import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def invoke(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, timeout=5)


def test_disk_reuse_defaults_to_metadata_reset():
    result = invoke("plan_osd_disk_prep.py")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["method"] == "bluestore-metadata-reset"
    assert "dd if=/dev/zero" not in result.stdout


def test_full_erase_requires_explicit_sanitization_intent():
    result = invoke("plan_osd_disk_prep.py", "--intent", "sanitize", "--device-class", "virtio")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["method"] == "full-disk-zero"


def test_reuse_rejects_sanitization_capabilities_instead_of_ignoring_them():
    result = invoke("plan_osd_disk_prep.py", "--sanicap", "2")
    assert result.returncode == 2
    assert "--intent sanitize" in result.stderr


@pytest.mark.parametrize("version", ["20.2.3", "20.2.4", "20.2.99", "garbage", "20.2.4-rc1"])
def test_manager_gate_refuses_affected_or_unverified_versions(version):
    result = invoke("check_rook_mgr_compatibility.py", "--version", version)
    assert result.returncode != 0
    assert "enable" not in result.stdout


@pytest.mark.parametrize("version", ["19.2.6", "20.2.2"])
def test_manager_gate_accepts_versions_outside_the_known_node_proxy_regression(version):
    result = invoke("check_rook_mgr_compatibility.py", "--version", version)
    assert result.returncode == 0, result.stderr
