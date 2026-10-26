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
  csi.storage.k8s.io/controller-expand-secret-name: rook-csi-cephfs-provisioner
  csi.storage.k8s.io/controller-expand-secret-namespace: rook-ceph
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-cephfs-node
  csi.storage.k8s.io/node-stage-secret-namespace: rook-ceph
reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

`allowVolumeExpansion: true` is honored only when `controller-expand-secret-name` and `controller-expand-secret-namespace` name the provisioner Secret. The external-resizer does not fall back to the provisioner-secret parameters. From this skill directory, `python3 scripts/check_volume_expansion_secrets.py` fails if an expandable RBD or CephFS class omits either parameter, or if that Secret has no `userID` or `userKey`. It prints Secret names, never Secret data. Pass `--context <target-context>` when the current context is not the target cluster. A failed check during read-only validation is reported, not patched.

Keep exactly one default StorageClass unless the user explicitly requests another policy.

CSI template references are **Not checked**, not invalid. The expansion checker exits 2 for them; verify the resolved PV references as described in [validation-hardening.md](validation-hardening.md) before recording a full credential-validation pass.

For VirtualMachine disks on CephFS, configure `StorageProfile` `claimPropertySets` (`Filesystem` mode) — see `references/vm-storage-profiles.md`.

## Validation

Create a test PVC and pod. Confirm:

- PVC is `Bound`.
- Pod can write and read data.
- CephFS mount is active and healthy.
- MDS is in `active` state.
- `oc get sc` shows exactly one default StorageClass when defaulting is expected.
- `python3 scripts/check_volume_expansion_secrets.py` exits 0.

Use the complete CephFS snapshot/restore smoke flow in `references/validation-hardening.md`. It verifies the restored token and then deletes and audits the smoke namespace; a provisioning-only check is not a full smoke pass:

```bash
bash scripts/cleanup_smoke_namespace.sh --namespace rook-cephfs-smoke
```

## Snapshot Support

Configure supported CephFS snapshotting before declaring storage setup complete. Follow [Snapshot readiness](backup-restore-dr.md#snapshot-readiness) for controller/CSI prerequisites, class selection, and restore verification. Set this driver's `snapshotPolicy` to `volumeGroupSnapshot` there. Reuse a matching class; create the class below only when it is missing, substituting discovered driver/backend values:

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
