"""Storage smoke flows must exercise point-in-time recovery, not just PVC I/O."""

import re
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
MODES = [
    ("openshift-rook", "rbd"), ("openshift-rook", "cephfs"),
    ("openshift-odf", "rbd"), ("openshift-odf", "cephfs"),
    ("openshift-longhorn", "v1"), ("openshift-longhorn", "v2"),
    ("openshift-lvm-storage", "fs"), ("openshift-lvm-storage", "block"),
]


@pytest.mark.parametrize("skill,mode", MODES)
def test_rendered_smoke_sources_are_explicitly_marked_disposable(tmp_path, skill, mode):
    manifest = tmp_path / "source.yaml"
    result = subprocess.run([
        sys.executable, str(ROOT / skill / "scripts/render_smoke_manifest.py"),
        "--mode", mode, "--namespace", "storage-test-smoke",
        "--storage-class", "test-storage", "--output", str(manifest),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    docs = list(yaml.safe_load_all(manifest.read_text(encoding="utf-8")))
    assert {d["kind"] for d in docs} == {"Namespace", "PersistentVolumeClaim", "Pod"}
    for doc in docs:
        assert doc["metadata"].get("labels", {}).get("app.kubernetes.io/part-of") == "storage-smoke"


@pytest.mark.parametrize("skill", sorted({s for s, _ in MODES}))
def test_minimum_smoke_flow_runs_snapshot_roundtrip_before_source_cleanup(skill):
    root = ROOT / skill
    guide = (root / "references/validation-hardening.md").read_text(encoding="utf-8")
    smoke = guide.split("## Smoke Test\n", 1)[1].split("\n## ", 1)[0]
    assert "python3 scripts/check_snapshot_smoke.py" in smoke
    assert "--source-pvc" in smoke and "--writer-pod" in smoke
    assert "--snapshot-class" in smoke and "--context" in smoke
    assert "unsupported" in smoke and "untested" in smoke
    assert "restored" in smoke and "cleanup" in smoke
    scripts = re.findall(r"```bash\n(.*?)```", smoke, re.S)
    assert any("check_snapshot_smoke.py" in script for script in scripts)


def test_snapshot_helpers_are_shipped_independently_in_each_storage_package():
    helpers = [(ROOT / skill / "scripts/check_snapshot_smoke.py").read_bytes()
               for skill in sorted({s for s, _ in MODES})]
    assert all(helper == helpers[0] for helper in helpers)


@pytest.mark.parametrize("skill", sorted({s for s, _ in MODES}))
@pytest.mark.parametrize("scenario,expected", [
    ("success", 0), ("snapshot-failed", 17),
    ("cleanup-failed", 1), ("namespace-exists", 1), ("discovery-failed", 19),
])
def test_documented_smoke_flow_preserves_errors_and_always_cleans_owned_sources(tmp_path, skill, scenario, expected):
    """Execute the published shell flow against fake CLIs, including its EXIT trap."""
    guide = (ROOT / skill / "references/validation-hardening.md").read_text(encoding="utf-8")
    smoke = guide.split("## Smoke Test\n", 1)[1].split("\n## ", 1)[0]
    block = next(b for b in re.findall(r"```bash\n(.*?)```", smoke, re.S)
                 if "check_snapshot_smoke.py" in b)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = '''import json, os, sys
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['SMOKE_CALL_LOG'], 'a') as out:
    out.write(json.dumps([tool, *args]) + '\\n')
scenario = os.environ['SMOKE_SCENARIO']
if tool == 'oc' and 'get' in args and 'namespace' in args:
    if scenario == 'namespace-exists': print('namespace/existing-smoke')
    if scenario == 'discovery-failed': sys.exit(19)
if tool == 'python3' and args[0] == 'scripts/check_snapshot_smoke.py':
    if scenario == 'snapshot-failed': sys.exit(17)
if tool == 'bash' and scenario == 'cleanup-failed': sys.exit(23)
'''
    for name in ["oc", "python3", "bash"]:
        executable = bindir / name
        executable.write_text("#!" + sys.executable + "\n" + fake, encoding="utf-8")
        executable.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", block],
                            cwd=tmp_path, capture_output=True, text=True,
                            env={**os.environ, "PATH": str(bindir) + ":/usr/bin:/bin",
                                 "SMOKE_CALL_LOG": str(log), "SMOKE_SCENARIO": scenario})
    assert result.returncode == expected, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    cleanup = [c for c in calls if c[0] == "bash"]
    if scenario in {"namespace-exists", "discovery-failed"}:
        assert cleanup == []
        assert not any(c[0] == "python3" for c in calls)
    else:
        assert len(cleanup) == 1
        assert cleanup[0][1] == "scripts/cleanup_smoke_namespace.sh"
        assert "--context" in cleanup[0]
        snapshot_at = next(i for i, c in enumerate(calls) if "scripts/check_snapshot_smoke.py" in c)
        assert calls.index(cleanup[0]) > snapshot_at
