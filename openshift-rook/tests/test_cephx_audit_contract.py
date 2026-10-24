"""Execute the documented full-key audit against a mocked external CLI."""

import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "references/validation-hardening.md"


def key(kind="aes256k"):
    return {"type": {"none": 0, "aes": 1, "aes256k": 2}[kind],
            "type_str": kind, "secret": "DO-NOT-PRINT"}


def inventory():
    return {"data": {
        "secrets": [
            {"entity": {"type": 8, "type_str": "client"},
             "auth": {"key": key(), "pending_key": key("none")}},
            {"auth": {"key": key()}},
        ],
        "rotating_secrets": [{"entity": {"type": 1, "type_str": "mon"},
                              "secrets": {"keys": [{"expiring_key": {"key": key()}},
                                                   {"expiring_key": {"key": key()}}]}}],
    }}


def execute(tmp_path, fixture, *, fail=False, optimize=""):
    source = tmp_path / "fixture.json"
    source.write_text(json.dumps(fixture))
    oc = tmp_path / "oc"
    oc.write_text("""#!/usr/bin/env python3
import os, sys
from pathlib import Path
if sys.argv[1:] != ['-n', 'rook-ceph', 'exec', 'deploy/rook-ceph-tools', '--',
                    'ceph', 'auth', 'dump-keys', '--format=json']:
    raise SystemExit(99)
if os.environ['OC_FAIL'] == 'true':
    raise SystemExit(42)
print(Path(os.environ['OC_FIXTURE']).read_text())
""")
    oc.chmod(0o755)
    blocks = re.findall(r"```bash\n(.*?)```", REFERENCE.read_text(), re.DOTALL)
    script = next(b for b in blocks if "# Audit all CephX key types" in b)
    return subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", script], cwd=ROOT,
                          env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                               "OC_FIXTURE": str(source), "OC_FAIL": str(fail).lower(),
                               "PYTHONOPTIMIZE": optimize}, capture_output=True, text=True)


@pytest.mark.parametrize("optimize", ["", "1", "2"])
def test_valid_inventory_and_unused_pending_slot(tmp_path, optimize):
    run = execute(tmp_path, inventory(), optimize=optimize)
    assert run.returncode == 0, run.stderr
    assert 'Audited key types: {"aes256k": 4}' in run.stdout
    assert "DO-NOT-PRINT" not in run.stdout + run.stderr


@pytest.mark.parametrize("location", ["primary", "pending", "first_rotating", "last_rotating"])
def test_legacy_key_rejected(tmp_path, location):
    fixture = inventory()
    if location in ("primary", "pending"):
        field = "key" if location == "primary" else "pending_key"
        fixture["data"]["secrets"][0]["auth"][field] = key("aes")
    else:
        index = 0 if location == "first_rotating" else 1
        fixture["data"]["rotating_secrets"][0]["secrets"]["keys"][index]["expiring_key"]["key"] = key("aes")
    run = execute(tmp_path, fixture)
    assert run.returncode != 0
    assert "All audited keys use aes256k" not in run.stdout
    assert "DO-NOT-PRINT" not in run.stdout + run.stderr


@pytest.mark.parametrize("bad", [None, [], {}, {"auth": None}, {"auth": {}},
                                 {"auth": {"pending_key": key("none")}}])
@pytest.mark.parametrize("optimize", ["", "1"])
def test_mixed_missing_auth_records_rejected(tmp_path, bad, optimize):
    fixture = inventory()
    fixture["data"]["secrets"].append(copy.deepcopy(bad))
    assert execute(tmp_path, fixture, optimize=optimize).returncode != 0


@pytest.mark.parametrize("bad", [None, [], {}, {"secrets": {}}, {"secrets": {"keys": []}},
                                 {"secrets": {"keys": [None]}}, {"secrets": {"keys": [{}]}},
                                 {"secrets": {"keys": [{"expiring_key": {}}]}}])
@pytest.mark.parametrize("optimize", ["", "1"])
def test_mixed_missing_rotating_records_rejected(tmp_path, bad, optimize):
    fixture = inventory()
    fixture["data"]["rotating_secrets"].append(copy.deepcopy(bad))
    assert execute(tmp_path, fixture, optimize=optimize).returncode != 0


@pytest.mark.parametrize("bad", [{}, {"type": 1, "type_str": "aes256k"}, "opaque-key", None,
                                 {"type": 99, "type_str": "unknown"}, key("none")])
@pytest.mark.parametrize("location", ["primary", "rotating"])
def test_invalid_present_keys_rejected(tmp_path, bad, location):
    fixture = inventory()
    if location == "primary":
        fixture["data"]["secrets"][0]["auth"]["key"] = bad
    else:
        fixture["data"]["rotating_secrets"][0]["secrets"]["keys"][1]["expiring_key"]["key"] = bad
    assert execute(tmp_path, fixture).returncode != 0


@pytest.mark.parametrize("field", ["secrets", "rotating_secrets"])
@pytest.mark.parametrize("bad", [None, {}, [], "unexpected"])
@pytest.mark.parametrize("optimize", ["", "1"])
def test_malformed_top_level_inventory_rejected(tmp_path, field, bad, optimize):
    fixture = inventory()
    fixture["data"][field] = bad
    assert execute(tmp_path, fixture, optimize=optimize).returncode != 0


def test_empty_document_and_failed_query_rejected(tmp_path):
    assert execute(tmp_path, {}).returncode != 0
    assert execute(tmp_path, inventory(), fail=True).returncode != 0
