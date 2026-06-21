# Migration Between V1 And V2

Use this runbook for migration between Longhorn V1 filesystem disks and V2 block disks. Migration can mean host disk conversion, volume backup/restore, or new StorageClass rollout; do not imply an in-place data-engine conversion for existing volumes unless the target Longhorn version explicitly supports that workflow.

## Choose The Migration Model

- **New workloads only**: create a new StorageClass with the target `dataEngine` and migrate applications gradually.
- **Existing PVCs**: back up or snapshot, restore into the target class, then cut workloads over.
- **Dedicated disk conversion**: only possible after all Longhorn data on that disk is removed, migrated, or proven unnecessary.
- **SNO lab conversion**: acceptable with one replica only after the user accepts the outage and data-protection posture.

## Required Gates

- Capture volume, replica, engine, backup, StorageClass, and disk state before changing anything.
- Confirm no required Longhorn volume, replica, or engine remains on a disk before removing or wiping it.
- Require explicit destructive confirmation before every `mkfs`, `wipefs`, mount removal, or uninstall step.
- Use `/dev/disk/by-id/*` for block-device targeting and gather `readlink -f`, `lsblk -f`, `findmnt`, and `wipefs -n` immediately before the destructive action.
- Keep exactly one default StorageClass after migration if defaulting is requested.

## V1 Filesystem To V2 Block Disk

1. Verify Longhorn volume state:

   ```bash
   oc -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io -o wide
   oc get pvc,pv -A | grep -i longhorn || true
   ```

2. Apply V2 host prerequisites from `v2-block-data-engine.md` and wait for MCP recovery.

3. Remove the old filesystem mount from the MachineConfig that originally created it. Do not mask an existing mount unit from a later MachineConfig; the MachineConfig daemon validates previous rendered state and can degrade on a regular-file versus symlink mismatch.

4. Verify the path is no longer mounted:

   ```bash
   oc debug "node/${NODE}" -- chroot /host bash -c "
     systemctl is-active var-mnt-longhorn.mount || true
     findmnt /var/mnt/longhorn || true
   "
   ```

5. Mark the old Longhorn filesystem disk unschedulable, evict replicas if any exist, then remove it from the Longhorn node CR only when empty.

6. With explicit destructive confirmation, wipe the dedicated disk and add it as `diskType: block`.

7. Enable `v2-data-engine=true`, create or recreate a V2 StorageClass, and align `longhorn-storageclass` ConfigMap.

8. Run a canary PVC in the target class before moving production workloads.

## V2 Block To V1 Filesystem

1. Create backups or application-level copies of V2 volumes that must survive.
2. Detach and remove or migrate V2 volumes before disabling V2 or wiping a block disk.
3. Remove V2 block disks from Longhorn only after replicas are evicted and no engines depend on them.
4. With explicit destructive confirmation, format the stable `/dev/disk/by-id/*` target, create the filesystem mount MachineConfig, and wait for MCP recovery.
5. Recreate or create a V1 StorageClass with `dataEngine: v1`.
6. Restore workloads and validate one default StorageClass, replica count, and disk placement.

## Stop Conditions

Stop and ask for direction if:

- Any Longhorn volume is `faulted`, `unknown`, or lacks a current backup.
- The target disk has an unexpected filesystem, partition table, mount, or PV dependency.
- MCP is degraded or the only SNO node is not Ready.
- The user has not confirmed destructive intent for the exact target.
