# Validation Hardening And Troubleshooting

Use this runbook after install, migration, upgrade, reboot, maintenance, or incident response.

## Core Validation

```bash
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc -n longhorn-system get pods -o wide
oc -n longhorn-system get settings.longhorn.io
oc -n longhorn-system get nodes.longhorn.io -o wide
oc -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io -o wide
```

Confirm exactly one default StorageClass when defaulting is expected.

## Snapshot readiness

Run the read-only [snapshot readiness inventory](backup-restore-dr.md#snapshot-readiness) during every validation, including clusters with no PVCs. Report supported but unconfigured drivers as **Warning**, alongside Longhorn volume health. Record Supported, Configured, Scheduled, and Restore-tested for each StorageClass and data engine. Configure missing supported classes during authorized setup/remediation; validation alone does not authorize mutations or production-volume tests.

## Smoke Test

For every backend/mode with verified snapshot support, the minimum smoke test also runs `python3 scripts/check_snapshot_smoke.py`. It writes and syncs a token, snapshots the source, changes the source token, restores a new PVC, and compares the restored data with the original token. A ready snapshot or Bound restore PVC is not sufficient. Missing supported snapshot configuration fails this stage; resolve it using [Snapshot readiness](backup-restore-dr.md#snapshot-readiness) before rerunning. Mark verified unsupported combinations **N/A** with the version/mode reason, and unavailable or unverified recovery **untested**; never silently report a complete smoke pass after skipping supported snapshot tests.

Use generated manifests or labeled assets with `app.kubernetes.io/part-of: storage-smoke` on the Namespace, PVC, and writer Pod. The helper refuses unlabeled or non-smoke sources, and requires a Delete-reclaim StorageClass so test PV cleanup can complete. Pass the same explicit target context to source creation, the round-trip helper, and namespace cleanup. Replace the snapshot-class placeholder with the discovered compatible class. Retained snapshot classes are preserved; the helper uses a temporary Delete class for its own snapshots. It checks restored PVC/PV and VolumeSnapshotContent cleanup before success, then the EXIT trap removes and audits the source namespace even if the test fails. Record cleanup failures as failures, retaining the resource names for follow-up. Use a unique namespace per run and replace the example name consistently; the preflight refuses an existing namespace.

Create a namespace, PVC, and writer pod using the intended StorageClass. Validate:

- PVC is `Bound`;
- pod reaches `Ready`;
- write/read succeeds;
- Longhorn volume is healthy;
- replica count matches SNO or multi-node policy;
- replica placement uses intended disk tags and paths;
- `longhorn-storageclass` ConfigMap matches the live class.

Remove smoke resources unless the user asks to keep them for inspection.

Use unique smoke namespaces per mode, for example `longhorn-v1-smoke` and
`longhorn-v2-smoke`, so cleanup and audit commands are unambiguous.

Minimum smoke flow for V2; repeat with `--mode v1`, its matching StorageClass, and a unique `longhorn-v1-smoke` namespace when V1 is enabled:

```bash
(
set -euo pipefail
target_context="<target-context>"
smoke_existing=$(oc --context="$target_context" get namespace longhorn-v2-smoke --ignore-not-found -o name)
if [ -n "$smoke_existing" ]; then
  echo "refusing to reuse existing namespace longhorn-v2-smoke" >&2
  exit 1
fi
python3 scripts/render_smoke_manifest.py \
  --mode v2 \
  --namespace longhorn-v2-smoke \
  --storage-class longhorn \
  --output /tmp/longhorn-v2-smoke.yaml

cleanup_smoke() {
  smoke_status=$?
  trap - EXIT
  if ! bash scripts/cleanup_smoke_namespace.sh --namespace longhorn-v2-smoke --context "$target_context"; then
    exit 1
  fi
  exit "$smoke_status"
}
trap cleanup_smoke EXIT


oc --context="$target_context" apply -f /tmp/longhorn-v2-smoke.yaml
oc --context="$target_context" -n longhorn-v2-smoke wait pod/writer --for=condition=Ready --timeout=5m
oc --context="$target_context" -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io -o wide
python3 scripts/check_snapshot_smoke.py \
  --context "$target_context" \
  --namespace longhorn-v2-smoke \
  --source-pvc data --writer-pod writer \
  --snapshot-class "<longhorn-local-snapshot-class>"
)
```

If the helper is unavailable, adapt `assets/smoke-pvc-writer.yaml` and replace
every placeholder before applying it.

On OpenShift, make smoke pods compatible with restricted PodSecurity by setting
`allowPrivilegeEscalation: false`, dropping all capabilities, setting
`runAsNonRoot: true` when the image supports it, and setting
`seccompProfile.type: RuntimeDefault`. PodSecurity warnings do not always block
pod creation, but avoid them in reusable examples.

The smoke pod runs as non-root with no explicit `fsGroup`. On OpenShift it still
writes successfully because the `restricted-v2` SCC injects an `fsGroup` and
Longhorn's CSIDriver uses the default `fsGroupPolicy: ReadWriteOnceWithFSType`,
so the RWO ext4 volume is chowned at mount time. Off OpenShift, set `fsGroup`
explicitly so a non-root writer can access the volume.

For V1, confirm the Longhorn volume uses `DATA ENGINE=v1`. For V2, confirm
`DATA ENGINE=v2` on volume, replica, and engine CRs.

## V1 Post-Reboot Drift

Check:

- `iscsid.service` active;
- `/var/mnt/longhorn` mounted from `/dev/disk/by-label/longhorn`;
- dedicated disk schedulable and root disk unschedulable when intended;
- `default-replica-count`, `create-default-disk-labeled-nodes`, and `default-data-path`;
- one default StorageClass.

For a root-backed V1 smoke-only test, verify `/var/lib/longhorn` exists and
report that `/var/mnt/longhorn` was not validated as a mounted dedicated disk.

## V2 Post-Reboot Drift

Check:

- `iscsid.service` active;
- `HugePages_Total` and `hugepages-2Mi` node capacity;
- `vfio_pci`, `uio_pci_generic`, and `nvme_tcp` loaded where expected
  (`vfio_iommu_type1` may also appear as an auto-loaded VFIO dependency);
- raw block disk unmounted with no signatures from `wipefs -n`;
- Longhorn V2 block disk `Ready=True` and `Schedulable=True`;
- `v1-data-engine=false` when the intended end state is V2-only;
- `v2-data-engine=true`;
- `data-engine-hugepage-enabled={"v2":"true"}` and
  `data-engine-memory-size` matches the intended V2 memory size;
- V2 StorageClass uses `dataEngine: "v2"` and expected `diskSelector`;
- no `v1` instance manager remains when the intended end state is V2-only;
- the persistent default-setting source matches the intended engine policy:
  `ConfigMap/longhorn-default-setting` for manifest-managed installs, or Helm
  computed values / rendered chart source for Helm-managed installs.

## Post-Uninstall Validation

After uninstall, confirm:

- `longhorn-system` namespace is absent;
- `oc api-resources --api-group=longhorn.io` returns no Longhorn resources;
- Longhorn validating and mutating webhooks are absent;
- `csidriver/driver.longhorn.io` is absent;
- Longhorn RBAC and `longhorn-critical` priority class are absent;
- no StorageClass uses `driver.longhorn.io`;
- no PV/PVC uses a Longhorn StorageClass;
- exactly one intended default StorageClass remains.

## Hardening

- Configure backup target and recurring backup jobs.
- Create periodic Longhorn system backups.
- Integrate Longhorn metrics with OpenShift monitoring.
- Alert on degraded/faulted volumes, failed backups, capacity pressure, disk health, replica rebuild failures, and instance-manager restarts.
- For multi-node production, prefer at least two replicas and spread across nodes or zones.
- For SNO, document that one replica is a topology constraint, not high availability.
- Avoid root disk replica placement unless intentionally accepted.

## Troubleshooting Shape

For incidents, answer with:

- symptom and impact;
- current health evidence;
- likely Longhorn layer: Kubernetes scheduling, CSI, manager, engine, replica, disk, network, backup, or OpenShift host/MachineConfig;
- commands already run;
- next read-only checks;
- safest remediation and stop conditions.

Collect support data when needed:

```bash
oc -n longhorn-system get events --sort-by=.lastTimestamp
oc -n longhorn-system logs ds/longhorn-manager --tail=200
oc -n longhorn-system get supportbundles.longhorn.io 2>/dev/null || true
```
