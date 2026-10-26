# Backup Restore And DR

Use this runbook for backup targets, RBD snapshots, CephFS snapshots, RGW object versioning, and disaster recovery planning for Rook Ceph.

## Snapshot readiness

Snapshotting is part of storage setup. During installation, configuration, or remediation, configure it for every supported StorageClass unless the user explicitly opts out. During a read-only validation, inventory and report gaps without creating classes, snapshots, or test workloads. An explicit opt-out is recorded as disabled by policy, not configured. Verify support against the installed driver version, backend, data engine, and volume mode; sidecar presence alone is insufficient.

Record these fields for each StorageClass, even when no PVCs exist:

| Field | Evidence required |
|---|---|
| Supported | Installed-version documentation confirms CSI snapshot and restore support for the backend/mode; otherwise unsupported with reason, or unknown. |
| Configured | Snapshot APIs and controllers ready; a compatible VolumeSnapshotClass, credentials, and unambiguous class selection exist. |
| Scheduled | Workload coverage, scheduler, retention, last successful run, and application-consistency policy; a class alone creates no periodic snapshots. |
| Restore-tested | Dated successful snapshot-to-new-PVC restore and data comparison for this driver/mode; otherwise untested. |

### Read-only inventory

```bash
oc get storageclasses -o json
oc get csidrivers
oc api-resources --api-group=snapshot.storage.k8s.io --verbs=list -o name
# Run each following query only when its resource was discovered above.
oc get volumesnapshotclasses -o json
oc get volumesnapshots -A
oc get volumesnapshotcontents
```

A failed discovery or Forbidden query is **Not checked**, never evidence that snapshots are absent or unsupported. Verify the OpenShift snapshot-controller operator and controller workloads are healthy, and the product's CSI snapshotter is ready. Reuse distribution-managed snapshot APIs/controllers; do not install duplicate upstream controllers on OpenShift. For OKD or missing prerequisites, use the installed distribution/version's supported installation path and report a blocker until it is ready.

With the ceph-csi-operator, set `spec.snapshotPolicy: volumeGroupSnapshot` on each RBD and CephFS `Driver` only when a group-snapshot API is served (`volumegroupsnapshotclasses.groupsnapshot.storage.k8s.io`). That deploys `csi-snapshotter` and adds `--feature-gates=CSIVolumeGroupSnapshot=true`. Ordinary VolumeSnapshot stays enabled. When that API is not served, set `snapshotPolicy: volumeSnapshot` instead. The snapshotter waits for the group informers to sync, so the group feature gate without those CRDs stops ordinary VolumeSnapshots from becoming ready. An empty policy defaults to `volumeSnapshot` and leaves the group feature gate off. Read `snapshotPolicy.enum` on the served `drivers.csi.ceph.io` CRD and patch `volumeGroupSnapshot` only when it is listed and the group API is served. Do not set `snapshotPolicy` on an NFS driver. Do not set `OperatorConfig.spec.driverSpecDefaults.snapshotPolicy`; an empty Driver inherits that default, including NFS. A deployed CSIDriver or snapshotter without the selected policy is not sufficient. After the controller plugin rolls out, the `csi-snapshotter` args must contain `--feature-gates=CSIVolumeGroupSnapshot=true` when the policy is `volumeGroupSnapshot`, and must not contain that gate when the policy is `volumeSnapshot`. Keep the VolumeSnapshotClass. Create a VolumeGroupSnapshotClass for each RBD and CephFS driver when a group-snapshot API is served; it does not replace the VolumeSnapshotClass. Use the CRD storage version. On OpenShift 4.22 that version is `groupsnapshot.storage.k8s.io/v1beta2`, and `driver`, `parameters`, and `deletionPolicy` are fields of the object. Point `csi.storage.k8s.io/group-snapshotter-secret-name` at the same provisioner Secret the VolumeSnapshotClass uses. Set `pool` for RBD and `fsName` for CephFS from the StorageClass. `csi-snapshotter` v8 lists `groupsnapshot/v1`. If the cluster serves only `v1beta2`, leave `snapshotPolicy: volumeSnapshot`: the v1 informer never syncs and ordinary VolumeSnapshots stay unready. Do not enable feature gates. Storage setup does not change `FeatureGate` `featureSet`, including `CustomNoUpgrade` and `TechPreviewNoUpgrade`. When the group-snapshot API is not served, leave it unserved and do not create a VolumeGroupSnapshotClass.

