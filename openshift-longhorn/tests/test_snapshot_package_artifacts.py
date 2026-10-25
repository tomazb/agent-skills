"""Snapshot smoke workflows must ship both runtime and cleanup helpers."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("relative", [
    "scripts/check_snapshot_smoke.py",
    "scripts/cleanup_smoke_namespace.sh",
])
def test_missing_snapshot_smoke_runtime_artifact_fails_package_check(validator, tmp_path, relative):
    for name in validator.REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    target = tmp_path / relative
    if target.exists():
        target.unlink()
    issues = validator.check_required_files(tmp_path)
    assert any(relative in issue for issue in issues)
