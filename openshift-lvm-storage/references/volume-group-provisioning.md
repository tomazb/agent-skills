# Volume Group Provisioning

Use this runbook for volume group creation, thin pool configuration, `DeviceClass` setup, and disk management on OpenShift nodes.

## VG Creation Overview

The LVMS operator creates volume groups (VGs) and thin pools on target nodes based on the `LVMCluster` CR. The operator runs `vgcreate`, `pvcreate`, and `lvcreate` on the host via privileged DaemonSet pods. You do not run these commands manually unless troubleshooting.

## Device Selector Options

The `deviceSelector` in the `LVMCluster` supports multiple discovery methods. Choose one per `DeviceClass`:

### By Stable Disk Path (Recommended)

```yaml
deviceSelector:
  paths:
    - /dev/disk/by-id/<stable-disk-id>
```

### By Multiple Paths

```yaml
deviceSelector:
  paths:
    - /dev/disk/by-id/<disk-1>
    - /dev/disk/by-id/<disk-2>
```

### By Path (for virtual/less stable environments)

```yaml
deviceSelector:
  paths:
    - /dev/disk/by-path/<pci-path>
```

### By Force Wipe (for reused disks with existing signatures)

```yaml
deviceSelector:
  paths:
    - /dev/disk/by-id/<disk-id>
  forceWipeDevicesAndDestroyAllData: true
```

**Warning**: `forceWipeDevicesAndDestroyAllData` is destructive. It runs `wipefs` and `pvcreate` on the specified disks, destroying any existing data. Require explicit destructive confirmation before enabling this flag.

### Omitting deviceSelector (use all available disks)

If `deviceSelector` is omitted, the operator attempts to use all available unpartitioned disks on matching nodes. This is risky on multi-purpose nodes. Prefer explicit `paths`.

## Thin Pool Configuration

Thin pools allow over-provisioning and efficient snapshot support. The `thinPoolConfig` controls pool creation:

```yaml
thinPoolConfig:
  name: thin-pool-1
  overprovisionRatio: 10
  sizePercent: 90
```

- `name`: the logical volume name for the thin pool inside the VG.
- `sizePercent`: percentage of the VG to allocate to the thin pool (e.g., `90`).
- `overprovisionRatio`: the thin pool over-provisioning multiplier (e.g., `10` means 10x the physical capacity can be provisioned).

## Disk Preparation for New Disks

Before adding a new disk to an existing `LVMCluster`, verify it is clean:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${DISK}'
  lsblk -f '${DISK}'
  pvs '${DISK}' || true
  wipefs -n '${DISK}' || true
"
```

If the disk has existing LVM signatures, decide whether to:
- Remove the old VG manually (destructive, requires confirmation);
- Use `forceWipeDevicesAndDestroyAllData` (also destructive);
- Choose a different disk.

## Node-Level LVM Verification

After the `LVMCluster` reports `Ready`, verify VGs and thin pools on each node:

```bash
NODE="<node>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  pvs
  vgs
  lvs
  lvs -o lv_name,vg_name,pool_lv,origin,size,data_percent,metadata_percent
"
```

Check that:
- The VG exists with the expected name.
- The thin pool exists with the expected name and `sizePercent`.
- Physical volumes are the expected disks.
- No data percent warnings on the thin pool.

## Safety Rules for VG Operations

- Never run `pvcreate`, `vgcreate`, `vgremove`, `lvremove`, or `wipefs` on a node unless the user gives explicit destructive confirmation.
- Before every destructive action, require `readlink -f`, `lsblk -f`, `pvs`, `vgs`, `lvs`, and `wipefs -n` evidence.
- Use stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` paths. Never use `/dev/sdX` or `/dev/nvmeXnY` alone.
- `LVMCluster` changes trigger VG reconciliation. A device list change can cause the operator to attempt `pvcreate` or `vgextend`. Warn the user before applying such changes.
- Monitor thin pool usage (`lvs` `data_percent`) and set alerts before the pool reaches critical capacity. Over-provisioning does not create physical space.
