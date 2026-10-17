import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REFERENCE = (
    Path(__file__).resolve().parents[1] / "references" / "vm-storage-profiles.md"
)
NAMESPACE = "odf-vm-smoke"

# Only the external CLI is mocked. Bash executes the complete documented block,
# including its error handling, branches, patch payload, and Pod manifest.
OC = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
namespace_at = args.index("-n")
assert args[namespace_at + 1] == os.environ["OC_NAMESPACE"]
del args[namespace_at:namespace_at + 2]
manifest = sys.stdin.read() if args == ["apply", "-f", "-"] else ""
log = Path(os.environ["OC_LOG"])
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"args": args, "manifest": manifest}) + "\n")
created = log.with_suffix(".dv-created")
if (args[0] == os.environ.get("OC_FAIL_ACTION")
        and (not os.environ.get("OC_FAIL_TARGET") or args[1] == os.environ["OC_FAIL_TARGET"])):
    sys.stderr.write("injected oc failure\n")
    raise SystemExit(42)
if args[:3] == ["get", "pvc", "default-sc-test-dv"] and os.environ["OC_DV_DELAY"] == "true" and not created.exists():
    sys.stderr.write("DataVolume PVC not created yet\n")
    raise SystemExit(1)
if args[:2] == ["get", "pvc"] and args[3] == "-o":
    if args[4] == "jsonpath={.spec.storageClassName}":
        value = os.environ["OC_GENERAL_SC"] if args[2] == "default-sc-test-pvc" else "vm-storage"
    elif args[2:] == ["default-sc-test-pvc", "-o", "jsonpath={.status.phase}"]:
        value = "Pending"
    else:
        raise SystemExit(99)
    sys.stdout.write(value)
elif args[:2] == ["get", "sc"] and args[3:] == ["-o", "jsonpath={.volumeBindingMode}"]:
    sys.stdout.write({"general-storage": os.environ["OC_PLAIN_MODE"], "vm-storage": os.environ["OC_DV_MODE"]}[args[2]])
elif args == ["patch", "vm", "default-sc-test-vm", "--type=merge", "-p", '{"spec":{"running":true}}']:
    pass
elif args == ["apply", "-f", "-"]:
    assert "claimName: default-sc-test-pvc" in manifest
    assert "name: default-sc-test-consumer" in manifest
    assert "claimName: default-sc-test-dv" not in manifest
elif args == ["wait", "pvc/default-sc-test-dv", "--for=create", "--timeout=120s"]:
    created.touch()
elif args[0] == "wait":
    assert args[1] in ("pvc/default-sc-test-pvc", "datavolume/default-sc-test-dv")
    assert args[2:] == (["--for=jsonpath={.status.phase}=Bound", "--timeout=120s"] if args[1].startswith("pvc/") else ["--for=condition=Ready", "--timeout=300s"])
else:
    sys.stderr.write("unexpected oc " + " ".join(args) + "\n")
    raise SystemExit(99)
"""


def _text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def _provisioning_script() -> str:
    # Extract the whole fence, so a missing set -e cannot be hidden by the test.
    blocks = re.findall(r"```bash\n(.*?)```", _text(), re.DOTALL)
    return next(block for block in blocks if "--for=condition=Ready" in block)


def test_plain_pvc_bind_wait_is_conditional():
    text = _text()
    select = text.index("Default-class selection and provisioning are separate checks")
    skip = text.index(
        "Skip the plain PVC bind wait when no general default is expected"
    )
    consumer = text.index("a pod that mounts `default-sc-test-pvc`")
    wait = text.index("oc wait -n odf-vm-smoke pvc/default-sc-test-pvc")
    assert select < skip < consumer < wait
    selection = text[
        text.index(
            "oc -n odf-vm-smoke get pvc default-sc-test-pvc -o jsonpath="
        ) : text.index("When a general default exists")
    ]
    assert "oc wait" not in selection


def _run(tmp_path: Path, *, caller_probe=False, **env_extra: str):
    oc = tmp_path / "oc"
    oc.write_text(OC, encoding="utf-8")
    oc.chmod(0o755)
    log = tmp_path / "oc.log"
    env = dict(
        os.environ,
        PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
        OC_LOG=str(log),
        OC_NAMESPACE=NAMESPACE,
        OC_GENERAL_SC="general-storage",
        OC_PLAIN_MODE="Immediate",
        OC_DV_MODE="Immediate",
        OC_FAIL_ACTION="",
        OC_FAIL_TARGET="",
        OC_DV_DELAY="false",
    )
    env.update(env_extra)
    script = _provisioning_script()
    command = ["/bin/bash"]
    if caller_probe:
        command += ["--noprofile", "--norc", "-i"]
        script = "set +e; set +u; set +o pipefail\n" + script + r"""
