# Backup Restore And DR

Use this runbook for backup targets, RBD/CephFS snapshots, object versioning, and disaster recovery planning for ODF. ODF ships default `VolumeSnapshotClass` objects; prefer them over hand-written snapshot classes.

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

### CSI snapshot policy

Use `volumeSnapshot` by default for ordinary RBD and CephFS snapshots. With ceph-csi-operator, discover the effective per-Driver `spec.snapshotPolicy` and the served CRD's `snapshotPolicy.enum`; do not assume that an empty value enables snapshots. During authorized setup, select `volumeSnapshot` when snapshots are disabled or group support is unverified. Preserve an existing, verified group-snapshot configuration rather than changing it during validation. A group API being served alone does not prove that the installed snapshotter can use it.

Do not set `snapshotPolicy` on an NFS driver. Do not set `OperatorConfig.spec.driverSpecDefaults.snapshotPolicy`, because an empty Driver inherits that value, including NFS. Preserve ODF ownership of the Driver and its VolumeSnapshotClasses; use the installed ODF version's supported configuration and reconciliation path. Do not overwrite generated resources. Confirm the RBD/CephFS controller rollout and the ordinary snapshot/restore smoke test. For the `volumeSnapshot` policy, the snapshotter must not have `--feature-gates=CSIVolumeGroupSnapshot=true`.

The following commands show the ordinary-snapshot policy for discovered RBD and CephFS Drivers. Substitute the actual context, namespace, and Driver names. Apply only through a configuration path supported by the owning operator:

```bash
oc --context "<target-context>" -n openshift-storage patch driver.csi.ceph.io openshift-storage.rbd.csi.ceph.com --type=merge -p '{"spec":{"snapshotPolicy":"volumeSnapshot"}}'
oc --context "<target-context>" -n openshift-storage patch driver.csi.ceph.io openshift-storage.cephfs.csi.ceph.com --type=merge -p '{"spec":{"snapshotPolicy":"volumeSnapshot"}}'
```

### Optional group snapshots

Use `spec.snapshotPolicy: volumeGroupSnapshot` only when group snapshots are needed and the target cluster has verified compatible group APIs, CSI sidecars, and a successful group snapshot and restore. Confirm that `volumeGroupSnapshot` is in the served Driver enum and that the group-snapshot resource versions served by the API match those used by the installed snapshotter. Verify both group recovery and ordinary VolumeSnapshot readiness before adopting this policy for workloads. Until that evidence exists, set `snapshotPolicy: volumeSnapshot` instead and report group support as Not checked or unsupported with its reason.

Check the installed snapshotter's group API client, not just its major version. For example, [upstream snapshotter v8.2.0](https://github.com/kubernetes-csi/external-snapshotter/blob/v8.2.0/cmd/csi-snapshotter/main.go#L255) uses `groupsnapshot/v1beta1`. If the installed client expects a version not served by the cluster, its group informer cannot sync, and enabling the group gate can leave ordinary snapshots unready. This includes a client requesting `v1` against a cluster serving only `v1beta2`; verify the actual requests and served versions before choosing group mode. API presence, a deployed snapshotter, or a class alone is insufficient. Do not enable feature gates. Storage setup does not change `FeatureGate` `featureSet`, including `CustomNoUpgrade` and `TechPreviewNoUpgrade`. Leave absent group APIs unserved. For a verified `volumeGroupSnapshot` configuration, confirm `--feature-gates=CSIVolumeGroupSnapshot=true` after rollout.

Only after those group prerequisites pass, create or reuse a matching `VolumeGroupSnapshotClass` for each supported RBD and CephFS backend. Keep the ordinary VolumeSnapshotClass. Discover the served CRD version; the examples below use `groupsnapshot.storage.k8s.io/v1beta2`, whose `driver`, `parameters`, and `deletionPolicy` are top-level fields. Do not apply that version unless it matches the installed API and snapshotter. Use discovered backend values and the provisioner Secret used by the VolumeSnapshotClass. Omit these optional objects when group snapshots are not needed or not verified.

