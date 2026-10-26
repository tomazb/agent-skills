import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ["plan_osd_disk_prep.py", "check_rook_mgr_compatibility.py", "check_rook_health.py",
           "check_rgw_smoke.py", "rgw_s3_roundtrip.py", "rook_audit_expectations.sh"]


@pytest.mark.parametrize("helper", HELPERS)
def test_lifecycle_helpers_are_required_package_artifacts(validator, package_factory, helper):
    package = package_factory()
    path = "scripts/" + helper
    assert path in validator.REQUIRED_FILES
    (package / path).unlink()
    assert any(path in issue for issue in validator.validate_root(package))


@pytest.mark.parametrize("version,success", [("20.2.4", False), ("20.2.2", True)])
def test_documented_manager_gate_precedes_every_enablement(tmp_path, version, success):
    text = (ROOT / "references" / "install-and-preflight.md").read_text()
    block = next(b for b in re.findall(r"```bash\n(.*?)```", text, re.S)
                 if "check_rook_mgr_compatibility.py" in b)
    oc = tmp_path / "oc"
    log = tmp_path / "commands"
    oc.write_text("#!/usr/bin/env python3\nimport sys,json\n"
                  + f"with open({str(log)!r}, 'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                  + f"print('ceph version {version} (fake)') if sys.argv[-2:] == ['ceph','version'] else None\n")
    oc.chmod(0o755)
    result = subprocess.run(["bash", "-c", block], cwd=ROOT,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True, text=True, timeout=10)
    assert (result.returncode == 0) is success, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    mutations = [c for c in calls if "enable" in c or "set" in c]
    assert bool(mutations) is success
    assert all(c[:2] == ["--context", "<target-context>"] for c in calls)
