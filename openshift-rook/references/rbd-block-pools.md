# RBD Block Pools And StorageClasses

Use this runbook for creating and managing RBD (RADOS Block Device) pools and StorageClasses on Rook Ceph.

## Pool Creation

Create a `CephBlockPool` with appropriate replica count and failure domain rules.

### Multi-Node Production

```yaml
apiVersion: ceph.rook.io/v1
kind: CephBlockPool
metadata:
  name: replicapool
  namespace: rook-ceph
spec:
  failureDomain: host
  replicated:
    size: 3
    requireSafeReplicaSize: true
  parameters:
    compression_mode: none
```

### SNO

```yaml
apiVersion: ceph.rook.io/v1
kind: CephBlockPool
metadata:
  name: replicapool
  namespace: rook-ceph
spec:
  failureDomain: host
  replicated:
    size: 1
    requireSafeReplicaSize: false
  parameters:
    compression_mode: none
```

Do not copy `size: 1` or `requireSafeReplicaSize: false` into multi-node production plans without explicit direction.

## PG/PGP Planning

Modern Ceph manages placement groups automatically. The PG autoscaler
(`pg_autoscale_mode`) is enabled by default for new pools (since Ceph Octopus),
and Rook creates pools with it on. In most clusters, leave it on and do not set
`pg_num`/`pgp_num` manually.

`pg_num` is **not immutable** — the autoscaler splits and merges PGs as the pool
grows, and manual changes are also allowed. Any change triggers rebalancing, so
make manual changes deliberately during a maintenance window.

### Let the autoscaler do the work (recommended)

Give the autoscaler a hint about the pool's expected share of cluster capacity
with `target_size_ratio` instead of hard-coding PG counts:

```yaml
# CephBlockPool spec fragment:
spec:
  parameters:
    target_size_ratio: "0.5"
```

Check what the autoscaler is doing:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd pool autoscale-status
```

### Manual PG counts (advanced override)

Only set `pg_num`/`pgp_num` manually when you have a specific reason. Manual
values conflict with the autoscaler, so turn it off for that pool first, then
size with the Ceph PG calculator (rough target is ~100 PGs per OSD summed across
all pools, divided by replica size, rounded to a power of two):

```yaml
# CephBlockPool spec fragment:
spec:
  parameters:
    pg_autoscale_mode: "off"
    pg_num: "256"
    pgp_num: "256"
```

If the Rook Ceph version does not support these pool parameters in the CR, set them via the Ceph CLI after pool creation:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd pool set replicapool pg_autoscale_mode off
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd pool set replicapool pg_num 256
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd pool set replicapool pgp_num 256
```

## StorageClass

Create a StorageClass that references the RBD pool and the Ceph cluster secret.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: rook-ceph-block
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  pool: replicapool
  imageFormat: "2"
  imageFeatures: layering
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: rook-ceph
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-rbd-node
  csi.storage.k8s.io/node-stage-secret-namespace: rook-ceph
  csi.storage.k8s.io/fstype: ext4
reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

Keep exactly one default StorageClass unless the user explicitly requests another policy.

## Validation

Create a test PVC and pod. Confirm:

- PVC is `Bound`.
- Pod can write and read data.
- RBD image is created in the pool.
- RBD image has the correct replica count and failure domain.
- `oc get sc` shows exactly one default StorageClass when defaulting is expected.

Minimum smoke flow:

```bash
oc apply -f /tmp/rook-rbd-smoke.yaml
oc -n rook-rbd-smoke wait pod/rbd-smoke-writer --for=condition=Ready --timeout=5m
oc -n rook-rbd-smoke exec rbd-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
```

## Snapshot Support

Enable RBD snapshot support by creating a `VolumeSnapshotClass`:

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
