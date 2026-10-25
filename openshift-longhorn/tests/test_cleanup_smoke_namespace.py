from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_smoke_namespace.sh"

OC = """\
#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]
log = os.environ.get("OC_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(" ".join(args) + "\\n")
if args[:1] == ["--context"]:
    args = args[2:]
fail = os.environ.get("OC_FAIL", "")
if args[:2] == ["delete", "namespace"]:
    if fail == "delete":
        sys.stderr.write("error: timed out waiting for namespace\\n")
        raise SystemExit(1)
    raise SystemExit(0)
if args[:1] == ["get"] and args[1] in ("namespaces", "namespace"):
    if fail == "namespaces":
        sys.stderr.write("error: namespaces\\n")
        raise SystemExit(1)
    sys.stdout.write(os.environ.get("OC_NAMESPACES", "namespace/default\\nnamespace/kube-system\\n"))
    raise SystemExit(0)
if args[:1] == ["api-resources"]:
    if fail == "snapshot-discovery":
        sys.stderr.write("error: discovery forbidden\\n")
        raise SystemExit(1)
    sys.stdout.write(os.environ.get("OC_SNAPSHOT_APIS", ""))
    raise SystemExit(0)
if args[:2] == ["get", "volumesnapshotcontents.snapshot.storage.k8s.io"]:
    if fail == "snapshot-contents":
        sys.stderr.write("error: contents forbidden\\n")
        raise SystemExit(1)
    count_file = (log or "oc") + ".snapshotcount"
    seen = 0
    if os.path.exists(count_file):
        with open(count_file, encoding="utf-8") as fh:
            seen = int(fh.read() or "0")
    with open(count_file, "w", encoding="utf-8") as fh:
        fh.write(str(seen + 1))
    if seen >= 1 and "OC_SNAPSHOT_JSON_AFTER" in os.environ:
        sys.stdout.write(os.environ["OC_SNAPSHOT_JSON_AFTER"])
        raise SystemExit(0)
    sys.stdout.write(os.environ.get("OC_SNAPSHOT_JSON", '{"items":[]}'))
    raise SystemExit(0)
if args[:2] == ["get", "pv"]:
    if fail == "pv":
        sys.stderr.write("error: pv\\n")
        raise SystemExit(1)
    count_file = (log or "oc") + ".pvcount"
    seen = 0
    if os.path.exists(count_file):
        with open(count_file, encoding="utf-8") as fh:
            seen = int(fh.read() or "0")
    with open(count_file, "w", encoding="utf-8") as fh:
        fh.write(str(seen + 1))
    if seen >= 1 and "OC_PV_JSON_AFTER" in os.environ:
        sys.stdout.write(os.environ["OC_PV_JSON_AFTER"])
        raise SystemExit(0)
    sys.stdout.write(os.environ.get("OC_PV_JSON", '{"items":[]}'))
    raise SystemExit(0)
sys.stderr.write("unexpected oc " + " ".join(args) + "\\n")
raise SystemExit(99)
"""


def _run(tmp_path: Path, *args: str, **env_extra: str) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    oc = bindir / "oc"
    oc.write_text(OC, encoding="utf-8")
    oc.chmod(0o755)
    log = tmp_path / "oc.log"
    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["OC_LOG"] = str(log)
    env.update(env_extra)
    return subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _log(tmp_path: Path) -> str:
    path = tmp_path / "oc.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_help_exits_zero(tmp_path):
    result = _run(tmp_path, "--help")
    assert result.returncode == 0, result.stderr
    assert "--namespace" in result.stdout
    assert _log(tmp_path) == ""


