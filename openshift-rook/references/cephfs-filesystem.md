# CephFS Filesystem Pools And StorageClasses

Use this runbook for creating and managing CephFS shared filesystem pools and StorageClasses on Rook Ceph.

## CephFS Creation

Create a `CephFilesystem` with metadata and data pools. Plan replica counts and failure domains at creation time.

### Multi-Node Production

```yaml
apiVersion: ceph.rook.io/v1
kind: CephFilesystem
metadata:
  name: rook-cephfs
  namespace: rook-ceph
spec:
  metadataPool:
    replicated:
      size: 3
      requireSafeReplicaSize: true
    parameters:
      compression_mode: none
  dataPools:
  - name: data0
    replicated:
      size: 3
      requireSafeReplicaSize: true
    parameters:
      compression_mode: none
  preserveFilesystemOnDelete: true
  metadataServer:
    activeCount: 1
    activeStandby: true
```

### SNO

```yaml
apiVersion: ceph.rook.io/v1
kind: CephFilesystem
metadata:
  name: rook-cephfs
  namespace: rook-ceph
spec:
  metadataPool:
    replicated:
      size: 1
      requireSafeReplicaSize: false
    parameters:
      compression_mode: none
  dataPools:
  - name: data0
    replicated:
      size: 1
      requireSafeReplicaSize: false
    parameters:
      compression_mode: none
  preserveFilesystemOnDelete: true
  metadataServer:
    activeCount: 1
    activeStandby: false
```

Do not copy `size: 1` or `requireSafeReplicaSize: false` into multi-node production plans without explicit direction.

## StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: rook-cephfs
provisioner: rook-ceph.cephfs.csi.ceph.com
parameters:
  clusterID: rook-ceph
  fsName: rook-cephfs
  pool: rook-cephfs-data0
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-cephfs-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: rook-ceph
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-cephfs-node
  csi.storage.k8s.io/node-stage-secret-namespace: rook-ceph
reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

Keep exactly one default StorageClass unless the user explicitly requests another policy.

## Validation

Create a test PVC and pod. Confirm:

- PVC is `Bound`.
- Pod can write and read data.
- CephFS mount is active and healthy.
- MDS is in `active` state.
- `oc get sc` shows exactly one default StorageClass when defaulting is expected.

## Snapshot Support

Enable CephFS snapshot support by creating a `VolumeSnapshotClass`:

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
