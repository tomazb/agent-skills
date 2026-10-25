"""Ensure local CSI snapshots do not silently request external backups."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_local_snapshot_class_explicitly_uses_snap_type():
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    docs = [doc for block in re.findall(r"```yaml\n(.*?)```", text, re.S)
            for doc in yaml.safe_load_all(block) if isinstance(doc, dict)]
    classes = [d for d in docs if d.get("kind") == "VolumeSnapshotClass"]
    assert classes
    assert all(d["driver"] == "driver.longhorn.io" for d in classes)
    assert any(d.get("parameters", {}).get("type") == "snap" for d in classes)
    assert all(d["deletionPolicy"] in {"Delete", "Retain"} for d in classes)
    assert "data engine" in text and "bak" in text


def test_longhorn_restore_example_matches_snapshot_size_and_class():
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    docs = [doc for block in re.findall(r"```yaml\n(.*?)```", text, re.S)
            for doc in yaml.safe_load_all(block) if isinstance(doc, dict)]
    snapshots = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "VolumeSnapshot"}
    restores = [d for d in docs if d.get("kind") == "PersistentVolumeClaim"]
    assert len(restores) == 1
    restore = restores[0]
    source = restore["spec"]["dataSource"]
    assert source["kind"] == "VolumeSnapshot"
    assert source["apiGroup"] == "snapshot.storage.k8s.io"
    assert snapshots[source["name"]]["spec"]["volumeSnapshotClassName"] == "longhorn-local-snapshots"
    assert restore["spec"]["resources"]["requests"]["storage"] == "1Gi"
    assert "size must match" in text
