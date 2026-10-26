"""Snapshot setup must respect ODF ownership and verify recovery."""

from pathlib import Path
import json
import re
import shlex


ROOT = Path(__file__).resolve().parents[1]


def test_rbd_and_cephfs_default_to_ordinary_snapshots_with_optional_groups():
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    patches = [shlex.split(line) for block in re.findall(r"```bash\n(.*?)```", text, re.S)
               for line in block.splitlines() if "patch driver.csi.ceph.io" in line]
    assert len(patches) == 2
    for command in patches:
        assert json.loads(command[command.index("-p") + 1])["spec"]["snapshotPolicy"] == "volumeSnapshot"
    assert "Use `volumeSnapshot` by default" in text
    assert "group snapshot and restore" in text
    assert 'snapshotPolicy: volumeGroupSnapshot' in text
    assert "openshift-storage.rbd.csi.ceph.com" in text
    assert "openshift-storage.cephfs.csi.ceph.com" in text
    assert "--feature-gates=CSIVolumeGroupSnapshot=true" in text
    assert "Do not set `snapshotPolicy` on an NFS driver" in text
    assert "set `snapshotPolicy: volumeSnapshot` instead" in text
    assert "TechPreviewNoUpgrade" in text
    assert "Do not enable feature gates." in text
    assert "kind: VolumeGroupSnapshotClass" in text
    assert "groupsnapshot.storage.k8s.io/v1beta2" in text
    assert "openshift-storage.rbd.csi.ceph.com" in text
    assert "openshift-storage.cephfs.csi.ceph.com" in text


def test_odf_recovers_managed_snapshot_classes_through_the_operator():
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    assert "operator-managed" in text
    assert "reconciliation" in text
    assert "do not overwrite" in text.lower()
    assert "readyToUse" in text
    assert "dataSource" in text

def test_standalone_smoke_cleanup_pins_target_context():
    """Standalone filesystem and object cleanup must not use the current context."""
    guide = (ROOT / "references/validation-hardening.md").read_text(encoding="utf-8")
    assert 'cleanup_smoke_namespace.sh --namespace odf-smoke --context "<target-context>"' in guide
    assert 'cleanup_smoke_namespace.sh --namespace odf-object-smoke --object --context "<target-context>"' in guide
