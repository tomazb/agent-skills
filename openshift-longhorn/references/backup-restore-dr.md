# Backup Restore And DR

Use this runbook for backup targets, recurring jobs, Longhorn system backup, restore, and disaster recovery planning.

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

During authorized setup/remediation, use a unique disposable namespace and a test PVC/consumer for each supported backend/mode. Write and sync a known token, quiesce the test writer, create a VolumeSnapshot with an explicit class, and wait for `.status.readyToUse=true` with no error. Inspect the bound `VolumeSnapshotContent` driver, source association, and restore size. Restore to a **new PVC** with `dataSource.kind: VolumeSnapshot` and `dataSource.apiGroup: snapshot.storage.k8s.io`, using the same driver/backend, compatible volume mode, and a size matching the snapshot restore size. Start a second consumer and compare the restored token. A Bound PVC or ready snapshot alone does not prove data recovery. For `WaitForFirstConsumer`, provide the restored PVC's consumer before waiting for binding; preserve local-node constraints.

For a test using a retained production class, create a temporary class with equivalent backend/credential parameters and `deletionPolicy: Delete` instead of changing the production class. Clean up only test-created consumers, snapshots, bound contents, PVCs, namespace, and temporary class; verify their backend snapshot/content removal before reporting completion. Never bulk-delete VolumeSnapshotContent or retained recovery points. If test cleanup fails, report the exact remaining test resources and stop further tests. In read-only work, mark restore testing untested and give this next step without running it.

Snapshots on the source backend do not provide off-cluster disaster recovery. Configure recurring protection only after workload selectors, schedule, retention, capacity budget, and application quiescing are defined; report scheduling separately when that policy is missing. Require an independent backup destination and a restore exercise for recovery from backend loss. No PVCs means runtime recovery is untested, not that snapshot configuration can be skipped.

## CSI snapshot configuration

Verify the installed Longhorn version and each StorageClass's data engine against its snapshot/restore support matrix. Longhorn native recurring snapshots do not by themselves configure Kubernetes CSI snapshots. Reuse a compatible class or create this local snapshot class during setup:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: longhorn-local-snapshots
driver: driver.longhorn.io
deletionPolicy: Delete
parameters:
  type: snap
```

Set `type: snap` explicitly for local snapshots. A `type: bak` class creates a Longhorn backup and requires a working backup target; do not silently select it as the local-snapshot default. Reuse any existing intended snapshot default and explicit class references. For V2, verify installed-version clone/restore support and clone mode rather than copying V1 assumptions.

Create a test snapshot with `volumeSnapshotClassName: longhorn-local-snapshots`, wait for readiness, then restore to a new PVC with the source StorageClass, data engine, and mode. Follow **Snapshot readiness** for token verification and cleanup. Native RecurringJobs, CSI snapshot classes, and external backup targets must each be reported independently.

For the Longhorn smoke test, the restored PVC size must match the snapshot size. For a 1Gi filesystem source PVC named `source` on the discovered `longhorn` class, create the snapshot below first, wait for `readyToUse=true`, then apply the restore document separately. Preserve the source's data engine and mode; do not combine a restore test with expansion.

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: local-snapshot
  namespace: longhorn-snapshot-smoke
spec:
  volumeSnapshotClassName: longhorn-local-snapshots
  source:
    persistentVolumeClaimName: source
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored
  namespace: longhorn-snapshot-smoke
spec:
  storageClassName: longhorn
  accessModes: [ReadWriteOnce]
  volumeMode: Filesystem
  resources:
    requests:
      storage: 1Gi
  dataSource:
    name: local-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

Source: [Longhorn CSI snapshots and restores](https://longhorn.io/docs/latest/snapshots-and-backups/csi-snapshot-support/csi-volume-snapshot-associated-with-longhorn-snapshot/). Select the installed-version documentation before configuring a data engine.

## Backup Target

For production, require a backup target before risky lifecycle actions. Prefer object storage such as S3-compatible storage when available; NFS can work but adds mount and failover considerations.

Collect:

```bash
oc -n longhorn-system get settings.longhorn.io backup-target backup-target-credential-secret -o yaml
oc -n longhorn-system get backuptargets.longhorn.io,backups.longhorn.io,backupvolumes.longhorn.io 2>/dev/null || true
```

Validate credentials, network reachability, and retention requirements before relying on backups.

## Recurring Jobs

Production volumes should have recurring backups. If a backupstore is not available, recurring snapshots are a weaker fallback and do not protect against cluster or disk loss.

Record:

- target volume selectors;
- snapshot and backup schedules;
- retention counts;
- concurrency;
- whether jobs are inherited from StorageClass parameters or Longhorn recurring job resources.

## System Backup

Create a Longhorn system backup before upgrades, uninstall planning, cluster restore exercises, or broad settings changes. A system backup preserves Longhorn custom resources and stores them in the remote backup target.

Check:

```bash
oc -n longhorn-system get systembackups.longhorn.io,systemrestores.longhorn.io 2>/dev/null || true
```

Do not describe system backup as a replacement for application-consistent backups of data inside volumes.

## Restore Planning

For volume restore:

- confirm the target StorageClass and data engine;
- check replica count and disk selectors;
- validate namespace, PVC name, access mode, and workload cutover;
- test a restored canary before restoring production.

For StatefulSets:

- preserve stable PVC naming expectations;
- scale workloads down when required;
- restore PVCs before scaling up;
- verify application-level consistency after restore.

For system restore:

- use a matching Longhorn version unless the documented restore path says otherwise;
- restore into a prepared cluster with Longhorn prerequisites satisfied;
- validate CRDs, settings, nodes, disks, engines, and StorageClasses before attaching workloads.

## DR Output

A DR answer should include recovery point objective, recovery time objective, backup target health, restore order, validation commands, and explicit data-loss assumptions.
