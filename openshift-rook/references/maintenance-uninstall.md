# Maintenance And Uninstall

Use this runbook for node maintenance, OSD replacement, MachineConfig cleanup, operator uninstall, and cluster destruction.

## Node Maintenance

For SNO, treat node maintenance as an outage. Confirm backups and post-reboot checks; draining cannot preserve availability when there is only one node.

For multi-node:

```bash
oc adm cordon <node>
oc adm drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=<duration>
```

Perform maintenance. If the node has OSDs, Ceph will re-replicate data to remaining OSDs. Ensure the cluster has enough free capacity.

After maintenance, uncordon:

```bash
oc adm uncordon <node>
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
```

## OSD Replacement

See `references/cluster-expand-shrink.md` for detailed OSD replacement steps. Always verify cluster health before and after replacement.

## Operator Uninstall

### Helm Uninstall

```bash
helm uninstall rook-ceph -n rook-ceph
```

### Manifest Uninstall

Delete the Rook Ceph resources in reverse order:

```bash
oc -n rook-ceph delete cephnfs --all --wait=true --timeout=10m
oc -n rook-ceph delete cephobjectstore --all --wait=true --timeout=10m
oc -n rook-ceph delete cephfilesystem --all --wait=true --timeout=10m
oc -n rook-ceph delete cephblockpool --all --wait=true --timeout=10m
oc -n rook-ceph delete cephcluster rook-ceph --wait=true --timeout=10m
```

Wait for the operator to clean up OSDs, mons, and mgrs. Then remove the CSI custom resources **before** the CSI operator (otherwise their finalizers block the operator and namespace teardown), then delete the operator, common resources, and namespace:

```bash
# Delete ceph-csi CRs first so the csi-operator can finalize cleanly:
oc -n rook-ceph delete drivers.csi.ceph.io,operatorconfigs.csi.ceph.io,cephconnections.csi.ceph.io,clientprofiles.csi.ceph.io,clientprofilemappings.csi.ceph.io --all --wait=false --ignore-not-found
oc delete -f /tmp/rook-ceph-operator.yaml
oc delete -f /tmp/rook-ceph-csi-operator.yaml
oc delete -f /tmp/rook-ceph-common.yaml
oc delete namespace rook-ceph --wait=true --timeout=10m
```

### Namespace Stuck Terminating And Orphaned Cluster-Scoped Objects

Namespace deletion can hang because a `csi.ceph.io` CR (for example `clientprofiles.csi.ceph.io/rook-ceph`) keeps its finalizer after the operator is gone. Prefer the targeted CR deletes above; if the namespace is still stuck, clear finalizers on the **confirmed** blocking CRs (inspect first, then patch):

```bash
for kind in $(oc api-resources --api-group=csi.ceph.io -o name 2>/dev/null); do
  for item in $(oc -n rook-ceph get "$kind" --no-headers -o custom-columns=:.metadata.name 2>/dev/null); do
    oc -n rook-ceph patch "$kind" "$item" --type=merge -p '{"metadata":{"finalizers":[]}}'
  done
done
```

Also inspect `ceph.rook.io` CRs the same way if a `CephCluster` stays in `Deleting`. Keep mounts and consumers removed before clearing any finalizer.

Several objects are **cluster-scoped and survive the namespace deletion** — they must be removed by name or a later reinstall reuses stale definitions. Query **both** StorageClasses and CSIDrivers (custom `CSI_DRIVER_NAME_PREFIX` values and user-created StorageClasses/VolumeSnapshotClasses may differ from the defaults), confirm nothing depends on them, then delete every match:

