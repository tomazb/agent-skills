from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest
import yaml

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


def test_storagecluster_sno_emits_flexible_scaling_and_placements(tmp_path):
    """A replica=1 manifest without these is the manifest the runbook forbids.

    references/validated-odf-sno.md: apply the SNO placements from the start
    rather than reactively, because ODF sets topologyKey:"" with
    whenUnsatisfiable:DoNotSchedule and nothing schedules. Reproduced live on
    ODF 4.22.3 (htz2, 2026-09-16) for the MDS/RGW placements ODF emits itself.
    """
    output = tmp_path / "sno.yaml"
    render_storagecluster("ocs-storagecluster", "openshift-storage", "localblock", 1, 1, str(output))
    spec = yaml.safe_load(output.read_text(encoding="utf-8"))["spec"]

    assert spec["flexibleScaling"] is True
    mon = spec["placement"]["mon"]["topologySpreadConstraints"][0]
    assert mon["topologyKey"] == "kubernetes.io/hostname"
    assert mon["whenUnsatisfiable"] == "ScheduleAnyway"

    device_set = spec["storageDeviceSets"][0]
    for key, app in (
        ("placement", "rook-ceph-osd"),
        ("preparePlacement", "rook-ceph-osd-prepare"),
    ):
        constraint = device_set[key]["topologySpreadConstraints"][0]
        assert constraint["topologyKey"] == "kubernetes.io/hostname"
        assert constraint["whenUnsatisfiable"] == "ScheduleAnyway"
        assert constraint["labelSelector"]["matchLabels"]["app"] == app


def test_storagecluster_multinode_omits_sno_only_fields(tmp_path):
    """flexibleScaling and the SNO placements must not leak into replica=3."""
    output = tmp_path / "multi.yaml"
    render_storagecluster("ocs-storagecluster", "openshift-storage", "localblock", 3, 1, str(output))
    spec = yaml.safe_load(output.read_text(encoding="utf-8"))["spec"]

    assert "flexibleScaling" not in spec
    assert "placement" not in spec
    assert "placement" not in spec["storageDeviceSets"][0]
    assert "preparePlacement" not in spec["storageDeviceSets"][0]


def test_storagecluster_invalid_replica_raises(tmp_path):
    with pytest.raises(ValueError):
        render_storagecluster("n", "openshift-storage", "localblock", 0, 1, str(tmp_path / "out.yaml"))


def test_storagecluster_unsupported_replica_raises(tmp_path):
    with pytest.raises(ValueError, match="1 or 3"):
        render_storagecluster("n", "openshift-storage", "localblock", 2, 1, str(tmp_path / "out.yaml"))


def test_storagecluster_invalid_count_raises(tmp_path):
    with pytest.raises(ValueError):
        render_storagecluster("n", "openshift-storage", "localblock", 3, 0, str(tmp_path / "out.yaml"))
