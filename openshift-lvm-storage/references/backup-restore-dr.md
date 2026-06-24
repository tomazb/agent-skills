# Backup, Restore, And DR

Use this runbook for backup, restore, and disaster recovery planning for LVMS on OpenShift/OKD.

## LVMS Storage Characteristics

LVMS uses local LVM thin pools on each node. This means:

- Volumes are **not replicated** across nodes.
- A node failure makes all volumes on that node inaccessible until the node returns.
- There is no native cross-node redundancy or automatic failover.
- Backup and DR must be handled at the application level or via volume snapshots.

## Backup Strategies

### Application-Level Backup (Recommended)

Use Velero, OpenShift API for Data Protection (OADP), or application-native backup tools. This captures application state independently of the underlying storage:

```bash
# Example: OADP backup of a namespace with LVMS volumes
oc create -f - <<EOF
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: my-app-backup
  namespace: openshift-adp
spec:
  includedNamespaces:
    - my-app
  storageLocation: default
  snapshotVolumes: false  # Use restic/kopia for file-level backup
  defaultVolumesToFsBackup: true
EOF
```

With `snapshotVolumes: false` and `defaultVolumesToFsBackup: true`, Velero/OADP uses file-level backup (restic or kopia) to back up the pod filesystem contents. This works for LVMS filesystem volumes but not for raw block volumes.

### Volume Snapshots (for filesystem volumes)

TopoLVM supports CSI snapshots for thin pool-backed volumes. Snapshots are local to the node and VG.

Create a `VolumeSnapshotClass`:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: lvms-snapshot-class
driver: topolvm.io
deletionPolicy: Delete
```

`deletionPolicy` is a required field (`Delete` or `Retain`). Omitting it makes the API server reject the manifest.

Create a snapshot:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-app-snapshot
  namespace: my-app
spec:
  volumeSnapshotClassName: lvms-snapshot-class
  source:
    persistentVolumeClaimName: my-pvc
```

Verify:

```bash
oc -n my-app get volumesnapshot my-app-snapshot -o wide
oc -n my-app get volumesnapshotcontent
```

**Limitations**:
- Snapshots are local to the node's VG and thin pool.
- A node failure destroys the snapshot.
- Snapshots consume thin pool capacity. Monitor `data_percent` and `metadata_percent`.
- Snapshots are not suitable for off-node DR.

### Block Volume Backup

Raw block volumes cannot be backed up with file-level backup tools. Options include:

1. Application-level backup (e.g., database dump, VM snapshot at the hypervisor level).
2. `dd` the block device to a backup target from within the pod (requires manual coordination).
3. Use a DR solution that replicates the application data, not the raw block device.

## Restore Considerations

### Restoring to the Same Node

If the node is still available, restore from application backup or volume snapshot:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc-restored
  namespace: my-app
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: lvms-vg1
  dataSource:
    name: my-app-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  resources:
    requests:
      storage: 10Gi
```

### Restoring to a Different Node

Because LVMS volumes are local to the node, restoring a PVC from a snapshot on a different node requires the snapshot to be on a shared storage backend (which LVMS does not provide). For local storage, the typical approach is:

1. Restore from application-level backup to a new pod on a different node.
2. The new pod will provision a new empty LVMS volume on the new node.
3. The application backup restores the data into the new volume.

## Node Affinity Constraints

TopoLVM volumes are bound to the node where they are provisioned. The PV has a `nodeAffinity` constraint that prevents the pod from being scheduled elsewhere:

```bash
oc get pv <pv-name> -o yaml | grep -A 10 nodeAffinity
```

This means:
- A pod using an LVMS volume cannot be rescheduled to a different node without the volume being recreated.
- Node maintenance requires the pod to remain on the same node (or be deleted and recreated with a new volume).
- For DR, plan for application-level recovery rather than volume migration.

## DR Planning

For a node failure scenario with LVMS:

1. **Detection**: Monitor node health, thin pool capacity, and `LogicalVolume` CR status.
2. **Impact assessment**: Identify which pods and PVCs are on the failed node.
3. **Recovery options**:
   - If the node is recoverable: wait for node recovery, pods will resume.
   - If the node is lost: delete the pod and PVC, recreate from application backup on a different node.
4. **RPO/RTO**: Define based on application backup frequency, not storage replication.
5. **Test DR**: Regularly test restore from application backup to a new node.

## Safety Rules

- Do not rely on LVMS for cross-node redundancy. It is local storage.
- Volume snapshots are local to the node. Do not treat them as off-node DR.
- Monitor thin pool capacity. Snapshots and over-provisioning can exhaust the pool.
- Plan for application-level backup and restore, not storage-level replication.
- Document node affinity constraints for pods using LVMS volumes.
