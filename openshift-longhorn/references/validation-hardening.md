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

## Smoke Test

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

Minimum smoke flow:

```bash
python3 scripts/render_smoke_manifest.py \
  --mode <v1-or-v2> \
  --namespace <smoke-namespace> \
  --storage-class longhorn \
  --output /tmp/longhorn-smoke.yaml

oc apply -f /tmp/longhorn-smoke.yaml
oc -n <smoke-namespace> wait pod/<writer-pod> --for=condition=Ready --timeout=5m
oc -n <smoke-namespace> exec <writer-pod> -- sh -c 'echo ok > /data/probe && cat /data/probe'
oc -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io -o wide
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
- `v2-data-engine=true`;
- `data-engine-hugepage-enabled` and `data-engine-memory-size`;
- V2 StorageClass uses `dataEngine: "v2"` and expected `diskSelector`.

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
