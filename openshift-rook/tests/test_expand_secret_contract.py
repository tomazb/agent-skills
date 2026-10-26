"""StorageClass examples and the expansion-secret check must name resizer credentials."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "references/validation-hardening.md"
REFERENCES = {
    "rbd": (ROOT / "references/rbd-block-pools.md", "rook-ceph-block", "rook-csi-rbd-provisioner"),
    "cephfs": (ROOT / "references/cephfs-filesystem.md", "rook-cephfs", "rook-csi-cephfs-provisioner"),
}


def test_storageclass_examples_point_expansion_at_the_provisioner_secret():
    for path, class_name, secret_name in REFERENCES.values():
        docs = [doc for block in re.findall(r"```yaml\n(.*?)```", path.read_text(encoding="utf-8"), re.S)
                for doc in yaml.safe_load_all(block) if isinstance(doc, dict)]
        storage = next(doc for doc in docs if doc.get("kind") == "StorageClass" and doc["metadata"]["name"] == class_name)
        params = storage["parameters"]
        assert storage["allowVolumeExpansion"] is True
        assert params["csi.storage.k8s.io/controller-expand-secret-name"] == secret_name
        assert params["csi.storage.k8s.io/controller-expand-secret-namespace"] == "rook-ceph"
        assert params["csi.storage.k8s.io/controller-expand-secret-name"] == params["csi.storage.k8s.io/provisioner-secret-name"]
        assert params["csi.storage.k8s.io/controller-expand-secret-namespace"] == params["csi.storage.k8s.io/provisioner-secret-namespace"]
        text = path.read_text(encoding="utf-8")
        assert "does not fall back to the provisioner-secret parameters" in text


def storage_class(name, provisioner, *, expand=True, secret=None):
    item = {
        "metadata": {"name": name},
        "provisioner": provisioner,
        "parameters": {
            "csi.storage.k8s.io/provisioner-secret-name": "rook-csi-rbd-provisioner",
            "csi.storage.k8s.io/provisioner-secret-namespace": "rook-ceph",
        },
    }
    if expand:
        item["allowVolumeExpansion"] = True
    if secret is not None:
        namespace, secret_name = secret
        item["parameters"]["csi.storage.k8s.io/controller-expand-secret-name"] = secret_name
        item["parameters"]["csi.storage.k8s.io/controller-expand-secret-namespace"] = namespace
    return item


def secret_body():
    return {"data": {"userID": "DO-NOT-PRINT-ID", "userKey": "DO-NOT-PRINT-KEY"}}


def execute(tmp_path, items, secrets, *, fail_sc=False, context="", optimize=""):
    sc_path = tmp_path / "sc.json"
    sc_path.write_text(json.dumps({"items": items}))
    secret_path = tmp_path / "secrets.json"
    secret_path.write_text(json.dumps(secrets))
    log = tmp_path / "oc.log"
    log.unlink(missing_ok=True)
    oc = tmp_path / "oc"
    oc.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ["OC_LOG"]).open("a").write(json.dumps(args) + "\\n")
while args and args[0] in ("--context", "--kubeconfig"):
    args = args[2:]
if os.environ.get("OC_FAIL_SC") == "true" and args[:3] == ["get", "sc", "-o"]:
    sys.stderr.write("DO-NOT-PRINT\\n")
    raise SystemExit(1)
if args == ["get", "sc", "-o", "json"]:
    sys.stdout.write(Path(os.environ["SC_JSON"]).read_text())
    raise SystemExit(0)
if len(args) == 7 and args[0] == "-n" and args[2:4] == ["get", "secret"] and args[5:7] == ["-o", "json"]:
    key = args[1] + "/" + args[4]
    found = json.loads(Path(os.environ["SECRET_JSON"]).read_text())
    if key not in found:
        sys.stderr.write("DO-NOT-PRINT\\n")
        raise SystemExit(1)
    sys.stdout.write(json.dumps(found[key]))
    raise SystemExit(0)
sys.stderr.write("unexpected")
raise SystemExit(99)
""")
    oc.chmod(0o755)
    blocks = re.findall(r"```bash\n(.*?)```", VALIDATION.read_text(encoding="utf-8"), re.DOTALL)
    script = next(block for block in blocks if "omit resizer credentials" in block)
    command = ["/bin/bash", "--noprofile", "--norc", "-c", script]
    if context:
        command = [sys.executable, str(ROOT / "scripts/check_volume_expansion_secrets.py"), "--context", context]
    env = os.environ.copy()
    env.update({
        "PATH": str(tmp_path) + os.pathsep + env.get("PATH", ""),
        "SC_JSON": str(sc_path),
        "SECRET_JSON": str(secret_path),
        "OC_LOG": str(log),
        "OC_FAIL_SC": "true" if fail_sc else "false",
        "PYTHONOPTIMIZE": optimize,
    })
    import sys as _sys
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return completed, calls


def test_provisioner_secret_parameters_do_not_authorize_expansion(tmp_path):
    """htz2's classes set provisioner secrets and allowVolumeExpansion, and omit the resizer secret."""
    items = [
        storage_class("rook-ceph-block", "rook-ceph.rbd.csi.ceph.com"),
        storage_class("rook-cephfs", "rook-ceph.cephfs.csi.ceph.com"),
        storage_class("rook-ceph-rgw-obc", "rook-ceph.ceph.rook.io/bucket"),
    ]
    run, calls = execute(tmp_path, items, {})
    assert run.returncode != 0
    assert "without controller-expand secret parameters" in run.stderr
    assert "DO-NOT-PRINT" not in run.stdout + run.stderr
    assert calls == [["get", "sc", "-o", "json"]]


