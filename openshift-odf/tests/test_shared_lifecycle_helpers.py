"""Keep reusable data-path logic aligned while preserving ODF lifecycle policy."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ["plan_osd_disk_prep.py", "check_odf_health.py", "check_object_smoke.py",
           "rgw_s3_roundtrip.py", "odf_audit_expectations.sh", "odf_common.sh", "classify_rook_ownership.sh"]


@pytest.mark.parametrize("helper", HELPERS)
def test_helpers_are_required_package_artifacts(validator, package_factory, helper):
    root = package_factory()
    path = "scripts/" + helper
    assert path in validator.REQUIRED_FILES
    (root / path).unlink()
    assert any(path in issue for issue in validator.validate_root(root))


def test_sigv4_client_stays_identical_across_skills():
    assert (ROOT / "scripts" / "rgw_s3_roundtrip.py").read_bytes() == (
        ROOT.parent / "openshift-rook" / "scripts" / "rgw_s3_roundtrip.py").read_bytes()


def test_read_only_observation_engine_stays_identical_across_skills():
    paths = [ROOT / "scripts" / "check_odf_health.py",
             ROOT.parent / "openshift-rook" / "scripts" / "check_rook_health.py"]
    engines = [next(n for n in ast.parse(p.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "observe") for p in paths]
    assert ast.dump(engines[0]) == ast.dump(engines[1])


def test_explicit_sanitization_uses_the_shared_capability_selector():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_osd_disk_prep.py"),
        "--intent", "sanitize", "--device-class", "virtio"], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["method"] == "full-disk-zero"


def test_odf_health_cli_targets_only_the_odf_namespace(monkeypatch):
    spec = importlib.util.spec_from_file_location("odf_health_policy", ROOT / "scripts" / "check_odf_health.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    seen = []
    monkeypatch.setattr(module, "observe", lambda args: seen.append(args.namespace) or {"status": "passed"})
    assert module.main(["--context", "target"]) == 0
    assert seen == ["openshift-storage"]
    assert module.main(["--context", "target", "--namespace", "rook-ceph"]) == 2
