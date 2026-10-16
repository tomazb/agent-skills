from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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
if args[:1] == ["get"] and args[1] in ("objectbucket", "objectbuckets"):
    if fail == "objectbucket":
        sys.stderr.write("error: objectbucket\\n")
        raise SystemExit(1)
    sys.stdout.write(os.environ.get("OC_BUCKETS", ""))
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
        ["/bin/bash", str(SCRIPT), *args],
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
    result = _run(tmp_path, "--namespace", "rook-ceph")
    assert result.returncode == 2
    assert "refusing to delete rook-ceph" in result.stderr
    assert _log(tmp_path) == ""


def test_refuses_an_unsafe_name(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke;rm")
    assert result.returncode == 2
    assert "invalid namespace" in result.stderr
    assert _log(tmp_path) == ""


def test_deletes_a_clean_smoke_namespace(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke")
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace rook-rbd-smoke" in result.stdout
    log = _log(tmp_path)
    assert "delete namespace rook-rbd-smoke --ignore-not-found --wait=true --timeout=5m" in log
    assert "get namespaces -o name" in log
    assert "get pv -o json" in log
    assert "objectbucket" not in log


def test_accepts_the_aes256k_probe_namespace(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-aes256k-probe")
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace rook-rbd-aes256k-probe" in result.stdout


def test_namespace_still_present_fails(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "rook-cephfs-smoke",
        OC_NAMESPACES="namespace/default\nnamespace/rook-cephfs-smoke\n",
    )
    assert result.returncode == 1
    assert "rook-cephfs-smoke still exists" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_leftover_pv_fails(tmp_path):
    pv_json = (
        '{"items":[{"metadata":{"name":"pvc-left"},'
        '"spec":{"claimRef":{"namespace":"rook-rbd-smoke","name":"rbd-smoke-pvc"}}}]}'
    )
    result = _run(
        tmp_path,
        "--namespace",
        "rook-rbd-smoke",
        OC_PV_JSON=pv_json,
        CLEANUP_PV_WAIT_SECONDS="0",
    )
    assert result.returncode == 1
    assert "leftover PVs still claim rook-rbd-smoke" in result.stderr
    assert "pvc-left" in result.stderr
    assert "Retain" not in result.stderr
    assert "deleted smoke namespace" not in result.stdout
    assert _log(tmp_path).count("get pv -o json") == 1


def test_pv_in_another_namespace_is_kept(tmp_path):
    pv_json = (
        '{"items":[{"metadata":{"name":"pvc-app"},'
        '"spec":{"claimRef":{"namespace":"app","name":"data"}}}]}'
    )
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke", OC_PV_JSON=pv_json)
    assert result.returncode == 0, result.stderr


def _bucket(namespace: str, claim: str, ob_name: str) -> str:
    return json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": ob_name},
                    "spec": {"claimRef": {"namespace": namespace, "name": claim}},
                }
            ]
        }
    )


def test_object_bucket_leftover_fails_only_with_object_flag(tmp_path):
    buckets = _bucket(
        "rook-rgw-smoke",
        "rook-ceph-obc",
        "obc-rook-rgw-smoke-rook-ceph-obc",
    )
    without = _run(tmp_path, "--namespace", "rook-rgw-smoke", OC_BUCKETS=buckets)
    assert without.returncode == 0, without.stderr
    assert "objectbucket" not in _log(tmp_path)

    with_flag = _run(tmp_path, "--namespace", "rook-rgw-smoke", "--object", OC_BUCKETS=buckets)
    assert with_flag.returncode == 1
    assert "leftover ObjectBuckets" in with_flag.stderr
    assert "obc-rook-rgw-smoke-rook-ceph-obc" in with_flag.stderr
    assert "deleted smoke namespace" not in with_flag.stdout


def test_object_bucket_whose_name_contains_the_namespace_is_kept(tmp_path):
    buckets = _bucket(
        "team-rook-rgw-smoke",
        "obc",
        "obc-team-rook-rgw-smoke-obc",
    )
    result = _run(tmp_path, "--namespace", "rook-rgw-smoke", "--object", OC_BUCKETS=buckets)
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace rook-rgw-smoke" in result.stdout


def test_failed_delete_is_not_success(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke", OC_FAIL="delete")
    assert result.returncode == 1
    assert "failed to delete rook-rbd-smoke" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_failed_pv_query_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke", OC_FAIL="pv")
    assert result.returncode == 1
    assert "could not inspect PVs - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_unparsed_pv_list_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke", OC_PV_JSON="not-json")
    assert result.returncode == 1
    assert "could not inspect PVs - cleanup unverified" in result.stderr


LEFT_PV = (
    '{"items":[{"metadata":{"name":"pvc-left"},'
    '"spec":{"claimRef":{"namespace":"rook-rbd-smoke","name":"rbd-smoke-pvc"},'
    '"persistentVolumeReclaimPolicy":"{policy}"}}]}'
)


def test_pv_that_clears_during_the_wait_passes(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "rook-rbd-smoke",
        OC_PV_JSON=LEFT_PV.replace("{policy}", "Delete"),
        OC_PV_JSON_AFTER='{"items":[]}',
        CLEANUP_PV_WAIT_SECONDS="2",
    )
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace rook-rbd-smoke" in result.stdout
    assert _log(tmp_path).count("get pv -o json") == 2


def test_retained_leftover_pv_is_named_in_the_error(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "rook-rbd-smoke",
        OC_PV_JSON=LEFT_PV.replace("{policy}", "Retain"),
        CLEANUP_PV_WAIT_SECONDS="0",
    )
    assert result.returncode == 1
    assert "leftover PVs still claim rook-rbd-smoke" in result.stderr
    assert "persistentVolumeReclaimPolicy is Retain" in result.stderr
    assert "pvc-left" in result.stderr


def test_invalid_pv_wait_exits_2_before_deleting(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "rook-rbd-smoke",
        CLEANUP_PV_WAIT_SECONDS="soon",
    )
    assert result.returncode == 2
    assert "invalid CLEANUP_PV_WAIT_SECONDS" in result.stderr
    assert _log(tmp_path) == ""


def test_failed_namespace_list_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke", OC_FAIL="namespaces")
    assert result.returncode == 1
    assert "could not list namespaces - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_empty_namespace_list_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rbd-smoke", OC_NAMESPACES="")
    assert result.returncode == 1
    assert "could not list namespaces - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_failed_objectbucket_query_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "rook-rgw-smoke", "--object", OC_FAIL="objectbucket")
    assert result.returncode == 1
    assert "could not inspect ObjectBuckets - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout
