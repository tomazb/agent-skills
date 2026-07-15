# Maintenance And Uninstall

Use this runbook for node maintenance, OSD replacement, MachineConfig cleanup, ODF operator uninstall, and cluster removal. Uninstall ODF through OLM and the `StorageCluster`, not by deleting Rook CRs by hand.

## Node Maintenance

For SNO, treat node maintenance as an outage. Confirm backups and post-reboot checks; draining cannot preserve availability when there is only one node.

For multi-node:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd set noout
oc adm cordon <node>
oc adm drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=<duration>
```

Set `noout` before draining so Ceph does not immediately rebalance data off a node that will return. Perform maintenance, uncordon the node, and confirm the OSDs have recovered before clearing the flag:

```bash
oc adm uncordon <node>
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd unset noout
```

## OSD Replacement

See `references/cluster-expand-shrink.md` for the supported `ocs-osd-removal` job and disk-replacement steps. Always verify cluster health before and after replacement.

## Uninstall ODF

ODF uninstall is a documented, ordered process. It has two independent annotations:

- `uninstall.ocs.openshift.io/mode="graceful"` (the default) pauses until all ODF PVCs and OBCs are removed. `mode="forced"` proceeds despite those consumers and leaves orphaned PVCs and OBCs; it does not delete them safely.
- `uninstall.ocs.openshift.io/cleanup-policy="delete"` removes ODF `DataDirHostPath` data and OSD disks. `cleanup-policy="retain"` preserves them for a later recovery decision.

Confirm both the consumer-handling and disk-data intent with the user before choosing annotations.

### 1. Remove consumers

For the default graceful mode, delete application PVCs and OBCs that use ODF StorageClasses, and any custom StorageClasses you created on top of ODF. The cluster must have no bound ODF volumes before removing the `StorageCluster`. Use forced mode only when the user explicitly accepts orphaned claims and their recovery implications.

### 2. Set the uninstall annotations

```bash
# Choose delete only when the OSD disks and /var/lib/rook data may be erased.
oc annotate storagecluster ocs-storagecluster -n openshift-storage \
  uninstall.ocs.openshift.io/cleanup-policy="delete" --overwrite
# Graceful waits for all ODF PVCs and OBCs to be removed.
oc annotate storagecluster ocs-storagecluster -n openshift-storage \
  uninstall.ocs.openshift.io/mode="graceful" --overwrite
```

Use `mode="forced"` only when you accept orphaned ODF PVCs and OBCs. To preserve OSD disk data and `/var/lib/rook`, set `cleanup-policy="retain"` instead of `delete`; it does not change the forced/graceful consumer behavior.

### 3. Delete the StorageCluster

```bash
oc -n openshift-storage delete storagecluster ocs-storagecluster --wait=true --timeout=15m
```

`ocs-operator` tears down the reconciled Rook `CephCluster`, pools, filesystem, object store, and NooBaa system, and cleans OSD disks according to the cleanup policy. Watch it drain:

```bash
oc -n openshift-storage get storagecluster,cephcluster,noobaa -o wide
oc -n openshift-storage get pods -o wide
```

### 4. Remove the operator and namespace

```bash
oc -n openshift-storage delete subscription --all
oc -n openshift-storage delete csv -l operators.coreos.com/odf-operator.openshift-storage
oc delete namespace openshift-storage --wait=true --timeout=15m
```

Remove the storage node labels after confirming the node no longer hosts another storage system:

```bash
oc label node <node> cluster.ocs.openshift.io/openshift-storage- || true
```

Before deleting LSO objects, inventory their ownership:

```bash
oc -n openshift-local-storage get localvolumeset,localvolume,localvolumediscovery -o wide
```

Delete only named `LocalVolumeSet` and `LocalVolumeDiscovery` objects that were dedicated to ODF. Never use `--all`, and do not delete LSO resources when `LocalVolume`, Longhorn, LVMS, or another storage system shares the node or namespace.

## Post-Uninstall Audit

After uninstall, confirm:

- `openshift-storage` namespace is absent.
- `oc api-resources --api-group=ocs.openshift.io` and `--api-group=ceph.rook.io` return no leftover ODF/Rook resources in use.
- No StorageClass uses an ODF provisioner (`openshift-storage.rbd.csi.ceph.com`, `openshift-storage.cephfs.csi.ceph.com`, `openshift-storage.noobaa.io/obc`, `openshift-storage.ceph.rook.io/bucket`).
- No PV/PVC uses an ODF StorageClass.
- Exactly one intended default StorageClass remains.

Run the post-uninstall audit script:

```bash
bash scripts/post_uninstall_audit.sh
```

Equivalent manual checks:

```bash
oc get namespace openshift-storage 2>/dev/null || true
oc api-resources --api-group=ocs.openshift.io
oc get sc | grep -E 'openshift-storage|ocs-storagecluster' || true
oc get pv,pvc -A -o wide | grep -E 'openshift-storage|ocs-storagecluster' || true
oc get csidriver | grep openshift-storage || true
```

## Disk Cleanup (Data Loss)

An uninstall with `cleanup-policy="delete"` wipes the OSD disks automatically. If the policy was not set, or you need to reclaim disks after the fact, clean each OSD disk only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target. `wipefs -af` and `sgdisk --zap-all` are sufficient for non-Ceph disks, but a disk that previously held a BlueStore OSD requires full-disk zeroing to clear the labels at its midpoint and end:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

# Standard signature and partition-table cleanup:
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"

# Required only when the disk previously held a BlueStore OSD:
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  dd if=/dev/zero of='${DISK}' bs=4M status=progress
  sync
  lsblk -f '${DISK}'
"
```

Full-disk zeroing can take a long time. See `references/local-storage-disks.md` for the BlueStore cleanup rationale and post-wipe checks.

## MachineConfig Cleanup

MachineConfig cleanup can reboot nodes. On SNO, warn about temporary API loss. Find ODF-specific MachineConfigs before deciding what to remove:

```bash
oc get machineconfig | grep -iE 'ocs|odf|rook' || true
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

ODF binds its own scoped SecurityContextConstraints through the operator bundle, and removing the operator removes them. Do not hand-remove the built-in `privileged` SCC from ODF service accounts unless you granted it manually during emergency repair. If a manual grant was made, remove only that exact grant:

```bash
oc get scc | grep -E 'rook-ceph|noobaa' || true
oc adm policy who-can use scc privileged
```
