# Maintenance And Uninstall

Use this runbook for node maintenance, disk maintenance, MachineConfig cleanup, SCC cleanup, and uninstall.

## Node Maintenance

For SNO, treat node maintenance as an outage. Confirm backups and post-reboot checks; draining cannot preserve availability when there is only one node.

For multi-node:

```bash
oc adm cordon <node>
oc adm drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=<duration>
```

Then perform maintenance, wait for Longhorn replica rebuilds if needed, and uncordon:

```bash
oc adm uncordon <node>
oc -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io -o wide
```

## Disk Maintenance Or Removal

Before removing a disk:

- disable scheduling on the disk;
- evict all replicas;
- verify no replicas remain on that disk;
- verify volume health and backups;
- remove the disk from the Longhorn node CR only after it is empty.

Before any `wipefs` or `mkfs`, require explicit destructive confirmation and gather `readlink -f`, `lsblk -f`, `findmnt`, and `wipefs -n` for the exact `/dev/disk/by-id/*` path.

## SCC Cleanup

Remove temporary privileged SCC grants after preflight or repair work:

```bash
oc adm policy remove-scc-from-user privileged \
  -z longhorn-preflight-checker \
  -n longhorn-system
```

List service accounts and SCC use if cleanup is uncertain:

```bash
oc get rolebindings,clusterrolebindings -A | grep -i longhorn || true
oc adm policy who-can use scc privileged
```

## MachineConfig Cleanup

MachineConfig cleanup can reboot nodes. On SNO, warn about temporary API loss. Prefer editing or removing the MachineConfig that originally created a mount or file instead of masking a systemd unit from a later MachineConfig.

Find Longhorn-specific MachineConfigs before deciding what to remove:

```bash
oc get machineconfig | grep -i longhorn || true
oc get machineconfig <name> -o yaml
```

Common examples:

- `80-longhorn-prereqs-*`: usually enables `iscsid.service` and may also define
  a `/var/mnt/longhorn` mount for V1 filesystem disks.
- `81-longhorn-v2-spdk-*`: usually configures V2/SPDK modules and hugepage
  kernel arguments.

Remove obsolete MachineConfigs only after confirming the target mode. For
example, remove V2/SPDK MachineConfigs before a clean V1-only validation, and
remove V1 mount MachineConfigs before a V2-only raw block validation.

After changes:

```bash
oc wait mcp/<pool> --for=condition=Updated=True --timeout=45m
oc get mcp <pool> -o wide
oc get nodes
```

If MCP is degraded, stop and inspect before proceeding.

## Uninstall

Only uninstall when the user explicitly wants Longhorn removed and accepts that workloads must be migrated, backed up, or deleted first.

Preconditions:

- No required PV/PVC depends on `driver.longhorn.io`.
- Workloads using Longhorn volumes are migrated, backed up, or deleted.
- A final system backup exists if any Longhorn state may be needed.
- The user has explicitly confirmed uninstall intent.

Before uninstalling, hand off StorageClass defaulting:

```bash
oc annotate storageclass <replacement-sc> \
  storageclass.kubernetes.io/is-default-class=true --overwrite
oc annotate storageclass longhorn \
  storageclass.kubernetes.io/is-default-class=false --overwrite 2>/dev/null || true
oc get sc
```

Delete or migrate smoke-test namespaces and PVCs, then verify Longhorn data CRs
are gone:

```bash
oc delete namespace <smoke-namespace> --wait=true --timeout=10m
oc get pv,pvc -A -o wide
oc -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io -o wide
```

Set the documented confirmation flag:

```bash
oc -n longhorn-system patch settings.longhorn.io deleting-confirmation-flag \
  --type=merge -p '{"value":"true"}'
```

Uninstall with the same install method that was used.

For Helm installs, uninstall the release after the confirmation flag is set:

```bash
helm uninstall longhorn -n longhorn-system
```

For manifest installs on OpenShift/OKD, run the uninstall job matching the installed Longhorn version, then delete the OKD deploy manifest (the same `longhorn-okd.yaml` applied at install, so OpenShift-specific oauth-proxy/SCC resources are removed) and the uninstall job:

```bash
LONGHORN_VERSION="v<installed-version>"
oc create -f "https://raw.githubusercontent.com/longhorn/longhorn/${LONGHORN_VERSION}/uninstall/uninstall.yaml"
oc -n longhorn-system get job/longhorn-uninstall -w
oc delete -f "https://raw.githubusercontent.com/longhorn/longhorn/${LONGHORN_VERSION}/deploy/longhorn-okd.yaml"
oc delete -f "https://raw.githubusercontent.com/longhorn/longhorn/${LONGHORN_VERSION}/uninstall/uninstall.yaml"
```

`oc delete -f .../longhorn-okd.yaml` can return `NotFound` for DaemonSets or
Deployments that the uninstall job already removed. Treat this as acceptable
only if the final audit is clean.

Remove leftover Longhorn StorageClasses after confirming no PV/PVC uses them:

```bash
oc get pv,pvc -A -o wide
oc delete storageclass longhorn longhorn-static --ignore-not-found=true
```

Post-uninstall audit:

```bash
bash scripts/post_uninstall_audit.sh
```

Equivalent manual checks:

```bash
oc get namespace longhorn-system 2>/dev/null || true
oc api-resources --api-group=longhorn.io
oc get validatingwebhookconfiguration longhorn-webhook-validator 2>/dev/null || true
oc get mutatingwebhookconfiguration longhorn-webhook-mutator 2>/dev/null || true
oc get csidriver driver.longhorn.io 2>/dev/null || true
oc get clusterrole,clusterrolebinding | grep -i longhorn || true
oc get priorityclass longhorn-critical 2>/dev/null || true
oc get sc
oc get pv,pvc -A -o wide
```

Host cleanup is separate from Longhorn uninstall. Remove MachineConfigs and wipe disks only after separate explicit destructive confirmation for each host cleanup action.
