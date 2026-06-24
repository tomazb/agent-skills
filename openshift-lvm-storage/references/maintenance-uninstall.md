# Maintenance And Uninstall

Use this runbook for node maintenance, disk removal from VGs, LVMS operator uninstall, TopoLVM CSI removal, and cluster cleanup on OpenShift/OKD.

## Node Maintenance

### Drain the Node

Before maintenance that removes the node from the cluster, drain it. Pods with LVMS volumes will be evicted but cannot be rescheduled to another node because the volume is local.

```bash
oc drain <node> --ignore-daemonsets --delete-emptydir-data --force
```

**Warning**: Pods with LVMS volumes will be stuck in `Terminating` if the node is lost. You may need to force-delete them after the node is removed:

```bash
oc delete pod <pod-name> -n <namespace> --force --grace-period=0
```

### Quiesce the VG

On the node, verify the VG is quiescent (no active LVs in use):

```bash
oc debug node/<node> -- chroot /host bash -c "lvs -o lv_name,vg_name,attr; vgs"
```

Check that all LVs show `a` (active) only for pods that are still running, or `o` (open) for LVs that were in use.

### Node Reboot

After reboot, the `LVMCluster` should reconcile automatically. Verify:

```bash
oc -n openshift-storage get lvmcluster lvmcluster -o wide
oc get nodes <node>
oc -n openshift-storage get pods -l app=topolvm-csi -o wide
```

## Disk Removal from VG

See `references/expand-shrink.md` for disk replacement and removal procedures. Key points:

- Verify no LVs have extents on the target disk (`pvdisplay -m`).
- Use `vgreduce` and `pvremove` only after confirming no data exists on the disk.
- Update the `LVMCluster` CR to remove the disk path after host-level removal.

## LVMS Operator Uninstall

### Remove Workloads

Before uninstalling, remove all PVCs and pods that use LVMS StorageClasses. Uninstalling while volumes are in use leaves orphaned LVs in the VG:

```bash
oc get pvc -A -o wide | grep lvms
oc get pv -o wide | grep topolvm
```

Delete all workloads that depend on LVMS volumes. Warn the user that this is destructive for application data.

### Remove LVMCluster

Delete the `LVMCluster` CR. The operator will attempt to clean up VGs and thin pools if configured:

```bash
oc -n openshift-storage delete lvmcluster lvmcluster
oc -n openshift-storage wait lvmcluster/lvmcluster --for=delete --timeout=5m || true
```

### Remove the Operator (OLM)

```bash
oc -n openshift-storage delete subscription lvms-operator
oc -n openshift-storage delete csv <lvms-operator-csv-name>
```

### Remove the Namespace

```bash
oc delete namespace openshift-storage --wait=false
oc get namespace openshift-storage -o yaml | grep -E 'status|phase'
```

If the namespace is stuck in `Terminating` due to finalizers, check for remaining resources:

```bash
oc -n openshift-storage get all
oc api-resources --api-group=topolvm.io --verbs=list | awk '{print $1}' | xargs -I {} oc -n openshift-storage get {} 2>/dev/null || true
```

## Host-Level Cleanup (Manual)

The LVMS operator does not automatically clean up VGs, thin pools, or LVs from nodes after uninstall. This must be done manually on each node if the disks are to be reused.

**Warning**: These commands are destructive and require explicit confirmation.

### Verify Current State

```bash
oc debug node/<node> -- chroot /host bash -c "
  pvs
  vgs
  lvs
  lsblk -f
"
```

### Remove LVs, Thin Pools, and VGs

```bash
oc debug node/<node> -- chroot /host bash -c "
  set -e
  # Remove logical volumes
  lvremove -y /dev/vg1/* || true
  # Remove thin pool (if not already removed by lvremove)
  lvremove -y /dev/vg1/thin-pool-1 || true
  # Remove volume group
  vgremove -y vg1 || true
  # Remove physical volume signatures
  pvremove -y /dev/disk/by-id/<disk-id> || true
"
```

### Wipe Disk Signatures (if reusing disks)

```bash
oc debug node/<node> -- chroot /host bash -c "
  wipefs -a /dev/disk/by-id/<disk-id>
"
```

**Warning**: `wipefs -a` is destructive. Require explicit confirmation before running it.

## Post-Uninstall Audit

After uninstall, run the read-only audit script to confirm nothing is left behind:

```bash
bash scripts/post_uninstall_audit.sh
```

Or manually verify:

```bash
oc api-resources --api-group=topolvm.io
oc get csidriver topolvm.io 2>/dev/null || true
oc get sc | grep lvms || true
oc get pv,pvc -A | grep topolvm || true
oc get scc | grep topolvm || true
oc get namespace openshift-storage 2>/dev/null || true
oc get csv -A | grep lvms || true
oc get subscription -A | grep lvms || true
```

## Safety Rules

- Never uninstall the LVMS operator while workloads are using LVMS volumes. This orphans LVs and can cause data loss.
- Require explicit destructive confirmation before `lvremove`, `vgremove`, `pvremove`, or `wipefs`.
- Before destructive disk actions, require `readlink -f`, `lsblk -f`, `pvs`, `vgs`, `lvs`, and `wipefs -n` evidence.
- Use stable `/dev/disk/by-id/*` paths for destructive targeting.
- Host-level cleanup is not reconciled by the operator. Document all manual changes.
- On SNO, node maintenance removes API access until the single node returns.
