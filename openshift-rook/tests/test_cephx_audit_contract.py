"""Execute the documented full-key audit; credentials must never be printed."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REFERENCE = Path(__file__).resolve().parents[1] / "references/validation-hardening.md"


@pytest.mark.parametrize("legacy_location", [None, "key", "pending_key", "expiring_key", "rotating"])
def test_full_audit(tmp_path, legacy_location):
    def key(kind):
        return {"type": 2 if kind == "aes256k" else 1, "type_str": kind, "secret": "DO-NOT-PRINT"}

    auth = {name: key("aes" if legacy_location == name else "aes256k")
            for name in ("key", "pending_key", "expiring_key")}
    fixture = {"data": {"secrets": [{"entity": {"type": 8, "type_str": "client"}, "auth": auth},
                                   {"auth": {"pending_key": {"type": 0, "type_str": "none"}}}],
                        "rotating_secrets": [{"entity": {"type": 1, "type_str": "mon"},
                                              "secrets": {"keys": [{"expiring_key": {
                            "key": key("aes" if legacy_location == "rotating" else "aes256k")}}]}}]}}
    run = execute(tmp_path, fixture)
    assert run.returncode == (0 if legacy_location is None else 1), run.stderr
    assert "DO-NOT-PRINT" not in run.stdout + run.stderr
    assert ("All audited keys use aes256k" in run.stdout) == (legacy_location is None)
    if legacy_location is None:
        assert 'Audited key types: {"aes256k": 4}' in run.stdout


def execute(tmp_path, fixture, *, fail=False):
    source = tmp_path / "fixture.json"
    source.write_text(json.dumps(fixture))
    oc = tmp_path / "oc"
    oc.write_text("""#!/usr/bin/python3
import os, sys
from pathlib import Path
assert sys.argv[1:] == ['-n', 'rook-ceph', 'exec', 'deploy/rook-ceph-tools', '--',
                       'ceph', 'auth', 'dump-keys', '--format=json']
if os.environ['OC_FAIL'] == 'true':
    raise SystemExit(42)
print(Path(os.environ['OC_FIXTURE']).read_text())
""")
    oc.chmod(0o755)
    blocks = re.findall(r"```bash\n(.*?)```", REFERENCE.read_text(), re.DOTALL)
    script = next(b for b in blocks if "# Audit all CephX key types" in b)
    return subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", script],
                          env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                               "OC_FIXTURE": str(source), "OC_FAIL": str(fail).lower()},
                          capture_output=True, text=True)


@pytest.mark.parametrize("fixture", [{}, {"data": {"secrets": [], "rotating_secrets": []}},
                                     {"data": {"secrets": [{"auth": {"key": {"type": 99, "type_str": "unknown"}}}], "rotating_secrets": []}},
                                     {"data": {"secrets": [{"auth": {"pending_key": {"type": 0, "type_str": "none"}}}], "rotating_secrets": []}}])
def test_empty_or_unknown_audit_cannot_pass(tmp_path, fixture):
    assert execute(tmp_path, fixture).returncode != 0


def test_failed_audit_cannot_pass(tmp_path):
    assert execute(tmp_path, {}, fail=True).returncode != 0


@pytest.mark.parametrize("broken_key", [{}, {"type": 1, "type_str": "aes256k"}, "opaque-key", None])
def test_unrecognized_key_among_valid_keys_cannot_pass(tmp_path, broken_key):
    fixture = {"data": {"secrets": [{"auth": {
        "key": {"type": 2, "type_str": "aes256k"}, "pending_key": broken_key}}],
        "rotating_secrets": []}}
    assert execute(tmp_path, fixture).returncode != 0