```bash
# This Rook cluster's CSI driver names share a fixed prefix (default "rook-ceph"; if the
# operator sets CSI_DRIVER_NAME_PREFIX, use that). Match ONLY that prefix so a second Ceph
# cluster's ".csi.ceph.com" drivers/snapshotclasses are never touched.
PFX="rook-ceph"   # = CSI_DRIVER_NAME_PREFIX if customized
# StorageClasses owned by this cluster (by provisioner):
oc get sc -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.provisioner}{"\n"}{end}' \
  | grep -E "(^| )${PFX}(-|\.)|${PFX}\.ceph\.rook\.io/bucket"
# CSIDrivers and VolumeSnapshotClasses owned by this cluster (exact prefix, not a bare .ceph.com):
oc get csidriver -o name | grep -E "/${PFX}\.(rbd|cephfs|nfs)\.csi\.ceph\.com$"
oc get volumesnapshotclass -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.driver}{"\n"}{end}' 2>/dev/null \
  | grep -E " ${PFX}\.(rbd|cephfs|nfs)\.csi\.ceph\.com$" || true
# Print the matches, confirm no PV/PVC/snapshot still depends on them, THEN delete each matched name:
oc delete sc <matched-storageclasses> --ignore-not-found
oc delete csidriver <matched-csidrivers> --ignore-not-found
oc delete volumesnapshotclass <matched-snapshotclasses> --ignore-not-found
```

After the namespace is gone, clear the mon/OSD `dataDirHostPath` on every storage node so a reinstall starts clean (a leftover mon store crashes the new mon). Read the configured path from the `CephCluster` (do not assume `/var/lib/rook`) and remove **all** children including hidden entries:

```bash
# Capture spec.dataDirHostPath BEFORE deleting the CephCluster (default /var/lib/rook):
DDHP="$(oc -n rook-ceph get cephcluster rook-ceph -o jsonpath='{.spec.dataDirHostPath}' 2>/dev/null || echo /var/lib/rook)"
oc debug node/<node> -- chroot /host bash -c "shopt -s dotglob; rm -rf '${DDHP:-/var/lib/rook}'/*; ls -la '${DDHP:-/var/lib/rook}'/"
```

### Stale krbd Devices

Before removing the Ceph pools or a consumer namespace, make sure every RBD-backed PVC is unmounted and **unmapped**. If an RBD image is deleted (or its pool is destroyed) while a `/dev/rbdN` mapping is still open on a node, that mapping is orphaned against a cluster that no longer exists. A later Rook OSD prepare then hangs indefinitely at `ceph-volume raw list` (it probes the dead `/dev/rbdN`), and the device cannot be removed from userspace — `/sys/bus/rbd/remove*` blocks uninterruptibly and can wedge a node shutdown. Drain consumers first (delete app PVCs with `--wait=true` so CSI unmaps them), then check each node:

```bash
oc debug node/<node> -- chroot /host bash -c '
  ls /dev/rbd[0-9]* 2>/dev/null || echo "no /dev/rbd[0-9]* devices"
  for r in /sys/bus/rbd/devices/*; do [ -e "$r" ] && echo "rbd $(basename $r): pool=$(cat $r/pool 2>/dev/null) image=$(cat $r/name 2>/dev/null)"; done
'
```

Unmap a leftover from the affected node. `rbd device unmap --force` is a local kernel operation that does not need the pool, but it **waits for in-flight I/O**, so a fully wedged mapping can block — wrap it in `timeout`. If that times out, run the sysfs fallback synchronously under its own `timeout` (a background job inside `oc debug` dies with the debug pod). Run it node-local, using the RBD id from `/sys/bus/rbd/devices/`:

```bash
oc debug node/<node> -- chroot /host bash -c '
  ID="<rbd-id>"   # from /sys/bus/rbd/devices/
  timeout 30 rbd device unmap --force "/dev/rbd${ID}" && exit 0
  if [ -e /sys/bus/rbd/remove_single_major ]; then
    timeout 60 sh -c "printf \"%s force\n\" \"${ID}\" > /sys/bus/rbd/remove_single_major"
  else
    timeout 60 sh -c "printf \"%s force\n\" \"${ID}\" > /sys/bus/rbd/remove"
  fi
'
```

After either path, re-check both `/dev/rbd[0-9]*` and `/sys/bus/rbd/devices/*` before pool deletion or reinstall:

```bash
oc debug node/<node> -- chroot /host bash -c '
  ls /dev/rbd[0-9]* 2>/dev/null || echo "no /dev/rbd[0-9]* devices"
  ls /sys/bus/rbd/devices/* 2>/dev/null || echo "no /sys/bus/rbd/devices entries"
'
```