```yaml
apiVersion: groupsnapshot.storage.k8s.io/v1beta2
kind: VolumeGroupSnapshotClass
metadata:
  name: openshift-storage-rbd-groupsnapclass
driver: openshift-storage.rbd.csi.ceph.com
parameters:
  clusterID: openshift-storage
  pool: ocs-storagecluster-cephblockpool
  csi.storage.k8s.io/group-snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/group-snapshotter-secret-namespace: openshift-storage
deletionPolicy: Delete
---
apiVersion: groupsnapshot.storage.k8s.io/v1beta2
kind: VolumeGroupSnapshotClass
metadata:
  name: openshift-storage-cephfs-groupsnapclass
driver: openshift-storage.cephfs.csi.ceph.com
parameters:
  clusterID: openshift-storage
  fsName: ocs-storagecluster-cephfilesystem
  csi.storage.k8s.io/group-snapshotter-secret-name: rook-csi-cephfs-provisioner
  csi.storage.k8s.io/group-snapshotter-secret-namespace: openshift-storage
deletionPolicy: Delete
```

Match `StorageClass.provisioner` to `VolumeSnapshotClass.driver` using the **same driver**, then check backend identity such as `clusterID`, pool, and snapshotter-secret references where required. A class for another backend using the same driver does not establish coverage. Verify referenced Secrets exist without printing their contents. Preserve operator ownership and existing `deletionPolicy`; use `Delete` for disposable test snapshots and choose `Delete` or `Retain` deliberately for persistent protection. Do not delete/recreate a class in use just to change immutable fields; use a new reviewed class when a custom policy is needed.

Configure selection with explicit `volumeSnapshotClassName`, or set `snapshot.storage.kubernetes.io/is-default-class: "true"` on the intended class with **at most one** default per CSI driver. Snapshot defaults are independent of StorageClass defaults. When several backends share a driver, use explicit selection instead of choosing an arbitrary global default. With CDI/KubeVirt, verify `StorageProfile.spec.snapshotClass` or an unambiguous supported default for VM disks.

### Snapshot and restore verification

Mount the **new filesystem restore PVC** writable so OpenShift can apply SELinux labels to cloned files; a read-only clone mount can leave CephFS/NFS data `unlabeled_t` and fail reads despite Ready pods and correct UID/fsGroup. The test reader command must still only read, and its root filesystem remains read-only. Keep raw-block restore devices read-only. Do not disable SELinux, expand SCC privileges, or change source-volume security to make the test pass.

