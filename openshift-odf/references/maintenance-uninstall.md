# Maintenance And Uninstall

Use this runbook for node maintenance, OSD replacement, MachineConfig cleanup, ODF operator uninstall, and cluster removal. Uninstall ODF through OLM and the `StorageCluster`, not by deleting Rook CRs by hand.

## Node Maintenance

For SNO, treat node maintenance as an outage. Confirm backups and post-reboot checks; draining cannot preserve availability when there is only one node.

For multi-node:

```bash
oc adm cordon <node>
oc adm drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=<duration>
```

Before draining a storage node, put OSDs into maintenance so Ceph does not immediately rebalance data off a node you plan to return quickly:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd set noout
```

Perform maintenance, then uncordon and clear the flag:

```bash
oc adm uncordon <node>
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd unset noout
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
```

## OSD Replacement

See `references/cluster-expand-shrink.md` for the supported `ocs-osd-removal` job and disk-replacement steps. Always verify cluster health before and after replacement.

## Uninstall ODF

ODF uninstall is a documented, ordered process. Determine the cleanup policy first — a *graceful* uninstall keeps application PVs, a *forced* uninstall removes them. Confirm intent with the user before choosing.

### 1. Remove consumers

Delete application PVCs and OBCs that use ODF StorageClasses, and any custom StorageClasses you created on top of ODF. The cluster must have no bound ODF volumes before removing the `StorageCluster`.

### 2. Set the uninstall mode annotation

```bash
oc annotate storagecluster ocs-storagecluster -n openshift-storage \
  uninstall.ocs.openshift.io/cleanup-policy="delete" --overwrite
oc annotate storagecluster ocs-storagecluster -n openshift-storage \
  uninstall.ocs.openshift.io/mode="graceful" --overwrite
```

Use `mode="forced"` only when you accept removing PVs that are still referenced. This is irreversible for that data.

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

Remove the storage node labels and, if LSO was dedicated to ODF, its `LocalVolumeSet`/`LocalVolumeDiscovery` and namespace:

```bash
oc label node <node> cluster.ocs.openshift.io/openshift-storage- || true
oc -n openshift-local-storage delete localvolumeset,localvolumediscovery --all || true
```

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

A graceful `cleanup-policy="delete"` uninstall wipes the OSD disks automatically. If the policy was not set, or you need to reclaim disks after the fact, clean each OSD disk only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target:

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
