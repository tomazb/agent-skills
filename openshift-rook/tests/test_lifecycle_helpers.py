from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

# Loaded by path under a name of its own: openshift-odf ships a render_smoke_manifest
# module too.
_spec = importlib.util.spec_from_file_location(
    "openshift_rook_render_smoke_manifest", SCRIPTS_DIR / "render_smoke_manifest.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
render_smoke_manifest = _module.render_smoke_manifest


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
