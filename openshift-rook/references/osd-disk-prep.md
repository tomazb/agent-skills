# OSD Disk Preparation

Use this runbook for preparing dedicated block disks for Ceph OSDs on OpenShift/RHCOS nodes.

## Disk Selection Gate

Before every destructive disk action, collect non-destructive evidence:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${DISK}'
  lsblk -f '${DISK}'
  wipefs -n '${DISK}' || true
  ceph-volume lvm list '${DISK}' || true
  lsblk -f
"
```

Never proceed from `/dev/sdX`, `/dev/nvmeXnY`, or guessed paths. Resolve and record the stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` identity first.

## Raw Block Preparation (BlueStore)

For BlueStore, the disk should be unpartitioned and free of filesystem signatures. Ceph OSDs use LVM on top of the raw block device.

After explicit destructive confirmation, clean the disk:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"
```

Verify it is clean:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  lsblk -f '${DISK}'
  wipefs -n '${DISK}' || true
  ceph-volume lvm list '${DISK}' || true
"
```

## FileStore (Legacy)

FileStore was removed from Rook in v1.9 and from Ceph in Quincy (v17). It is not an option for any current deployment. Only mention it if the user explicitly asks about migrating away from a very old installation.

## Disk Discovery in Rook CephCluster

Rook discovers OSD disks via the `CephCluster` `storage` spec. Use explicit device names for production, or `useAllDevices: true` with a `deviceFilter` for controlled auto-discovery.

```yaml
spec:
  storage:
    useAllNodes: false
    nodes:
    - name: "node-1"
      devices:
      - name: "/dev/disk/by-id/<disk-1>"
    - name: "node-2"
      devices:
      - name: "/dev/disk/by-id/<disk-2>"
```

## Label Storage Nodes

Label nodes that host OSDs so the Rook operator can place them correctly:

```bash
oc label node <node-1> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-2> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-3> node.ocs.openshift.io/storage=true --overwrite
```

## Validation

After the CephCluster CR is applied and OSDs are created, validate OSD health:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df
oc -n rook-ceph get pods -l app=rook-ceph-osd -o wide
```

Confirm:

- All OSDs are `up` and `in`.
- OSD weights are balanced.
- No OSDs are in `out` or `down` state unless deliberately being replaced.
- LVs created by `ceph-volume` exist on the intended disks.

## SNO OSD Considerations

On SNO, all OSDs run on the same node. Ceph can tolerate this if `allowMultiplePerNode: true` is set, but availability is limited by the single node. Use a reduced replica count and set `mon.count: 1` and `mgr.count: 1`.