def test_missing_namespace_exits_2(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "missing --namespace" in result.stderr
    assert _log(tmp_path) == ""


def test_refuses_a_live_namespace(tmp_path):
    result = _run(tmp_path, "--namespace", "openshift-storage")
    assert result.returncode == 2
    assert "refusing to delete openshift-storage" in result.stderr
    assert _log(tmp_path) == ""


def test_refuses_an_unsafe_name(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke;rm")
    assert result.returncode == 2
    assert "invalid namespace" in result.stderr
    assert _log(tmp_path) == ""


def test_deletes_a_clean_smoke_namespace(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke")
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace longhorn-rbd-smoke" in result.stdout
    log = _log(tmp_path)
    assert "delete namespace longhorn-rbd-smoke --ignore-not-found --wait=true --timeout=5m" in log
    assert "get namespaces -o name" in log
    assert "get pv -o json" in log
    assert "objectbucket" not in log


def test_accepts_the_asset_smoke_namespace(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-smoke")
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace longhorn-smoke" in result.stdout


def test_namespace_still_present_fails(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "longhorn-cephfs-smoke",
        OC_NAMESPACES="namespace/default\nnamespace/longhorn-cephfs-smoke\n",
    )
    assert result.returncode == 1
    assert "longhorn-cephfs-smoke still exists" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_leftover_pv_fails(tmp_path):
    pv_json = (
        '{"items":[{"metadata":{"name":"pvc-left"},'
        '"spec":{"claimRef":{"namespace":"longhorn-rbd-smoke","name":"rbd-smoke-pvc"}}}]}'
    )
    result = _run(
        tmp_path,
        "--namespace",
        "longhorn-rbd-smoke",
        OC_PV_JSON=pv_json,
        CLEANUP_PV_WAIT_SECONDS="0",
    )
    assert result.returncode == 1
    assert "leftover PVs still claim longhorn-rbd-smoke" in result.stderr
    assert "pvc-left" in result.stderr
    assert "Retain" not in result.stderr
    assert "deleted smoke namespace" not in result.stdout
    assert _log(tmp_path).count("get pv -o json") == 1


def test_pv_in_another_namespace_is_kept(tmp_path):
    pv_json = (
        '{"items":[{"metadata":{"name":"pvc-app"},'
        '"spec":{"claimRef":{"namespace":"app","name":"data"}}}]}'
    )
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke", OC_PV_JSON=pv_json)
    assert result.returncode == 0, result.stderr


def test_failed_delete_is_not_success(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke", OC_FAIL="delete")
    assert result.returncode == 1
    assert "failed to delete longhorn-rbd-smoke" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_failed_pv_query_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke", OC_FAIL="pv")
    assert result.returncode == 1
    assert "could not inspect PVs - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_unparsed_pv_list_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke", OC_PV_JSON="not-json")
    assert result.returncode == 1
    assert "could not inspect PVs - cleanup unverified" in result.stderr



@pytest.mark.parametrize("payload", [
    "null", "[]", "{}",
    '{"items": null}', '{"items": {}}', '{"items": "not-a-list"}',
    '{"items": [null]}', '{"items": [{}]}',
    '{"items": [{"metadata": {}, "spec": {"claimRef": "invalid"}}]}',
    '{"kind": "PersistentVolume", "metadata": {}}',
    '{"kind": "PersistentVolume", "spec": {}}',
])
def test_malformed_pv_inventory_fails_closed(tmp_path, payload):
    """A successful oc command is insufficient without a valid PV response."""
    result = _run(
        tmp_path, "--namespace", "storage-smoke",
        OC_PV_JSON=payload, CLEANUP_PV_WAIT_SECONDS="0",
    )
    assert result.returncode == 1
    assert "could not inspect PVs - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_single_pv_inventory_checks_namespace_claim(tmp_path):
    """A valid single-PV API response must not be mistaken for an empty list."""
    pv = json.dumps({
        "kind": "PersistentVolume",
        "metadata": {"name": "pvc-left"},
        "spec": {"claimRef": {"namespace": "storage-smoke", "name": "smoke-pvc"}},
    })
    result = _run(
        tmp_path, "--namespace", "storage-smoke",
        OC_PV_JSON=pv, CLEANUP_PV_WAIT_SECONDS="0",
    )
    assert result.returncode == 1
    assert "leftover PVs still claim storage-smoke" in result.stderr
    assert "pvc-left" in result.stderr
    assert "could not inspect PVs" not in result.stderr


LEFT_PV = (
    '{"items":[{"metadata":{"name":"pvc-left"},'
    '"spec":{"claimRef":{"namespace":"longhorn-rbd-smoke","name":"rbd-smoke-pvc"},'
    '"persistentVolumeReclaimPolicy":"{policy}"}}]}'
)


def test_pv_that_clears_during_the_wait_passes(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "longhorn-rbd-smoke",
        OC_PV_JSON=LEFT_PV.replace("{policy}", "Delete"),
        OC_PV_JSON_AFTER='{"items":[]}',
        CLEANUP_PV_WAIT_SECONDS="2",
    )
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace longhorn-rbd-smoke" in result.stdout
    assert _log(tmp_path).count("get pv -o json") == 2


def test_retained_leftover_pv_is_named_in_the_error(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "longhorn-rbd-smoke",
        OC_PV_JSON=LEFT_PV.replace("{policy}", "Retain"),
        CLEANUP_PV_WAIT_SECONDS="0",
    )
    assert result.returncode == 1
    assert "leftover PVs still claim longhorn-rbd-smoke" in result.stderr
    assert "persistentVolumeReclaimPolicy is Retain" in result.stderr
    assert "pvc-left" in result.stderr


def test_invalid_pv_wait_exits_2_before_deleting(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "longhorn-rbd-smoke",
        CLEANUP_PV_WAIT_SECONDS="soon",
    )
    assert result.returncode == 2
    assert "invalid CLEANUP_PV_WAIT_SECONDS" in result.stderr
    assert _log(tmp_path) == ""


def test_failed_namespace_list_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke", OC_FAIL="namespaces")
    assert result.returncode == 1
    assert "could not list namespaces - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_empty_namespace_list_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "longhorn-rbd-smoke", OC_NAMESPACES="")
    assert result.returncode == 1
    assert "could not list namespaces - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


SNAPSHOT_APIS = (
    "volumesnapshotclasses.snapshot.storage.k8s.io\n"
    "volumesnapshotcontents.snapshot.storage.k8s.io\n"
    "volumesnapshots.snapshot.storage.k8s.io\n"
)


def _snapshot_content(namespace: str, policy: str = "Delete") -> str:
    return json.dumps({"items": [{
        "metadata": {"name": "snapshot-content-left"},
        "spec": {
            "volumeSnapshotRef": {"namespace": namespace, "name": "smoke-snapshot"},
            "deletionPolicy": policy,
        },
    }]})


def test_snapshot_apis_absent_is_not_applicable_after_successful_discovery(tmp_path):
    result = _run(tmp_path, "--namespace", "storage-smoke", OC_SNAPSHOT_APIS="")
    assert result.returncode == 0, result.stderr
    assert "api-resources --api-group=snapshot.storage.k8s.io -o name" in _log(tmp_path)
    assert "get volumesnapshotcontents" not in _log(tmp_path)


@pytest.mark.parametrize("namespace", ["app", "team-storage-smoke", "storage-smoke-extra"])
def test_snapshot_content_in_other_namespace_is_kept(tmp_path, namespace):
    result = _run(
        tmp_path, "--namespace", "storage-smoke",
        OC_SNAPSHOT_APIS=SNAPSHOT_APIS,
        OC_SNAPSHOT_JSON=_snapshot_content(namespace),
    )
    assert result.returncode == 0, result.stderr
    assert "get volumesnapshotcontents.snapshot.storage.k8s.io -o json" in _log(tmp_path)


def test_retained_snapshot_content_fails(tmp_path):
    result = _run(
        tmp_path, "--namespace", "storage-smoke",
        OC_SNAPSHOT_APIS=SNAPSHOT_APIS,
        OC_SNAPSHOT_JSON=_snapshot_content("storage-smoke", "Retain"),
        CLEANUP_PV_WAIT_SECONDS="0",
    )
    assert result.returncode == 1
    assert "leftover VolumeSnapshotContents" in result.stderr
    assert "storage-smoke" in result.stderr
    assert "snapshot-content-left" in result.stderr
    assert "deletionPolicy is Retain" in result.stderr
    assert "deleted smoke namespace" not in result.stdout
    log = _log(tmp_path)
    assert log.count("get volumesnapshotcontents.snapshot.storage.k8s.io -o json") == 1
    assert "delete volumesnapshotcontent" not in log
    assert "patch " not in log


def test_delete_snapshot_content_eventually_clears(tmp_path):
    result = _run(
        tmp_path, "--namespace", "storage-smoke",
        OC_SNAPSHOT_APIS=SNAPSHOT_APIS,
        OC_SNAPSHOT_JSON=_snapshot_content("storage-smoke"),
        OC_SNAPSHOT_JSON_AFTER='{"items":[]}',
        # Subprocess scheduling and whole-second SECONDS resolution make a
        # one-second polling test unreliable on loaded CI runners.
        CLEANUP_PV_WAIT_SECONDS="3",
    )
    assert result.returncode == 0, result.stderr
    assert _log(tmp_path).count("get volumesnapshotcontents.snapshot.storage.k8s.io -o json") == 2


@pytest.mark.parametrize("failure", ["snapshot-discovery", "snapshot-contents"])
def test_failed_snapshot_audit_is_unverified(tmp_path, failure):
    result = _run(
        tmp_path, "--namespace", "storage-smoke",
        OC_SNAPSHOT_APIS=SNAPSHOT_APIS, OC_FAIL=failure,
    )
    assert result.returncode == 1
    assert "cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


@pytest.mark.parametrize("payload", [
    "", "not-json", "null", "[]", "{}", '{"items":null}',
    '{"items":{}}', '{"items":[null]}', '{"items":[{"spec":[]}]}',
    '{"items":[{"spec":{"volumeSnapshotRef":"storage-smoke"}}]}',
])
def test_invalid_snapshot_list_fails_closed(tmp_path, payload):
    result = _run(
        tmp_path, "--namespace", "storage-smoke",
        OC_SNAPSHOT_APIS=SNAPSHOT_APIS, OC_SNAPSHOT_JSON=payload,
    )
    assert result.returncode == 1
    assert "cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


@pytest.mark.parametrize("discovery", ["not discovery output", "volumesnapshots.snapshot.storage.k8s.io\n"])
def test_invalid_snapshot_discovery_fails_closed(tmp_path, discovery):
    result = _run(
        tmp_path, "--namespace", "storage-smoke", OC_SNAPSHOT_APIS=discovery,
    )
    assert result.returncode == 1
    assert "cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_context_is_forwarded_to_every_cleanup_command(tmp_path):
    result = _run(
        tmp_path, "--namespace", "storage-smoke", "--context", "<target-context>",
        OC_SNAPSHOT_APIS=SNAPSHOT_APIS,
    )
    assert result.returncode == 0, result.stderr
    lines = _log(tmp_path).splitlines()
    assert len(lines) == 5
    assert all(line.startswith("--context <target-context> ") for line in lines)


@pytest.mark.parametrize("args", [("--context",), ("--context=",), ("--context", "--namespace")])
def test_missing_context_value_fails_before_deleting(tmp_path, args):
    result = _run(tmp_path, "--namespace", "storage-smoke", *args)
    assert result.returncode == 2
    assert "missing value for --context" in result.stderr
    assert _log(tmp_path) == ""