block_status=$?
case $- in *e*|*u*) exit 91;; esac
if shopt -qo pipefail; then exit 92; fi
printf 'caller survived with unchanged options\n'
exit "$block_status"
"""
    result = subprocess.run(
        command,
        input=script,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls


@pytest.mark.parametrize("dv_mode", ["Immediate", "WaitForFirstConsumer"])
@pytest.mark.parametrize(
    "general_sc,plain_mode",
    [
        ("", "Immediate"),
        ("general-storage", "Immediate"),
        ("general-storage", "WaitForFirstConsumer"),
    ],
)
def test_provisioning_uses_each_pvcs_own_binding_mode(
    tmp_path, dv_mode, general_sc, plain_mode
):
    result, calls = _run(
        tmp_path, OC_DV_MODE=dv_mode, OC_GENERAL_SC=general_sc, OC_PLAIN_MODE=plain_mode
    )
    assert result.returncode == 0, result.stderr
    args = [call["args"] for call in calls]
    dv_wait = next(
        i
        for i, cmd in enumerate(args)
        if cmd[:2] == ["wait", "datavolume/default-sc-test-dv"]
    )
    dv_class = args.index(
        ["get", "pvc", "default-sc-test-dv", "-o", "jsonpath={.spec.storageClassName}"]
    )
    dv_binding = args.index(
        ["get", "sc", "vm-storage", "-o", "jsonpath={.volumeBindingMode}"]
    )
    assert dv_class < dv_binding < dv_wait
    starts = [i for i, cmd in enumerate(args) if cmd[0] == "patch"]
    if dv_mode == "WaitForFirstConsumer":
        assert len(starts) == 1
        assert dv_binding < starts[0] < dv_wait
    else:
        assert not starts
    plain_waits = [
        i
        for i, cmd in enumerate(args)
        if cmd[:2] == ["wait", "pvc/default-sc-test-pvc"]
    ]
    consumers = [i for i, cmd in enumerate(args) if cmd[0] == "apply"]
    if general_sc:
        assert len(plain_waits) == 1
        assert plain_waits[0] < dv_wait
        if plain_mode == "WaitForFirstConsumer":
            assert len(consumers) == 1
            assert consumers[0] < plain_waits[0]
        else:
            assert not consumers
    else:
        assert not plain_waits
        assert not consumers
        assert "Pending is expected when no general default exists" in result.stdout


@pytest.mark.parametrize("action", ["patch", "apply", "get", "wait"])
def test_failed_provisioning_stops_verification(tmp_path, action):
    result, calls = _run(
        tmp_path,
        OC_PLAIN_MODE="WaitForFirstConsumer",
        OC_DV_MODE="WaitForFirstConsumer",
        OC_FAIL_ACTION=action,
    )
    assert result.returncode == 42, result.stderr
    assert calls[-1]["args"][0] == action
    assert not any(
        call["args"][:2] == ["wait", "datavolume/default-sc-test-dv"] for call in calls
    )


def test_failed_datavolume_readiness_wait_is_not_success(tmp_path):
    result, calls = _run(
        tmp_path,
        OC_GENERAL_SC="",
        OC_FAIL_ACTION="wait",
        OC_FAIL_TARGET="datavolume/default-sc-test-dv",
    )
    assert result.returncode == 42, result.stderr
    assert calls[-1]["args"][:2] == ["wait", "datavolume/default-sc-test-dv"]


@pytest.mark.parametrize("dv_mode", ["Immediate", "WaitForFirstConsumer"])
def test_delayed_datavolume_pvc_is_created_before_class_lookup(tmp_path, dv_mode):
    result, calls = _run(
        tmp_path, OC_GENERAL_SC="", OC_DV_MODE=dv_mode, OC_DV_DELAY="true"
    )
    assert result.returncode == 0, result.stderr
    args = [call["args"] for call in calls]
    created = args.index(
        ["wait", "pvc/default-sc-test-dv", "--for=create", "--timeout=120s"]
    )
    selected = args.index(
        ["get", "pvc", "default-sc-test-dv", "-o", "jsonpath={.spec.storageClassName}"]
    )
    assert created < selected


def test_failed_datavolume_creation_wait_stops_verification(tmp_path):
    result, calls = _run(tmp_path, OC_GENERAL_SC="", OC_FAIL_ACTION="wait")
    assert result.returncode == 42, result.stderr
    assert calls[-1]["args"] == [
        "wait",
        "pvc/default-sc-test-dv",
        "--for=create",
        "--timeout=120s",
    ]
    assert not any(
        call["args"][:3] == ["get", "pvc", "default-sc-test-dv"] for call in calls
    )


@pytest.mark.parametrize("fail_action,expected_status", [("", 0), ("patch", 42)])
def test_interactive_caller_survives_with_unchanged_options(
    tmp_path, fail_action, expected_status
):
    result, _ = _run(
        tmp_path,
        caller_probe=True,
        OC_DV_MODE="WaitForFirstConsumer",
        OC_FAIL_ACTION=fail_action,
    )
    assert result.returncode == expected_status, result.stderr
    assert "caller survived with unchanged options" in result.stdout
