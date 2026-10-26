# Backup, Restore, And DR

Use this runbook for backup, restore, and disaster recovery planning for LVMS on OpenShift/OKD.

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

Match `StorageClass.provisioner` to `VolumeSnapshotClass.driver` using the **same driver**, then check backend identity such as `clusterID`, pool, and snapshotter-secret references where required. A class for another backend using the same driver does not establish coverage. Verify referenced Secrets exist without printing their contents. Preserve operator ownership and existing `deletionPolicy`; use `Delete` for disposable test snapshots and choose `Delete` or `Retain` deliberately for persistent protection. Do not delete/recreate a class in use just to change immutable fields; use a new reviewed class when a custom policy is needed.

Configure selection with explicit `volumeSnapshotClassName`, or set `snapshot.storage.kubernetes.io/is-default-class: "true"` on the intended class with **at most one** default per CSI driver. Snapshot defaults are independent of StorageClass defaults. When several backends share a driver, use explicit selection instead of choosing an arbitrary global default. With CDI/KubeVirt, verify `StorageProfile.spec.snapshotClass` or an unambiguous supported default for VM disks.

### Snapshot and restore verification

Mount the **new filesystem restore PVC** writable so OpenShift can apply SELinux labels to cloned files; a read-only clone mount can leave CephFS/NFS data `unlabeled_t` and fail reads despite Ready pods and correct UID/fsGroup. The test reader command must still only read, and its root filesystem remains read-only. Keep raw-block restore devices read-only. Do not disable SELinux, expand SCC privileges, or change source-volume security to make the test pass.

The executable smoke flows in [validation-hardening.md](validation-hardening.md#smoke-test) run `python3 scripts/check_snapshot_smoke.py` against generated, labeled smoke sources. Use those flows for the token/snapshot/source-change/restore/data-comparison test, including temporary retained-policy handling and cleanup. Do not substitute a provisioning-only pass.

During authorized setup/remediation, use a unique disposable namespace and a test PVC/consumer for each supported backend/mode. Write and sync a known token, quiesce the test writer, create a VolumeSnapshot with an explicit class, and wait for `.status.readyToUse=true` with no error. Inspect the bound `VolumeSnapshotContent` driver, source association, and restore size. Restore to a **new PVC** with `dataSource.kind: VolumeSnapshot` and `dataSource.apiGroup: snapshot.storage.k8s.io`, using the same driver/backend, compatible volume mode, and a size at least the restore size. Start a second consumer and compare the restored token. A Bound PVC or ready snapshot alone does not prove data recovery. For `WaitForFirstConsumer`, provide the restored PVC's consumer before waiting for binding; preserve local-node constraints.

For a test using a retained production class, create a temporary class with equivalent backend/credential parameters and `deletionPolicy: Delete` instead of changing the production class. Clean up only test-created consumers, snapshots, bound contents, PVCs, namespace, and temporary class; verify their backend snapshot/content removal before reporting completion. Never bulk-delete VolumeSnapshotContent or retained recovery points. If test cleanup fails, report the exact remaining test resources and stop further tests. In read-only work, mark restore testing untested and give this next step without running it.

Snapshots on the source backend do not provide off-cluster disaster recovery. Configure recurring protection only after workload selectors, schedule, retention, capacity budget, and application quiescing are defined; report scheduling separately when that policy is missing. Require an independent backup destination and a restore exercise for recovery from backend loss. No PVCs means runtime recovery is untested, not that snapshot configuration can be skipped.

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

### CSI volume snapshots

TopoLVM supports CSI snapshots for thin pool-backed volumes. Snapshots are local to the node and VG.

Current LVMS releases create an operator-managed `VolumeSnapshotClass` named `lvms-<device-class>` alongside each device class's StorageClass, for example `lvms-vg1`. Discover and reuse that class first. If it is missing, inspect `LVMCluster` and operator reconciliation; do not create a duplicate custom class to hide a failed managed resource. Confirm thin-pool configuration and support for the source filesystem or raw-block mode against the installed release.

Only when the installed deployment requires a custom class, create the following after checking that no compatible class exists. Preserve the managed class and its retention/default policy:

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
  volumeSnapshotClassName: lvms-vg1
  source:
    persistentVolumeClaimName: my-pvc
```

The snapshot example selects the discovered managed `lvms-vg1` class; use `lvms-snapshot-class` only when the custom class above was actually needed. Class names and device classes are discovered values, not fixed requirements.

Verify:

```bash
oc -n my-app get volumesnapshot my-app-snapshot -o wide
oc -n my-app get volumesnapshotcontent
```

**Limitations**:
- Snapshots are local to the node's VG and thin pool.
- A node outage makes the snapshot unavailable. Permanent loss of its backing disk/VG also loses its local snapshots.
- Snapshots consume thin pool capacity. Monitor `data_percent` and `metadata_percent`.
- Snapshots are not suitable for off-node DR.

Source: [OpenShift 4.20 LVM Storage](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/pdf/storage/OpenShift_Container_Platform-4.20-Storage-en-US.pdf). Verify the target release's operator behavior and snapshot support.

### Block Volume Backup

Raw block volumes cannot be backed up with file-level backup tools. Options include:

1. Application-level backup (e.g., database dump, VM snapshot at the hypervisor level).
2. `dd` the block device to a backup target from within the pod (requires manual coordination).
3. Use a DR solution that replicates the application data, not the raw block device.

## Restore Considerations

### Restoring to the Same Node

If the node is still available, restore from application backup or volume snapshot:

Wait for `.status.readyToUse=true` before creating the restore PVC. Keep its volume mode compatible with the source, request at least the snapshot restore size, and consume it on the source node. LVMS uses `WaitForFirstConsumer`; create the restored PVC's consumer before waiting for Bound, then compare its data with the token written before the snapshot. See **Snapshot readiness** for cleanup and the distinction between configured snapshots and tested recovery.

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
