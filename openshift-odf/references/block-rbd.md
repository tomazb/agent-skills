# Block (ceph-rbd) StorageClasses And Pools

Use this runbook for consuming and managing ceph-rbd (RADOS Block Device) storage in ODF. ODF creates the default block pool and the `ocs-storagecluster-ceph-rbd` StorageClass from the `StorageCluster`; do not create Rook `CephBlockPool` CRs by hand on an ODF cluster.

## Default Block StorageClass

After the `StorageCluster` is Ready, ODF provides a ready-to-use block StorageClass:

```bash
oc get sc ocs-storagecluster-ceph-rbd -o yaml
```

It provisions RBD volumes from the default `ocs-storagecluster-cephblockpool` with `replicated.size: 3` on multi-node (or `size: 1` on a single-replica SNO cluster). Use it for `ReadWriteOnce` block workloads and databases.

Keep exactly one default StorageClass unless the user explicitly requests another policy. `ocs-storagecluster-ceph-rbd` is not the cluster default unless you annotate it.

## Additional Block Pools (managed via StorageCluster)

To add a differently-configured RBD pool, declare it under the `StorageCluster` so `ocs-operator` owns it. Do not apply a standalone `CephBlockPool`:

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  managedResources:
    cephBlockPools:
      reconcileStrategy: manage
```

For an entirely separate pool with its own failure domain or replica policy, use the documented ODF additional-pool workflow (a `CephBlockPool` created through the ODF console/StorageClass wizard, which ODF then reconciles) rather than a hand-written Rook CR.

### Multi-Node Production replica policy

Production pools use `replicated.size: 3` with `requireSafeReplicaSize: true` and `failureDomain: host` (or a wider domain such as `zone`). Do not lower these for multi-node production without explicit direction.

### SNO

On a single-node cluster the block pool is `replicated.size: 1` with `requireSafeReplicaSize: false`. Do not copy `size: 1` or `requireSafeReplicaSize: false` into multi-node production plans without explicit direction.

## PG/PGP Planning

Modern Ceph manages placement groups automatically. The PG autoscaler
(`pg_autoscale_mode`) is enabled by default for ODF pools, and ODF creates pools
with it on. In most clusters, leave it on and do not set `pg_num`/`pgp_num`
manually.

`pg_num` is **not immutable** — the autoscaler splits and merges PGs as the pool
grows, and manual changes are also allowed. Any change triggers rebalancing, so
make manual changes deliberately during a maintenance window.

Check what the autoscaler is doing through the toolbox:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd pool autoscale-status
```

Only override the autoscaler with a specific reason; on ODF, prefer supported `StorageCluster` tuning over ad-hoc `ceph osd pool set` changes, because `ocs-operator` may reconcile pool settings back to managed values.

## Custom Application StorageClass

If you need a non-default reclaim or binding policy, create an application StorageClass that references the ODF RBD provisioner and the ODF cluster secrets:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: app-ceph-rbd-retain
provisioner: openshift-storage.rbd.csi.ceph.com
parameters:
  clusterID: openshift-storage
  pool: ocs-storagecluster-cephblockpool
  imageFormat: "2"
  imageFeatures: layering
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: openshift-storage
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-rbd-node
  csi.storage.k8s.io/node-stage-secret-namespace: openshift-storage
  csi.storage.k8s.io/fstype: ext4
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

Keep exactly one default StorageClass unless the user explicitly requests another policy.

## Validation

Create a test PVC and pod. Confirm:

- PVC is `Bound`.
- Pod can write and read data.
- RBD image is created in `ocs-storagecluster-cephblockpool`.
- RBD image has the correct replica count and failure domain.
- `oc get sc` shows exactly one default StorageClass when defaulting is expected.

Minimum smoke flow (pod name `rbd-smoke-writer` matches `scripts/render_smoke_manifest.py`):

```bash
oc apply -f /tmp/odf-rbd-smoke.yaml
oc -n odf-rbd-smoke wait pod/rbd-smoke-writer --for=condition=Ready --timeout=5m
oc -n odf-rbd-smoke exec rbd-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
```

## Snapshot Support

ODF installs a ceph-rbd `VolumeSnapshotClass` (`ocs-storagecluster-rbdplugin-snapclass`). Verify and use it:

```bash
oc get volumesnapshotclass ocs-storagecluster-rbdplugin-snapclass
```

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-pvc-snapshot
  namespace: <app-namespace>
spec:
  volumeSnapshotClassName: ocs-storagecluster-rbdplugin-snapclass
  source:
    persistentVolumeClaimName: my-pvc
```
