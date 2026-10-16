from __future__ import annotations

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


def test_refuses_openshift_storage(tmp_path):
    result = _run(tmp_path, "--namespace", "openshift-storage")
    assert result.returncode == 2
    assert "refusing to delete openshift-storage" in result.stderr
    assert _log(tmp_path) == ""


def test_refuses_an_unsafe_name(tmp_path):
    result = _run(tmp_path, "--namespace", "odf-rbd-smoke;rm")
    assert result.returncode == 2
    assert "invalid namespace" in result.stderr
    assert _log(tmp_path) == ""


def test_deletes_a_clean_smoke_namespace(tmp_path):
    result = _run(tmp_path, "--namespace", "odf-rbd-smoke")
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace odf-rbd-smoke" in result.stdout
    log = _log(tmp_path)
    assert "delete namespace odf-rbd-smoke --ignore-not-found --wait=true --timeout=5m" in log
    assert "get namespaces -o name" in log
    assert "get pv -o json" in log
    assert "objectbucket" not in log


def test_accepts_the_asset_smoke_namespace(tmp_path):
    result = _run(tmp_path, "--namespace", "odf-smoke")
    assert result.returncode == 0, result.stderr
    assert "deleted smoke namespace odf-smoke" in result.stdout


def test_namespace_still_present_fails(tmp_path):
    result = _run(
        tmp_path,
        "--namespace",
        "odf-cephfs-smoke",
        OC_NAMESPACES="namespace/default\nnamespace/odf-cephfs-smoke\n",
    )
    assert result.returncode == 1
    assert "odf-cephfs-smoke still exists" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_leftover_pv_fails(tmp_path):
    pv_json = (
        '{"items":[{"metadata":{"name":"pvc-left"},'
        '"spec":{"claimRef":{"namespace":"odf-rbd-smoke","name":"rbd-smoke-pvc"}}}]}'
    )
    result = _run(tmp_path, "--namespace", "odf-rbd-smoke", OC_PV_JSON=pv_json)
    assert result.returncode == 1
    assert "leftover PVs still claim odf-rbd-smoke" in result.stderr
    assert "pvc-left" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_pv_in_another_namespace_is_kept(tmp_path):
    pv_json = (
        '{"items":[{"metadata":{"name":"pvc-app"},'
        '"spec":{"claimRef":{"namespace":"app","name":"data"}}}]}'
    )
    result = _run(tmp_path, "--namespace", "odf-rbd-smoke", OC_PV_JSON=pv_json)
    assert result.returncode == 0, result.stderr


def test_object_bucket_leftover_fails_only_with_object_flag(tmp_path):
    buckets = "objectbucket.objectbucket.io/obc-odf-object-smoke-object-smoke-obc\n"
    without = _run(tmp_path, "--namespace", "odf-object-smoke", OC_BUCKETS=buckets)
    assert without.returncode == 0, without.stderr
    assert "objectbucket" not in _log(tmp_path)

    with_flag = _run(tmp_path, "--namespace", "odf-object-smoke", "--object", OC_BUCKETS=buckets)
    assert with_flag.returncode == 1
    assert "leftover ObjectBuckets" in with_flag.stderr
    assert "obc-odf-object-smoke-object-smoke-obc" in with_flag.stderr
    assert "deleted smoke namespace" not in with_flag.stdout


def test_failed_objectbucket_query_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "odf-object-smoke", "--object", OC_FAIL="objectbucket")
    assert result.returncode == 1
    assert "could not inspect ObjectBuckets - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_failed_delete_is_not_success(tmp_path):
    result = _run(tmp_path, "--namespace", "odf-rbd-smoke", OC_FAIL="delete")
    assert result.returncode == 1
    assert "failed to delete odf-rbd-smoke" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_failed_pv_query_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "odf-rbd-smoke", OC_FAIL="pv")
    assert result.returncode == 1
    assert "could not inspect PVs - cleanup unverified" in result.stderr
    assert "deleted smoke namespace" not in result.stdout


def test_unparsed_pv_list_is_unverified(tmp_path):
    result = _run(tmp_path, "--namespace", "odf-rbd-smoke", OC_PV_JSON="not-json")
    assert result.returncode == 1
    assert "could not inspect PVs - cleanup unverified" in result.stderr
