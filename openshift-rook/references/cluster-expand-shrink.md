# Cluster Expand And Shrink

Use this runbook for adding or removing OSD nodes, replacing disks, or rebalancing Ceph capacity on Rook Ceph.

## Adding OSD Nodes

Label the new node and add it to the `CephCluster` storage spec:

```bash
oc label node <new-node> node.ocs.openshift.io/storage=true --overwrite
```

Update the `CephCluster` CR with the new node and its devices:

```yaml
spec:
  storage:
    nodes:
    - name: "<new-node>"
      devices:
      - name: "/dev/disk/by-id/<new-disk>"
```

After the operator reconciles, validate:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df
```

Wait for `HEALTH_OK` or `HEALTH_WARN` with only known warnings before declaring the expansion complete.

## Removing OSDs

Never remove an OSD without checking replica counts and pool health. If a pool has `replicated.size: 3`, losing one OSD can trigger `HEALTH_WARN` if no replacement is available.

### Pre-Removal Safety Gate

Before removing any OSD, verify the cluster has enough OSDs to satisfy all pool replica requirements after the removal. If any pool has `replicated.size: 3` and you have exactly 3 OSDs, removing one will degrade data with no spare to replicate to:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd stat
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph df
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
```

Do not proceed if `ceph health detail` shows any existing degradation.

### Planned OSD Removal

1. Mark the OSD `out` to trigger rebalancing:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd out osd.<id>
```

2. Wait for rebalancing to complete and cluster health to return to `HEALTH_OK`:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
```

3. Remove the disk from the `CephCluster` CR storage spec. Do this before deleting the deployment — if the CR still references the disk when the deployment is deleted, the operator will immediately reconcile and recreate the OSD:

```yaml
# Remove the matching entry from spec.storage.nodes[].devices or spec.storage.nodes[]
```

```bash
oc -n rook-ceph edit cephcluster rook-ceph
```

4. Delete the OSD deployment to stop the daemon container. Do NOT use `ceph osd stop` — it marks the OSD in the map but cannot kill a container process:

```bash
oc -n rook-ceph delete deployment rook-ceph-osd-<id>
```

5. Remove the OSD from the CRUSH map:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd crush remove osd.<id>
```

6. Remove the OSD auth key:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph auth del osd.<id>
```

7. Remove the OSD from the cluster:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd rm osd.<id>
```

8. Verify the OSD is gone:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
```

## Replacing a Failed Disk

1. Verify the OSD is down and the disk is truly failed.
2. Follow the planned OSD removal steps above.
3. After the OSD is fully removed, clean the disk if reusing it:

```bash
oc debug "node/<node>" -- chroot /host bash -c "
  wipefs -af '/dev/disk/by-id/<disk>'
  sgdisk --zap-all '/dev/disk/by-id/<disk>'
"
```

4. Add the disk back to the `CephCluster` storage spec or replace the disk with a new one.
5. Wait for the operator to create a new OSD and for the cluster to rebalance.

## Rebalancing and PG Backfill

Rebalancing can be IO-intensive. If backfill is impacting performance, adjust backfill rates:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph config set osd osd_max_backfills 1
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph config set osd osd_recovery_max_active 1
```

Restore defaults after recovery:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph config rm osd osd_max_backfills
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph config rm osd osd_recovery_max_active
```

## SNO Considerations

On SNO, adding or removing OSDs changes capacity but does not improve availability. Rebalancing is limited by single-node resources. Warn the user about resource constraints.
