# Validation Hardening And Troubleshooting

Use this runbook after install, upgrade, reboot, maintenance, or incident response.

## Core Validation

```bash
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc -n openshift-storage get pods -o wide
oc -n openshift-storage get lvmcluster -o wide
oc -n openshift-storage get logicalvolumes.topolvm.io -o wide
oc get csidriver
```

Confirm exactly one default StorageClass when defaulting is expected.

## Snapshot readiness

Run the read-only [snapshot readiness inventory](backup-restore-dr.md#snapshot-readiness) during every validation, including clusters with no PVCs. Report supported but unconfigured thin-backed drivers as **Warning**, alongside LVMS health; resolve missing managed classes through operator reconciliation. Record Supported, Configured, Scheduled, and Restore-tested for each StorageClass. Configure missing supported classes during authorized setup/remediation; validation alone does not authorize mutations or production-volume tests.

## Node-Level LVM Validation

```bash
NODE="<node>"
oc debug "node/${NODE}" -- chroot /host bash -c "
  pvs
  vgs
  lvs
  lvs -o lv_name,vg_name,pool_lv,origin,size,data_percent,metadata_percent
"
```

Check that:
- VGs exist with expected names.
- Thin pools are within capacity (`data_percent` < 80, `metadata_percent` < 80).
- Physical volumes are the expected disks.

## Smoke Test

For every backend/mode with verified snapshot support, the minimum smoke test also runs `python3 scripts/check_snapshot_smoke.py`. It writes and syncs a token, snapshots the source, changes the source token, restores a new PVC, and compares the restored data with the original token. A ready snapshot or Bound restore PVC is not sufficient. Missing supported snapshot configuration fails this stage; resolve it using [Snapshot readiness](backup-restore-dr.md#snapshot-readiness) before rerunning. Mark verified unsupported combinations **N/A** with the version/mode reason, and unavailable or unverified recovery **untested**; never silently report a complete smoke pass after skipping supported snapshot tests.

Use generated manifests or labeled assets with `app.kubernetes.io/part-of: storage-smoke` on the Namespace, PVC, and writer Pod. The helper refuses unlabeled or non-smoke sources, and requires a Delete-reclaim StorageClass so test PV cleanup can complete. Pass the same explicit target context to source creation, the round-trip helper, and namespace cleanup. Replace the snapshot-class placeholder with the discovered compatible class. Retained snapshot classes are preserved; the helper uses a temporary Delete class for its own snapshots. It checks restored PVC/PV and VolumeSnapshotContent cleanup before success, then the EXIT trap removes and audits the source namespace even if the test fails. Record cleanup failures as failures, retaining the resource names for follow-up. Use a unique namespace per run and replace the example name consistently; the preflight refuses an existing namespace.

Create a namespace, PVC, and writer pod using the intended StorageClass. Validate:

- PVC is `Bound`.
- Pod reaches `Ready`.
- Write/read succeeds.
- TopoLVM volume is healthy (`LogicalVolume` CR status).
- `volumeBindingMode: WaitForFirstConsumer` is respected (pod scheduled before PV bound).
- `oc get sc` shows exactly one default StorageClass.

Use unique smoke namespaces per mode, for example `lvms-fs-smoke` and `lvms-block-smoke`, so cleanup and audit commands are unambiguous.

Minimum smoke flow for filesystem:

```bash
(
set -euo pipefail
target_context="<target-context>"
smoke_existing=$(oc --context="$target_context" get namespace lvms-fs-smoke --ignore-not-found -o name)
if [ -n "$smoke_existing" ]; then
  echo "refusing to reuse existing namespace lvms-fs-smoke" >&2
  exit 1
fi
python3 scripts/render_smoke_manifest.py \
  --mode fs \
  --namespace lvms-fs-smoke \
  --storage-class lvms-vg1 \
  --output /tmp/lvms-fs-smoke.yaml

cleanup_smoke() {
  smoke_status=$?
  trap - EXIT
  if ! bash scripts/cleanup_smoke_namespace.sh --namespace lvms-fs-smoke --context "$target_context"; then
    exit 1
  fi
  exit "$smoke_status"
}
trap cleanup_smoke EXIT


oc --context="$target_context" apply -f /tmp/lvms-fs-smoke.yaml
oc --context="$target_context" -n lvms-fs-smoke wait pod/lvms-smoke-writer --for=condition=Ready --timeout=5m
oc --context="$target_context" -n openshift-storage get logicalvolumes.topolvm.io -o wide
python3 scripts/check_snapshot_smoke.py \
  --context "$target_context" \
  --namespace lvms-fs-smoke \
  --source-pvc lvms-smoke-pvc --writer-pod lvms-smoke-writer \
  --snapshot-class "<lvms-snapshot-class>"
)
```

Minimum smoke flow for block:

```bash
(
set -euo pipefail
target_context="<target-context>"
smoke_existing=$(oc --context="$target_context" get namespace lvms-block-smoke --ignore-not-found -o name)
if [ -n "$smoke_existing" ]; then
  echo "refusing to reuse existing namespace lvms-block-smoke" >&2
  exit 1
fi
python3 scripts/render_smoke_manifest.py \
  --mode block \
  --namespace lvms-block-smoke \
  --storage-class lvms-vg1-block \
  --output /tmp/lvms-block-smoke.yaml

cleanup_smoke() {
  smoke_status=$?
  trap - EXIT
  if ! bash scripts/cleanup_smoke_namespace.sh --namespace lvms-block-smoke --context "$target_context"; then
    exit 1
  fi
  exit "$smoke_status"
}
trap cleanup_smoke EXIT


oc --context="$target_context" apply -f /tmp/lvms-block-smoke.yaml
oc --context="$target_context" -n lvms-block-smoke wait pod/lvms-smoke-writer --for=condition=Ready --timeout=5m
oc --context="$target_context" -n openshift-storage get logicalvolumes.topolvm.io -o wide
python3 scripts/check_snapshot_smoke.py \
  --context "$target_context" \
  --namespace lvms-block-smoke \
  --source-pvc lvms-smoke-pvc --writer-pod lvms-smoke-writer \
  --snapshot-class "<lvms-snapshot-class>"
)
```

If the helper is unavailable, adapt `assets/smoke-pvc-writer.yaml` and replace every placeholder before applying it.

On OpenShift, make smoke pods compatible with restricted PodSecurity by setting `allowPrivilegeEscalation: false`, dropping all capabilities, setting `runAsNonRoot: true` when the image supports it, and setting `seccompProfile.type: RuntimeDefault`.

## Post-Reboot Drift

After a node reboot, check:

- `LVMCluster` is `Ready`.
- TopoLVM CSI node pods are running on all nodes.
- VGs and thin pools exist (`vgs`, `lvs`).
- Thin pool capacity is within bounds.
- `LogicalVolume` CRs are `Healthy`.
- One default StorageClass remains.
- MachineConfigs have been applied and MCP is `Updated`.
- `topolvm.io/capacity` extended resource is reported on each node.

## Post-Uninstall Validation

After uninstall, confirm:

- `openshift-storage` namespace is absent (or empty if reused).
- `oc api-resources --api-group=topolvm.io` and `oc api-resources --api-group=lvm.topolvm.io` return no resources.
- `csidriver/topolvm.io` is absent.
- No StorageClass uses `provisioner: topolvm.io`.
- No PV/PVC uses a TopoLVM StorageClass.
- TopoLVM SCCs are absent.
- Exactly one intended default StorageClass remains.

## Hardening

- Configure application-level backup (Velero/OADP) for workloads using LVMS volumes.
- Integrate TopoLVM metrics with OpenShift monitoring.
- Alert on:
  - Thin pool capacity pressure (`data_percent`, `metadata_percent`).
  - Node failures affecting LVMS volumes.
  - `LogicalVolume` CRs not in `Healthy` state.
  - CSI driver pod failures or restarts.
  - VG capacity exhaustion (`topolvm.io/capacity` near zero).
- For multi-node production, spread workloads across nodes to avoid single-node bottleneck.
- For SNO, document that all storage is local and not redundant.
- Avoid thin pool over-provisioning ratios that exceed realistic usage patterns.

## Troubleshooting Shape

For incidents, answer with:

- Symptom and impact.
- Current health evidence (`LVMCluster`, `LogicalVolume`, `lvs`, `vgs`, pods).
- Likely layer: Kubernetes scheduling, TopoLVM CSI, LVM, node hardware, network, or OpenShift host/MachineConfig.
- Commands already run.
- Next read-only checks.
- Safest remediation and stop conditions.

Collect support data when needed:

```bash
oc -n openshift-storage get events --sort-by=.lastTimestamp
# Workload names vary by LVMS version. Discover them first, then tail logs by the observed names:
oc -n openshift-storage get deployment,daemonset -o wide
oc -n openshift-storage logs deployment/<controller-deployment> --tail=200
oc -n openshift-storage logs daemonset/<node-daemonset> --tail=200
oc -n openshift-storage get logicalvolumes.topolvm.io -o yaml
oc get node <node> -o yaml | grep -A 20 "topolvm.io/capacity"
```
