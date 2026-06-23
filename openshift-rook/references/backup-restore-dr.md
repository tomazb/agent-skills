# Backup Restore And DR

Use this runbook for backup targets, RBD snapshots, CephFS snapshots, RGW object versioning, and disaster recovery planning for Rook Ceph.

## RBD Snapshots

Rook supports Kubernetes VolumeSnapshot for RBD.

Create a `VolumeSnapshotClass`:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: rook-ceph-block-snapclass
driver: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  csi.storage.k8s.io/snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/snapshotter-secret-namespace: rook-ceph
deletionPolicy: Delete
```

Create a snapshot:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-pvc-snapshot
  namespace: <app-namespace>
spec:
  volumeSnapshotClassName: rook-ceph-block-snapclass
  source:
    persistentVolumeClaimName: my-pvc
```

## CephFS Snapshots

Create a `VolumeSnapshotClass` for CephFS:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: rook-cephfs-snapclass
driver: rook-ceph.cephfs.csi.ceph.com
parameters:
  clusterID: rook-ceph
  csi.storage.k8s.io/snapshotter-secret-name: rook-csi-cephfs-provisioner
  csi.storage.k8s.io/snapshotter-secret-namespace: rook-ceph
deletionPolicy: Delete
```

## RGW Object Versioning

Enable versioning on RGW buckets via the Ceph CLI or bucket policy. Rook does not manage RGW bucket policies directly; use the S3 API or Ceph CLI via the toolbox.

## Cluster Backup (Rook CRs)

Back up the Rook Ceph CRs before major changes:

```bash
oc -n rook-ceph get cephcluster -o yaml > /tmp/cephcluster-backup.yaml
oc -n rook-ceph get cephblockpool -o yaml > /tmp/cephblockpool-backup.yaml
oc -n rook-ceph get cephfilesystem -o yaml > /tmp/cephfilesystem-backup.yaml
oc -n rook-ceph get cephobjectstore -o yaml > /tmp/cephobjectstore-backup.yaml
```

## Ceph Cluster Recovery

If the Ceph cluster is lost but the OSD data disks remain intact, follow the Rook Ceph disaster recovery guide to re-import the cluster. This requires:

- **Preserving OSD data on disk** — the BlueStore data written by Ceph must be intact.
- **Preserving monitor data** — the `dataDirHostPath/mon-*/` directories (default `/var/lib/rook/mon-*/`) on the node must be intact. If monitor data is gone, OSD re-import alone is insufficient and a more involved recovery procedure is needed.
- Reinstalling the Rook operator.
- Re-creating the CephCluster CR with the exact same `dataDirHostPath` and storage node/disk mapping.
- The operator will detect existing OSDs and re-import them.

## DR Output

A DR answer should include recovery point objective, recovery time objective, backup target health, restore order, validation commands, and explicit data-loss assumptions.
