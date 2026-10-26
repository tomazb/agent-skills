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
(
set -euo pipefail
target_context="<target-context>"
smoke_existing=$(oc --context="$target_context" get namespace odf-cephfs-smoke --ignore-not-found -o name)
if [ -n "$smoke_existing" ]; then
  echo "refusing to reuse existing namespace odf-cephfs-smoke" >&2
  exit 1
fi
python3 scripts/render_smoke_manifest.py \
  --mode cephfs \
  --namespace odf-cephfs-smoke \
  --storage-class ocs-storagecluster-cephfs \
  --output /tmp/odf-cephfs-smoke.yaml

cleanup_smoke() {
  smoke_status=$?
  trap - EXIT
  if ! bash scripts/cleanup_smoke_namespace.sh --namespace odf-cephfs-smoke --context "$target_context"; then
    exit 1
  fi
  exit "$smoke_status"
}
trap cleanup_smoke EXIT


oc --context="$target_context" apply -f /tmp/odf-cephfs-smoke.yaml
oc --context="$target_context" -n odf-cephfs-smoke wait pod/cephfs-smoke-writer --for=condition=Ready --timeout=5m
python3 scripts/check_snapshot_smoke.py \
  --context "$target_context" \
  --namespace odf-cephfs-smoke \
  --source-pvc cephfs-smoke-pvc --writer-pod cephfs-smoke-writer \
  --snapshot-class "<cephfs-snapshot-class>"
)
```

The cleanup command is the end of the smoke. It deletes `odf-cephfs-smoke` and fails if the namespace, a PV that claims it, or a VolumeSnapshotContent that references it remains. See `references/validation-hardening.md`.

## Snapshot Support

ODF installs a cephfs `VolumeSnapshotClass` (`ocs-storagecluster-cephfsplugin-snapclass`). Verify and use it. Set this driver's `snapshotPolicy` to `volumeSnapshot` for ordinary snapshots; use `volumeGroupSnapshot` only after the optional group-snapshot prerequisites and recovery checks pass as described in [Snapshot readiness](backup-restore-dr.md#snapshot-readiness):

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