```yaml
apiVersion: groupsnapshot.storage.k8s.io/v1beta2
kind: VolumeGroupSnapshotClass
metadata:
  name: rook-ceph-block-groupsnapclass
driver: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  pool: replicapool
  csi.storage.k8s.io/group-snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/group-snapshotter-secret-namespace: rook-ceph
deletionPolicy: Delete
---
apiVersion: groupsnapshot.storage.k8s.io/v1beta2
kind: VolumeGroupSnapshotClass
metadata:
  name: rook-cephfs-groupsnapclass
driver: rook-ceph.cephfs.csi.ceph.com
parameters:
  clusterID: rook-ceph
  fsName: rook-cephfs
  csi.storage.k8s.io/group-snapshotter-secret-name: rook-csi-cephfs-provisioner
  csi.storage.k8s.io/group-snapshotter-secret-namespace: rook-ceph
deletionPolicy: Delete
```

```bash
oc -n rook-ceph patch driver.csi.ceph.io rook-ceph.rbd.csi.ceph.com --type=merge -p '{"spec":{"snapshotPolicy":"volumeGroupSnapshot"}}'
oc -n rook-ceph patch driver.csi.ceph.io rook-ceph.cephfs.csi.ceph.com --type=merge -p '{"spec":{"snapshotPolicy":"volumeGroupSnapshot"}}'
```

Substitute the discovered Driver name when the prefix is not `rook-ceph`.

Match `StorageClass.provisioner` to `VolumeSnapshotClass.driver` using the **same driver**, then check backend identity such as `clusterID`, pool, and snapshotter-secret references where required. A class for another backend using the same driver does not establish coverage. Verify referenced Secrets exist without printing their contents. Preserve operator ownership and existing `deletionPolicy`; use `Delete` for disposable test snapshots and choose `Delete` or `Retain` deliberately for persistent protection. Do not delete/recreate a class in use just to change immutable fields; use a new reviewed class when a custom policy is needed.

Configure selection with explicit `volumeSnapshotClassName`, or set `snapshot.storage.kubernetes.io/is-default-class: "true"` on the intended class with **at most one** default per CSI driver. Snapshot defaults are independent of StorageClass defaults. When several backends share a driver, use explicit selection instead of choosing an arbitrary global default. With CDI/KubeVirt, verify `StorageProfile.spec.snapshotClass` or an unambiguous supported default for VM disks.

### Snapshot and restore verification

Mount the **new filesystem restore PVC** writable so OpenShift can apply SELinux labels to cloned files; a read-only clone mount can leave CephFS/NFS data `unlabeled_t` and fail reads despite Ready pods and correct UID/fsGroup. The test reader command must still only read, and its root filesystem remains read-only. Keep raw-block restore devices read-only. Do not disable SELinux, expand SCC privileges, or change source-volume security to make the test pass.

