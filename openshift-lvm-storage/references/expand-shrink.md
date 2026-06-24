# Expand And Shrink

Use this runbook for expanding volume groups, adding or removing disks, thin pool expansion, and node-level disk management for LVMS on OpenShift/OKD.

## Volume Group Expansion

To add a new disk to an existing volume group, update the `LVMCluster` CR's `deviceSelector.paths` list and apply the change. The LVMS operator will run `pvcreate` and `vgextend` on the host.

### Before Expansion

Verify the current state:

```bash
oc -n openshift-storage get lvmcluster lvmcluster -o yaml
NODE="<node>"
oc debug "node/${NODE}" -- chroot /host bash -c "vgs; pvs; lvs"
```

### Add a New Disk

```yaml
apiVersion: lvm.topolvm.io/v1alpha1
kind: LVMCluster
metadata:
  name: lvmcluster
  namespace: openshift-storage
spec:
  storage:
    deviceClasses:
      - name: vg1
        thinPoolConfig:
          name: thin-pool-1
          overprovisionRatio: 10
          sizePercent: 90
        deviceSelector:
          paths:
            - /dev/disk/by-id/<existing-disk>
            - /dev/disk/by-id/<new-disk>
        default: true
```

Apply and wait:

```bash
oc apply -f /tmp/lvmcluster-updated.yaml
oc -n openshift-storage wait lvmcluster/lvmcluster --for=condition=Ready --timeout=10m
```

### Verify Expansion

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "vgs; pvs; lvs"
```

Check that:
- The new PV appears in `pvs`.
- The VG size increased in `vgs`.
- The thin pool did not automatically grow (it is fixed at creation). To expand the thin pool, see Thin Pool Expansion below.

## Thin Pool Expansion

The LVMS operator does not automatically expand the thin pool when the VG grows. You must either:

1. Recreate the `LVMCluster` (destructive, requires data migration); or
2. Manually expand the thin pool on the host (requires node access, not reconciled by the operator).

### Manual Thin Pool Expansion (Not Reconciled)

The LV path is `<vg-name>/<thin-pool-name>`, where `<vg-name>` is the `deviceClasses[].name` field from the `LVMCluster` CR (for example `vg1`), **not** the `openshift-storage` namespace. Confirm both names with `vgs` and `lvs` before running this:

```bash
NODE="<node>"
oc debug "node/${NODE}" -- chroot /host bash -c "
  vgs
  lvs
  lvextend -l +100%FREE <vg-name>/<thin-pool-name>
"
```

**Warning**: Manual host changes are not reconciled by the operator. Document them and verify after any operator upgrade or node reboot.

## Disk Replacement

To replace a failed disk in a VG:

1. Identify the failed disk:
   ```bash
   oc debug "node/${NODE}" -- chroot /host bash -c "pvs; vgs"
   ```

2. Evacuate any LVs from the failing PV if possible (for thick LVs, this may require data migration). For thin pool volumes, the data is spread across the VG and cannot be easily evacuated from a single PV.

3. Resolve the old PV to a stable path, verify there are no remaining extents, and remove it from the VG. Do not continue if `vgreduce` fails:
   ```bash
   OLD_DISK="/dev/disk/by-id/<old-disk-id>"
   oc debug "node/${NODE}" -- chroot /host bash -c "
     set -e
     readlink -f '${OLD_DISK}'
     pvdisplay -m '${OLD_DISK}'
     vgreduce vg1 '${OLD_DISK}'
   "
   ```

4. Update the `LVMCluster` CR to replace the old disk path with the new one.

5. Apply the updated `LVMCluster` and wait for `Ready`.

## Shrinking / Disk Removal

Removing a disk from a VG is risky if the thin pool or any LV has extents on that disk. The LVMS operator does not support automatic shrink or disk removal.

For safe removal:

1. Verify no LVs use the target disk:
   ```bash
   oc debug "node/${NODE}" -- chroot /host bash -c "
     pvdisplay -m /dev/disk/by-id/<target-disk>
   "
   ```

2. If the disk is empty in the VG, remove it manually:
   ```bash
   oc debug "node/${NODE}" -- chroot /host bash -c "
     vgreduce vg1 /dev/disk/by-id/<target-disk>
     pvremove /dev/disk/by-id/<target-disk>
   "
   ```

3. Update the `LVMCluster` CR to remove the disk path.

4. Apply and verify.

**Warning**: `vgreduce` and `pvremove` are destructive if data exists on the disk. Require explicit destructive confirmation before proceeding.

## Safety Rules

- Never add a disk with existing data or LVM signatures without verification. Use `wipefs -n`, `pvs`, and `lvs` evidence first.
- Never remove a disk from a VG unless you confirm it has no allocated extents.
- Manual host LVM changes (`lvextend`, `vgreduce`, `pvremove`) are not reconciled by the operator. Document them.
- Thin pool expansion is not automatic. Plan capacity at `LVMCluster` creation time.
- Use stable `/dev/disk/by-id/*` paths for all disk operations.
