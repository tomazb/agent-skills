from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from render_smoke_manifest import render_smoke_manifest
from render_storagecluster import render_storagecluster


def test_smoke_manifest_rbd_renders(tmp_path):
    output = tmp_path / "test-odf-rbd-smoke.yaml"
    render_smoke_manifest("rbd", "odf-rbd-smoke", "ocs-storagecluster-ceph-rbd", str(output))
    text = output.read_text(encoding="utf-8")
    assert "rbd-smoke-pvc" in text
    assert "ocs-storagecluster-ceph-rbd" in text
    assert "rbd-smoke-writer" in text
    assert "echo odf-smoke-ok > /data/smoke-probe && sync && sleep 3600" in text


def test_smoke_manifest_cephfs_renders(tmp_path):
    output = tmp_path / "test-odf-cephfs-smoke.yaml"
    render_smoke_manifest("cephfs", "odf-cephfs-smoke", "ocs-storagecluster-cephfs", str(output))
    text = output.read_text(encoding="utf-8")
    assert "cephfs-smoke-pvc" in text
    assert "ocs-storagecluster-cephfs" in text
    assert "cephfs-smoke-writer" in text
    assert "ReadWriteMany" in text
    assert "echo odf-smoke-ok > /data/smoke-probe && sync && sleep 3600" in text


def test_smoke_manifest_invalid_mode_raises(tmp_path):
    with pytest.raises(ValueError):
        render_smoke_manifest("invalid", "ns", "sc", str(tmp_path / "out.yaml"))


def test_storagecluster_multinode_renders(tmp_path):
    output = tmp_path / "test-storagecluster.yaml"
    render_storagecluster("ocs-storagecluster", "openshift-storage", "localblock", 3, 1, str(output))
    text = output.read_text(encoding="utf-8")
    assert "kind: StorageCluster" in text
    assert "replica: 3" in text
    assert "count: 1" in text
    assert "storageClassName: localblock" in text


def test_storagecluster_sno_renders(tmp_path):
    output = tmp_path / "test-storagecluster-sno.yaml"
    render_storagecluster("ocs-storagecluster", "openshift-storage", "localblock", 1, 1, str(output))
    text = output.read_text(encoding="utf-8")
    assert "replica: 1" in text


def test_storagecluster_invalid_replica_raises(tmp_path):
    with pytest.raises(ValueError):
        render_storagecluster("n", "openshift-storage", "localblock", 0, 1, str(tmp_path / "out.yaml"))


def test_storagecluster_unsupported_replica_raises(tmp_path):
    with pytest.raises(ValueError, match="1 or 3"):
        render_storagecluster("n", "openshift-storage", "localblock", 2, 1, str(tmp_path / "out.yaml"))


def test_storagecluster_invalid_count_raises(tmp_path):
    with pytest.raises(ValueError):
        render_storagecluster("n", "openshift-storage", "localblock", 3, 0, str(tmp_path / "out.yaml"))
