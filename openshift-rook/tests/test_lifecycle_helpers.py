from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
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


@pytest.mark.parametrize("mode", ["rbd", "cephfs"])
@pytest.mark.parametrize("node", [
    "worker-a", "worker-a.example.test", "worker-" + "a" * 57,
    "a" * 253, "a" * 126 + "." + "b" * 126,
])
def test_smoke_manifest_pins_node_with_scheduler_affinity(tmp_path, mode, node):
    """Both storage modes must retain scheduler participation with explicit pinning."""
    pinned = tmp_path / "pinned.yaml"
    unpinned = tmp_path / "unpinned.yaml"
    render_smoke_manifest(mode, "rook-rbd-smoke", "rook-ceph-block", str(pinned), node_name=node)
    render_smoke_manifest(mode, "rook-rbd-smoke", "rook-ceph-block", str(unpinned))
    pinned_text = pinned.read_text(encoding="utf-8")
    unpinned_text = unpinned.read_text(encoding="utf-8")
    assert "spec:\n  affinity:\n    nodeAffinity:\n" in pinned_text
    assert "requiredDuringSchedulingIgnoredDuringExecution:" in pinned_text
    assert "- matchFields:\n          - key: metadata.name\n            operator: In\n            values:\n            - " + node in pinned_text
    assert "nodeName:" not in pinned_text
    assert "affinity:" not in unpinned_text
    assert "nodeName:" not in unpinned_text


@pytest.mark.parametrize("node", [
    "node: bad", "worker-a\nmetadata: injected", "-worker", "worker-", "worker..a",
    "Worker", "a" * 254, "a" * 253 + ".", "worker_1",
])
def test_smoke_manifest_rejects_unsafe_node_name(tmp_path, node):
    """Reject node names that are invalid or could inject YAML into a Pod."""
    with pytest.raises(ValueError):
        render_smoke_manifest(
            "rbd", "rook-rbd-smoke", "rook-ceph-block", str(tmp_path / "bad.yaml"), node_name=node
        )
    assert not (tmp_path / "bad.yaml").exists()


def test_smoke_manifest_invalid_mode_raises(tmp_path):
    with pytest.raises(ValueError):
        render_smoke_manifest("invalid", "ns", "sc", str(tmp_path / "out.yaml"))
