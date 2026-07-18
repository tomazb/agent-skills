# CephFS Shared Filesystem StorageClasses

Use this runbook for consuming and managing cephfs shared filesystem storage in ODF. ODF creates the default `CephFilesystem` and the `ocs-storagecluster-cephfs` StorageClass from the `StorageCluster`; do not create Rook `CephFilesystem` CRs by hand on an ODF cluster.

## Default CephFS StorageClass

After the `StorageCluster` is Ready, ODF provides a shared-filesystem StorageClass backed by the `ocs-storagecluster-cephfilesystem` CephFS:

```bash
oc get sc ocs-storagecluster-cephfs -o yaml
```

Use it for `ReadWriteMany` workloads that need shared POSIX access. The MDS runs as `activeCount: 1` with `activeStandby: true` on multi-node clusters for MDS high availability.

Keep exactly one default StorageClass unless the user explicitly requests another policy.

## Filesystem replica policy (managed via StorageCluster)

The CephFS metadata and data pools inherit the `StorageCluster` resiliency policy:

- **Multi-Node Production**: metadata and data pools use `replicated.size: 3` with `requireSafeReplicaSize: true`. Do not lower these for multi-node production without explicit direction.
- **SNO**: metadata and data pools use `replicated.size: 1` with `requireSafeReplicaSize: false`, and the MDS runs `activeStandby: false`. Do not copy `size: 1` or `requireSafeReplicaSize: false` into multi-node production plans without explicit direction.

Change filesystem behavior through the `StorageCluster` `managedResources.cephFilesystems` settings, not by editing the Rook `CephFilesystem` directly:

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  managedResources:
    cephFilesystems:
      reconcileStrategy: manage
```

## Custom Application StorageClass

For a non-default reclaim policy on shared storage, reference the ODF CephFS provisioner and cluster secrets:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: app-cephfs-retain
provisioner: openshift-storage.cephfs.csi.ceph.com
parameters:
  clusterID: openshift-storage
  fsName: ocs-storagecluster-cephfilesystem
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-cephfs-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: openshift-storage
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-cephfs-node
  csi.storage.k8s.io/node-stage-secret-namespace: openshift-storage
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

Keep exactly one default StorageClass unless the user explicitly requests another policy.

## Validation

Create a test PVC and pod. Confirm:

- PVC is `Bound`.
- Pod can write and read data.
- CephFS mount is active and healthy.
- MDS is in `active` state (and a standby exists on multi-node).
- `oc get sc` shows exactly one default StorageClass when defaulting is expected.

Minimum smoke flow (pod name `cephfs-smoke-writer` matches `scripts/render_smoke_manifest.py`):

```bash
oc apply -f /tmp/odf-cephfs-smoke.yaml
oc -n odf-cephfs-smoke wait pod/cephfs-smoke-writer --for=condition=Ready --timeout=5m
oc -n odf-cephfs-smoke exec cephfs-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
```

## Snapshot Support

ODF installs a cephfs `VolumeSnapshotClass` (`ocs-storagecluster-cephfsplugin-snapclass`). Verify and use it:

```bash
oc get volumesnapshotclass ocs-storagecluster-cephfsplugin-snapclass
```

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-cephfs-snapshot
  namespace: <app-namespace>
spec:
  volumeSnapshotClassName: ocs-storagecluster-cephfsplugin-snapclass
  source:
    persistentVolumeClaimName: my-cephfs-pvc
```
