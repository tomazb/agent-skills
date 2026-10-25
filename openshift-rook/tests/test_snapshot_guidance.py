"""Validate the runnable Rook snapshot/restore examples."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_each_rook_snapshot_driver_has_a_matching_restore_example():
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    docs = [doc for block in re.findall(r"```yaml\n(.*?)```", text, re.S)
            for doc in yaml.safe_load_all(block) if isinstance(doc, dict)]
    classes = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "VolumeSnapshotClass"}
    snapshots = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "VolumeSnapshot"}
    restores = [d for d in docs if d.get("kind") == "PersistentVolumeClaim" and "dataSource" in d.get("spec", {})]
    assert {d["driver"] for d in classes.values()} == {
        "rook-ceph.rbd.csi.ceph.com", "rook-ceph.cephfs.csi.ceph.com",
    }
    assert len(restores) == 2
    for restore in restores:
        source = restore["spec"]["dataSource"]
        assert source["kind"] == "VolumeSnapshot"
        assert source["apiGroup"] == "snapshot.storage.k8s.io"
        snapshot = snapshots[source["name"]]
        cls = classes[snapshot["spec"]["volumeSnapshotClassName"]]
        assert cls["deletionPolicy"] in {"Delete", "Retain"}
        assert cls["parameters"]["clusterID"] == "rook-ceph"
        assert cls["parameters"]["csi.storage.k8s.io/snapshotter-secret-namespace"] == "rook-ceph"
        assert restore["metadata"]["namespace"] == snapshot["metadata"]["namespace"]
        assert restore["spec"]["storageClassName"] == (
            "rook-ceph-block" if ".rbd." in cls["driver"] else "rook-cephfs"
        )

def test_manual_cephfs_snapshot_cleanup_uses_the_target_context():
    """Namespace cleanup must be scoped to the intended cluster."""
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    instruction = next(line for line in text.splitlines()
                       if "Wait for snapshot readiness before applying" in line)
    assert "--namespace <test-smoke-namespace> --context <target-context>" in instruction

def test_standalone_rook_smoke_cleanup_pins_target_context():
    """The legacy smoke-manifest fallback targets the intended cluster."""
    guide = (ROOT / "references/validation-hardening.md").read_text(encoding="utf-8")
    assert 'cleanup_smoke_namespace.sh --namespace rook-smoke --context "<target-context>"' in guide