The executable smoke flows in [validation-hardening.md](validation-hardening.md#smoke-test) run `python3 scripts/check_snapshot_smoke.py` against generated, labeled smoke sources. Use those flows for the token/snapshot/source-change/restore/data-comparison test, including temporary retained-policy handling and cleanup. Do not substitute a provisioning-only pass.

During authorized setup/remediation, use a unique disposable namespace and a test PVC/consumer for each supported backend/mode. Write and sync a known token, quiesce the test writer, create a VolumeSnapshot with an explicit class, and wait for `.status.readyToUse=true` with no error. Inspect the bound `VolumeSnapshotContent` driver, source association, and restore size. Restore to a **new PVC** with `dataSource.kind: VolumeSnapshot` and `dataSource.apiGroup: snapshot.storage.k8s.io`, using the same driver/backend, compatible volume mode, and a size at least the restore size. Start a second consumer and compare the restored token. A Bound PVC or ready snapshot alone does not prove data recovery. For `WaitForFirstConsumer`, provide the restored PVC's consumer before waiting for binding; preserve local-node constraints.

For a test using a retained production class, create a temporary class with equivalent backend/credential parameters and `deletionPolicy: Delete` instead of changing the production class. Clean up only test-created consumers, snapshots, bound contents, PVCs, namespace, and temporary class; verify their backend snapshot/content removal before reporting completion. Never bulk-delete VolumeSnapshotContent or retained recovery points. If test cleanup fails, report the exact remaining test resources and stop further tests. In read-only work, mark restore testing untested and give this next step without running it.

Snapshots on the source backend do not provide off-cluster disaster recovery. Configure recurring protection only after workload selectors, schedule, retention, capacity budget, and application quiescing are defined; report scheduling separately when that policy is missing. Require an independent backup destination and a restore exercise for recovery from backend loss. No PVCs means runtime recovery is untested, not that snapshot configuration can be skipped.

## RBD Snapshots

Rook supports Kubernetes VolumeSnapshot for RBD. Discover the actual Rook CSI driver prefix, namespace/clusterID, and snapshotter Secrets from the installed StorageClass. The examples below use the standard `rook-ceph` names; substitute discovered values. Reuse a matching class when present; otherwise create the missing RBD and CephFS classes as part of setup, even with no claims.

Verify CSI snapshot support and the installed CSI operator's driver configuration. Set `snapshotPolicy: volumeGroupSnapshot` as described in Snapshot readiness. Do not assume NFS CSI or an RGW bucket StorageClass supports Kubernetes VolumeSnapshot because RBD/CephFS do. Report unsupported or unknown service/mode combinations separately.

Sources: [Rook snapshot guide](https://rook.io/docs/rook/latest/Storage-Configuration/Ceph-CSI/ceph-csi-snapshot/) and [Kubernetes snapshot class selection](https://kubernetes.io/docs/concepts/storage/volume-snapshot-classes/). Use the installed-version Rook guide when applying changes.

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
  namespace: rook-rbd-smoke
spec:
  volumeSnapshotClassName: rook-ceph-block-snapclass
  source:
    persistentVolumeClaimName: my-pvc
```

After it is ready, restore into a new PVC in the same namespace:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc-restored
  namespace: rook-rbd-smoke
spec:
  storageClassName: rook-ceph-block
  accessModes: [ReadWriteOnce]
  volumeMode: Filesystem
  resources:
    requests:
      storage: 1Gi
  dataSource:
    name: my-pvc-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

Use a 1Gi filesystem smoke source for this example. Preserve the source mode for block-mode tests, and increase the restore request when its restore size exceeds 1Gi. Verify data through the restored consumer using the procedure above.

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

Create a snapshot and restore PVC for a 1Gi CephFS smoke source:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-cephfs-snapshot
  namespace: rook-cephfs-smoke
spec:
  volumeSnapshotClassName: rook-cephfs-snapclass
  source:
    persistentVolumeClaimName: my-cephfs-pvc
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-cephfs-pvc-restored
  namespace: rook-cephfs-smoke
spec:
  storageClassName: rook-cephfs
  accessModes: [ReadWriteMany]
  volumeMode: Filesystem
  resources:
    requests:
      storage: 1Gi
  dataSource:
    name: my-cephfs-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

Wait for snapshot readiness before applying the restore document. Complete token verification and cleanup from **Snapshot readiness**, then use `bash scripts/cleanup_smoke_namespace.sh --namespace <test-smoke-namespace> --context <target-context>` to finish namespace/PV cleanup. Check that no test VolumeSnapshotContent remains; namespace deletion alone does not prove snapshot cleanup.

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
