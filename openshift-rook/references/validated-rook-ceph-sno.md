# Validated Rook Ceph SNO Scenario

This is observed evidence for one OpenShift SNO / Rook Ceph scenario. Do not turn these host-specific values into defaults without confirming the target cluster.

## Cluster Details

- OpenShift version: 4.16
- Rook version: v1.14.0
- Ceph version: v18.2.2
- Topology: Single Node OpenShift (SNO)
- Storage services: RBD, CephFS

## Disk Layout

- One dedicated SSD per node for OSD data (SNO has one node, one disk).
- Disk path: `/dev/disk/by-id/<stable-id>` (do not use as a default).

## CephCluster Configuration (SNO)

```yaml
spec:
  mon:
    count: 1
    allowMultiplePerNode: true
  mgr:
    count: 1
    allowMultiplePerNode: true
  storage:
    useAllNodes: true
    useAllDevices: true
```

## Pool Configuration

- RBD pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS metadata pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS data pool: `replicated.size: 1`, `requireSafeReplicaSize: false`

## StorageClasses

- `rook-ceph-block` (default for RBD)
- `rook-cephfs` (for CephFS)

## Validation Notes

- After install, `ceph -s` showed `HEALTH_OK`.
- OSD was created on the dedicated disk.
- Smoke tests for RBD and CephFS passed.
- Post-reboot checks showed mon in quorum, OSD up, MDS active.
