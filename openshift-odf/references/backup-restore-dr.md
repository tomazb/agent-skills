# Backup Restore And DR

Use this runbook for backup targets, RBD/CephFS snapshots, object versioning, and disaster recovery planning for ODF. ODF ships default `VolumeSnapshotClass` objects; prefer them over hand-written snapshot classes.

## RBD Snapshots

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