If either path is still populated, a **node reboot (or hypervisor power-cycle for a wedged VM) is the reliable fix** — krbd mappings do not persist across reboot. After a reboot, confirm `/dev/rbd[0-9]*` and `/sys/bus/rbd/devices/*` are both empty before reinstalling.

If the cluster was installed with the direct manifest path (crds.yaml was applied), delete the CRDs last. CRD deletion is irreversible and will cascade-delete any remaining custom resources — only proceed after the namespace is fully removed and the post-uninstall audit confirms no CRs remain:

```bash
oc delete -f /tmp/rook-ceph-crds.yaml
```

## Post-Uninstall Audit

After uninstall, confirm:

- `rook-ceph` namespace is absent.
- `oc api-resources --api-group=ceph.rook.io` returns no Rook Ceph resources.
- No StorageClass uses a Rook Ceph provisioner (`rook-ceph.rbd.csi.ceph.com`, `rook-ceph.cephfs.csi.ceph.com`, `rook-ceph.ceph.rook.io/bucket`).
- No PV/PVC uses a Rook Ceph StorageClass.
- Exactly one intended default StorageClass remains.

Run the post-uninstall audit script:

```bash
bash scripts/post_uninstall_audit.sh
```

Equivalent manual checks:

```bash
oc get namespace rook-ceph 2>/dev/null || true
oc api-resources --api-group=ceph.rook.io
oc get sc | grep rook-ceph || true
oc get pv,pvc -A -o wide | grep rook-ceph || true
oc get clusterrole,clusterrolebinding | grep -i rook-ceph || true
oc get priorityclass rook-ceph-default 2>/dev/null || true
oc get csidriver | grep rook-ceph || true
```

## Cluster Destruction (Data Loss)

Destroying the Ceph cluster destroys all data. Require explicit destructive confirmation before proceeding.

### Option A: Rook-native cleanup (recommended)

Set `cleanupPolicy` on the CephCluster **before** deleting it. With the required
confirmation string, Rook runs a job that zaps each OSD disk and removes
`dataDirHostPath` automatically, so you do not have to wipe disks by hand. This
is irreversible — only apply it when you intend to erase all data:

```bash
oc -n rook-ceph patch cephcluster rook-ceph --type=merge \
  -p '{"spec":{"cleanupPolicy":{"confirmation":"yes-really-destroy-data"}}}'
```

Then delete the CephCluster (the operator runs the cleanup job) and continue with
the operator uninstall steps above. Watch the cleanup jobs complete before
deleting the namespace:

```bash
oc -n rook-ceph delete cephcluster rook-ceph --wait=true --timeout=10m
oc -n rook-ceph get pods -l app=rook-ceph-cleanup
```

### Option B: Manual disk cleanup

If `cleanupPolicy` was not used (or you need to reclaim disks after the fact):

1. Follow the operator uninstall steps above.
2. After the namespace is removed, clean the OSD disks:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
  lsblk -f '${DISK}'
"
```

3. Remove MachineConfigs created for Rook Ceph if any.
4. Remove node labels.

## MachineConfig Cleanup

MachineConfig cleanup can reboot nodes. On SNO, warn about temporary API loss. Find Rook Ceph-specific MachineConfigs before deciding what to remove:

```bash
oc get machineconfig | grep -i rook || true
oc get machineconfig <name> -o yaml
```

After changes:

```bash
oc wait mcp/<pool> --for=condition=Updated=True --timeout=45m
oc get mcp <pool> -o wide
oc get nodes
```

If MCP is degraded, stop and inspect before proceeding.

## SCC Cleanup

Remove SCC grants when uninstalling Rook Ceph or after emergency repair work that granted additional privileges beyond the standard operator requirements:

```bash
oc adm policy remove-scc-from-user privileged -z rook-ceph-osd -n rook-ceph
oc adm policy remove-scc-from-user privileged -z rook-ceph-system -n rook-ceph
oc adm policy remove-scc-from-user privileged -z rook-ceph-mgr -n rook-ceph
```

List service accounts and SCC use if cleanup is uncertain:

```bash
oc get rolebindings,clusterrolebindings -A | grep -i rook || true
oc adm policy who-can use scc privileged
```
