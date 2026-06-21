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

## V1 Post-Reboot Drift

Check:

- `iscsid.service` active;
- `/var/mnt/longhorn` mounted from `/dev/disk/by-label/longhorn`;
- dedicated disk schedulable and root disk unschedulable when intended;
- `default-replica-count`, `create-default-disk-labeled-nodes`, and `default-data-path`;
- one default StorageClass.

## V2 Post-Reboot Drift

Check:

- `iscsid.service` active;
- `HugePages_Total` and `hugepages-2Mi` node capacity;
- `vfio_pci`, `vfio_iommu_type1`, `uio_pci_generic`, and `nvme_tcp` loaded where expected;
- raw block disk unmounted with no signatures from `wipefs -n`;
- Longhorn V2 block disk `Ready=True` and `Schedulable=True`;
- `v2-data-engine=true`;
- `data-engine-hugepage-enabled` and `data-engine-memory-size`;
- V2 StorageClass uses `dataEngine: "v2"` and expected `diskSelector`.

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
