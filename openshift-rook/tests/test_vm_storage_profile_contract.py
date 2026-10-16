import os
import subprocess
from pathlib import Path

REFERENCE = (
    Path(__file__).resolve().parents[1] / "references" / "vm-storage-profiles.md"
)

OC = """\
#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]
log = os.environ["OC_LOG"]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\\n")
    if args[:1] == ["apply"] and "-f" in args and "-" in args:
        fh.write(sys.stdin.read())
joined = " ".join(args)
if "jsonpath" in joined and "storageClassName" in joined:
    sys.stdout.write(os.environ.get("OC_SC_NAME", ""))
    raise SystemExit(0)
if "jsonpath" in joined and "status.phase" in joined:
    sys.stdout.write(os.environ.get("OC_PHASE", "Pending"))
    raise SystemExit(0)
if "jsonpath" in joined and "volumeBindingMode" in joined:
    sys.stdout.write(os.environ.get("OC_BINDING_MODE", "Immediate"))
    raise SystemExit(0)
if args[:1] in (["wait"], ["apply"]):
    raise SystemExit(0)
sys.stderr.write("unexpected oc " + joined + "\\n")
raise SystemExit(99)
"""


def _text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def _provisioning_script() -> str:
    text = _text()
    marker = "sc=$(oc -n rook-vm-smoke get pvc default-sc-test-pvc"
    start = text.index(marker)
    end = text.index("```", start)
    return text[start:end]


def test_plain_pvc_bind_wait_is_conditional():
    text = _text()
    select = text.index("Default-class selection and provisioning are separate checks")
    skip = text.index(
        "Skip the plain PVC bind wait when no general default is expected"
    )
    consumer = text.index("a pod that mounts `default-sc-test-pvc`")
    wait = text.index("oc wait -n rook-vm-smoke pvc/default-sc-test-pvc")
    assert select < skip < consumer < wait
    selection = text[
        text.index("oc -n rook-vm-smoke get pvc default-sc-test-pvc -o jsonpath=") : text.index(
            "When a general default exists"
        )
    ]
    assert "oc wait" not in selection


def _run(tmp_path: Path, **env_extra: str) -> tuple[subprocess.CompletedProcess[str], str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    oc = bindir / "oc"
    oc.write_text(OC, encoding="utf-8")
    oc.chmod(0o755)
    log = tmp_path / "oc.log"
    script = tmp_path / "provision.sh"
    script.write_text(_provisioning_script(), encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["OC_LOG"] = str(log)
    env.update(env_extra)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return result, log.read_text(encoding="utf-8")


def test_zero_default_skips_the_plain_pvc_wait(tmp_path):
    result, log = _run(tmp_path, OC_SC_NAME="", OC_PHASE="Pending")
    assert result.returncode == 0, result.stderr
    assert "Pending is expected when no general default exists" in result.stdout
    assert "pvc/default-sc-test-pvc" not in log
    assert "datavolume/default-sc-test-dv" in log
    assert "default-sc-test-consumer" not in log


def test_default_present_waits_for_the_plain_pvc(tmp_path):
    result, log = _run(
        tmp_path,
        OC_SC_NAME="rook-ceph-block",
        OC_BINDING_MODE="Immediate",
    )
    assert result.returncode == 0, result.stderr
    assert "Pending is expected" not in result.stdout
    pvc_wait = log.index("wait -n rook-vm-smoke pvc/default-sc-test-pvc")
    dv_wait = log.index("wait -n rook-vm-smoke datavolume/default-sc-test-dv")
    assert pvc_wait < dv_wait
    assert "default-sc-test-consumer" not in log


def test_wait_for_first_consumer_creates_a_pod_for_the_plain_pvc(tmp_path):
    result, log = _run(
        tmp_path,
        OC_SC_NAME="rook-ceph-block",
        OC_BINDING_MODE="WaitForFirstConsumer",
    )
    assert result.returncode == 0, result.stderr
    apply_at = log.index("apply -n rook-vm-smoke -f -")
    assert "claimName: default-sc-test-pvc" in log[apply_at:]
    assert "name: default-sc-test-consumer" in log[apply_at:]
    assert apply_at < log.index("wait -n rook-vm-smoke pvc/default-sc-test-pvc")