def test_expandable_classes_pass_when_the_secret_has_user_keys(tmp_path):
    items = [
        storage_class("rook-ceph-block", "rook-ceph.rbd.csi.ceph.com", secret=("rook-ceph", "rook-csi-rbd-provisioner")),
        storage_class("rook-cephfs", "rook-ceph.cephfs.csi.ceph.com", secret=("rook-ceph", "rook-csi-cephfs-provisioner")),
        storage_class("rook-ceph-rgw-obc", "rook-ceph.ceph.rook.io/bucket"),
        storage_class("plain-rbd", "rook-ceph.rbd.csi.ceph.com", expand=False),
    ]
    secrets = {
        "rook-ceph/rook-csi-rbd-provisioner": secret_body(),
        "rook-ceph/rook-csi-cephfs-provisioner": secret_body(),
    }
    run, calls = execute(tmp_path, items, secrets)
    assert run.returncode == 0, run.stderr
    assert "OK rook-ceph-block secret rook-ceph/rook-csi-rbd-provisioner" in run.stdout
    assert "OK rook-cephfs secret rook-ceph/rook-csi-cephfs-provisioner" in run.stdout
    assert "DO-NOT-PRINT" not in run.stdout + run.stderr
    assert ["-n", "rook-ceph", "get", "secret", "rook-csi-rbd-provisioner", "-o", "json"] in calls
    assert ["-n", "rook-ceph", "get", "secret", "rook-csi-cephfs-provisioner", "-o", "json"] in calls


def test_shared_secret_is_read_once(tmp_path):
    items = [
        storage_class("one", "custom.rbd.csi.ceph.com", secret=("rook-ceph", "shared")),
        storage_class("two", "custom.cephfs.csi.ceph.com", secret=("rook-ceph", "shared")),
    ]
    run, calls = execute(tmp_path, items, {"rook-ceph/shared": secret_body()})
    assert run.returncode == 0, run.stderr
    secret_calls = [call for call in calls if "secret" in call]
    assert secret_calls == [["-n", "rook-ceph", "get", "secret", "shared", "-o", "json"]]


def test_missing_secret_and_missing_key_fail_without_printing_data(tmp_path):
    items = [storage_class("rook-ceph-block", "rook-ceph.rbd.csi.ceph.com", secret=("rook-ceph", "rook-csi-rbd-provisioner"))]
    missing, _ = execute(tmp_path, items, {})
    assert missing.returncode != 0
    assert "cannot read secret rook-ceph/rook-csi-rbd-provisioner" in missing.stderr
    assert "DO-NOT-PRINT" not in missing.stdout + missing.stderr
    incomplete, _ = execute(tmp_path, items, {"rook-ceph/rook-csi-rbd-provisioner": {"data": {"userID": "DO-NOT-PRINT-ID"}}})
    assert incomplete.returncode != 0
    assert "missing userKey" in incomplete.stderr
    assert "DO-NOT-PRINT" not in incomplete.stdout + incomplete.stderr
    empty, _ = execute(tmp_path, items, {"rook-ceph/rook-csi-rbd-provisioner": {"data": {"userID": "DO-NOT-PRINT-ID", "userKey": ""}}})
    assert empty.returncode != 0
    assert "missing userKey" in empty.stderr
    assert "DO-NOT-PRINT" not in empty.stdout + empty.stderr


def test_empty_parameter_invalid_name_and_query_failure(tmp_path):
    blank = storage_class("rook-ceph-block", "rook-ceph.rbd.csi.ceph.com", secret=("rook-ceph", "   "))
    blank_run, blank_calls = execute(tmp_path, [blank], {})
    assert blank_run.returncode != 0
    assert "without controller-expand secret parameters" in blank_run.stderr
    assert blank_calls == [["get", "sc", "-o", "json"]]
    invalid = storage_class("rook-ceph-block", "rook-ceph.rbd.csi.ceph.com", secret=("rook-ceph", "../admin"))
    invalid_run, invalid_calls = execute(tmp_path, [invalid], {})
    assert invalid_run.returncode != 0
    assert "invalid controller-expand secret reference" in invalid_run.stderr
    assert invalid_calls == [["get", "sc", "-o", "json"]]
    failed, failed_calls = execute(tmp_path, [storage_class("rook-ceph-block", "rook-ceph.rbd.csi.ceph.com", expand=False)], {}, fail_sc=True)
    assert failed.returncode != 0
    assert "oc get sc failed" in failed.stderr
    assert "DO-NOT-PRINT" not in failed.stdout + failed.stderr
    assert failed_calls == [["get", "sc", "-o", "json"]]


def test_context_is_forwarded_and_optimize_does_not_skip_the_check(tmp_path):
    items = [storage_class("rook-ceph-block", "rook-ceph.rbd.csi.ceph.com")]
    run, calls = execute(tmp_path, items, {}, context="target-context", optimize="2")
    assert run.returncode != 0
    assert calls == [["--context", "target-context", "get", "sc", "-o", "json"]]
    assert "without controller-expand secret parameters" in run.stderr