The executable smoke flows in [validation-hardening.md](validation-hardening.md#smoke-test) run `python3 scripts/check_snapshot_smoke.py` against generated, labeled smoke sources. Use those flows for the token/snapshot/source-change/restore/data-comparison test, including temporary retained-policy handling and cleanup. Do not substitute a provisioning-only pass.

During authorized setup/remediation, use a unique disposable namespace and a test PVC/consumer for each supported backend/mode. Write and sync a known token, quiesce the test writer, create a VolumeSnapshot with an explicit class, and wait for `.status.readyToUse=true` with no error. Inspect the bound `VolumeSnapshotContent` driver, source association, and restore size. Restore to a **new PVC** with `dataSource.kind: VolumeSnapshot` and `dataSource.apiGroup: snapshot.storage.k8s.io`, using the same driver/backend, compatible volume mode, and a size at least the restore size. Start a second consumer and compare the restored token. A Bound PVC or ready snapshot alone does not prove data recovery. For `WaitForFirstConsumer`, provide the restored PVC's consumer before waiting for binding; preserve local-node constraints.

For a test using a retained production class, create a temporary class with equivalent backend/credential parameters and `deletionPolicy: Delete` instead of changing the production class. Clean up only test-created consumers, snapshots, bound contents, PVCs, namespace, and temporary class; verify their backend snapshot/content removal before reporting completion. Never bulk-delete VolumeSnapshotContent or retained recovery points. If test cleanup fails, report the exact remaining test resources and stop further tests. In read-only work, mark restore testing untested and give this next step without running it.

Snapshots on the source backend do not provide off-cluster disaster recovery. Configure recurring protection only after workload selectors, schedule, retention, capacity budget, and application quiescing are defined; report scheduling separately when that policy is missing. Require an independent backup destination and a restore exercise for recovery from backend loss. No PVCs means runtime recovery is untested, not that snapshot configuration can be skipped.

## RBD Snapshots

ODF provides operator-managed snapshot classes for supported RBD/CephFS services. Discover actual names, drivers, backend parameters, and owner references instead of assuming the standard names below. Reuse them and do not overwrite or delete ODF-owned classes. If a supported class is missing, inspect StorageCluster/CSI/operator conditions and restore operator reconciliation through OLM/StorageCluster-supported configuration. Stop setup with a snapshot-readiness gap if reconciliation cannot create it; do not mask it with an upstream Rook class.

Source: [ODF 4.20 volume snapshots](https://docs.redhat.com/en/documentation/red_hat_openshift_data_foundation/4.20/html-single/managing_and_allocating_storage_resources/managing_and_allocating_storage_resources). Use the target ODF release's guide for available services and limits.

ODF installs `ocs-storagecluster-rbdplugin-snapclass`. Verify and use it:

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

## CephFS Snapshots

ODF installs `ocs-storagecluster-cephfsplugin-snapclass` for shared filesystem PVCs:

```bash
oc get volumesnapshotclass ocs-storagecluster-cephfsplugin-snapclass
```

Use the same `VolumeSnapshot` pattern with `volumeSnapshotClassName: ocs-storagecluster-cephfsplugin-snapclass`.

## Object Versioning

Enable versioning on RGW or MCG buckets via the S3 API or bucket policy. ODF does not manage bucket policies from the `StorageCluster`; use the S3 API against the RGW/MCG endpoint or the Ceph CLI via the toolbox.

## Configuration Snapshot (ODF CRs, Not a Data Backup)

Capture ODF-owned CRs before major changes. This is a configuration snapshot for comparison and recovery planning, not a recoverable backup: it excludes application data, bucket contents, and credentials.

```bash
oc -n openshift-storage get storagecluster -o yaml > /tmp/storagecluster-backup.yaml
oc -n openshift-storage get cephcluster -o yaml > /tmp/cephcluster-backup.yaml
oc -n openshift-storage get cephblockpool -o yaml > /tmp/cephblockpool-backup.yaml
oc -n openshift-storage get cephfilesystem -o yaml > /tmp/cephfilesystem-backup.yaml
oc -n openshift-storage get cephobjectstore -o yaml > /tmp/cephobjectstore-backup.yaml
oc -n openshift-storage get noobaa,backingstore,bucketclass -o yaml > /tmp/mcg-backup.yaml
```

Include the Local Storage Operator objects and the ODF Subscription:

```bash
oc -n openshift-local-storage get localvolumeset,localvolumediscovery -o yaml > /tmp/lso-backup.yaml
oc -n openshift-storage get subscription,operatorgroup -o yaml > /tmp/odf-olm-backup.yaml
```

Move the exports from `/tmp` to a durable, encrypted backup destination. Back up application PVC data with supported snapshots or backup tooling, and include regular backups of the NooBaa database PVC when MCG is in use.

## Regional-DR And Metro-DR

For cross-cluster protection, ODF uses OpenShift DR (Regional-DR with async RBD mirroring, or Metro-DR with a stretched cluster) driven by the ODF Multicluster Orchestrator and Ramen, coordinated through Red Hat Advanced Cluster Management (RHACM). Plan DR at the ODF level (DRPolicy, DRPlacementControl, mirroring peering) rather than by configuring Ceph rbd-mirror by hand. Confirm the current ODF DR documentation and interoperability matrix before designing a DR topology.

## Ceph Cluster Recovery

If the Ceph cluster is lost but the OSD data disks and monitor data remain intact, follow the version-specific ODF disaster recovery guide. Do not recreate a `StorageCluster` from these YAML exports alone; the documented recovery flow must restore monitor quorum and map each OSD back to its original device/PV. It requires:

- **Preserving OSD data on disk** — the BlueStore data on each local disk must be intact and the `localblock` PVs must still map to those disks.
- **Preserving monitor data** — the `monDataDirHostPath` directories (default `/var/lib/rook/mon-*/`) on the node must be intact. If monitor data is gone, OSD re-import alone is insufficient and a more involved recovery procedure is needed.
- Reinstalling the ODF operator through OLM only as instructed by the version-specific recovery guide.
- Restoring monitor quorum and the original OSD-to-`localblock` PV mappings before bringing the recovered storage system online.

## DR Output

A DR answer should include recovery point objective, recovery time objective, backup target health, restore order, validation commands, and explicit data-loss assumptions.
