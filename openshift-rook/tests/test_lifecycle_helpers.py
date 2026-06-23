from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from render_smoke_manifest import render_smoke_manifest


def test_smoke_manifest_rbd_renders(tmp_path):
    output = tmp_path / "test-rook-rbd-smoke.yaml"
    render_smoke_manifest("rbd", "rook-rbd-smoke", "rook-ceph-block", str(output))
    text = output.read_text(encoding="utf-8")
    assert "rbd-smoke-pvc" in text
    assert "rook-ceph-block" in text
    assert "rbd-smoke-writer" in text


def test_smoke_manifest_cephfs_renders(tmp_path):
    output = tmp_path / "test-rook-cephfs-smoke.yaml"
    render_smoke_manifest("cephfs", "rook-cephfs-smoke", "rook-cephfs", str(output))
    text = output.read_text(encoding="utf-8")
    assert "cephfs-smoke-pvc" in text
    assert "rook-cephfs" in text
    assert "cephfs-smoke-writer" in text
    assert "ReadWriteMany" in text


def test_smoke_manifest_invalid_mode_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        render_smoke_manifest("invalid", "ns", "sc", str(tmp_path / "out.yaml"))
