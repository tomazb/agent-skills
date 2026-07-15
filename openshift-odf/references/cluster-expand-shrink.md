# Capacity Expansion And Shrink

Use this runbook for adding capacity, adding OSD nodes, replacing disks, or rebalancing Ceph capacity on ODF. Drive all capacity changes through the `StorageCluster` CR and the Local Storage Operator, not by editing the Rook `CephCluster` directly.

## Adding Capacity (scaling the StorageDeviceSet)

ODF adds capacity in units of the device set `replica` count (three OSDs at a time on multi-node production). Increase `count` on the existing `StorageDeviceSet` rather than editing the Rook `CephCluster`:

```bash
oc -n openshift-storage patch storagecluster ocs-storagecluster --type=json \
  -p '[{"op":"replace","path":"/spec/storageDeviceSets/0/count","value":2}]'
```

`ocs-operator` provisions new OSDs from available `localblock` PVs. Make sure the Local Storage Operator has discovered and provisioned enough new disks first (see `references/local-storage-disks.md`).

## Adding OSD Nodes

Label the new node so ODF schedules OSDs, mons, and mgrs on it:

```bash
oc label node <new-node> cluster.ocs.openshift.io/openshift-storage='' --overwrite
```

Extend the `LocalVolumeSet` node selector (or let the existing `Exists` selector match) so LSO provisions PVs on the new node, then raise the `StorageDeviceSet` `count` to consume them. After the operator reconciles, validate:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd df
```

Wait for `HEALTH_OK` or `HEALTH_WARN` with only known warnings before declaring the expansion complete.

## Removing OSDs

Never remove an OSD without checking replica counts and pool health. If a pool has `replicated.size: 3` and you have exactly 3 OSDs, removing one degrades data with no spare to replicate to.

### Pre-Removal Safety Gate

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd stat
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph df
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph health detail
```

Do not proceed if `ceph health detail` shows any existing degradation.

### Planned OSD Removal (ODF template job)

On ODF, remove a failed OSD with the supported `ocs-osd-removal` template job rather than deleting Rook resources by hand. The job marks the OSD `out`, waits for rebalancing, and purges it from the CRUSH map, auth, and OSD map:

```bash
# Scale down the OSD deployment for the failed osd id first:
oc -n openshift-storage scale deployment rook-ceph-osd-<id> --replicas=0

# Run the supported removal job:
oc process -n openshift-storage ocs-osd-removal \
  -p FAILED_OSD_IDS=<id> -p FORCE_OSD_REMOVAL=false | oc create -f -

# Watch it complete:
oc -n openshift-storage logs -l job-name=ocs-osd-removal-job -f
```

Use `FORCE_OSD_REMOVAL=true` only when the OSD is already down and you accept the documented data-safety implications. After the job succeeds, delete its completed job object and let LSO reclaim the underlying PV.

## Replacing a Failed Disk

1. Verify the OSD is down and the disk is truly failed.
2. Run the `ocs-osd-removal` job above for the failed OSD id.
3. After the OSD is fully removed, delete the released local PV and clean the disk if reusing it (only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target):

```bash
oc debug "node/<node>" -- chroot /host bash -c "
  wipefs -af '/dev/disk/by-id/<disk>'
  sgdisk --zap-all '/dev/disk/by-id/<disk>'
"
```

4. Let the Local Storage Operator rediscover and reprovision the replacement disk into `localblock`.
5. Wait for `ocs-operator` to create a new OSD and for the cluster to rebalance.

## Rebalancing And PG Backfill

Rebalancing can be IO-intensive. If backfill is impacting performance, throttle it through the toolbox:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph config set osd osd_max_backfills 1
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph config set osd osd_recovery_max_active 1
```

Restore defaults after recovery:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph config rm osd osd_max_backfills
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph config rm osd osd_recovery_max_active
```

## SNO Considerations

On SNO, adding capacity increases usable space but does not improve availability. Rebalancing is limited by single-node resources. ODF capacity on a single node stays a single-replica topology; warn the user about resource constraints and the single failure domain.
