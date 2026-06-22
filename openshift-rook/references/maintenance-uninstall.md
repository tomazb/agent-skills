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
oc -n rook-ceph delete cephobjectstore --all --wait=true --timeout=10m
oc -n rook-ceph delete cephfilesystem --all --wait=true --timeout=10m
oc -n rook-ceph delete cephblockpool --all --wait=true --timeout=10m
oc -n rook-ceph delete cephcluster rook-ceph --wait=true --timeout=10m
```

Wait for the operator to clean up OSDs, mons, and mgrs. Then delete the operator and namespace:

```bash
oc delete -f /tmp/rook-ceph-operator.yaml
oc delete -f /tmp/rook-ceph-common.yaml
oc delete namespace rook-ceph --wait=true --timeout=10m
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

If the user wants to destroy the cluster and erase OSD data:

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
