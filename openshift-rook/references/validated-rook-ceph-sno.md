# Validated Rook Ceph SNO Scenario

This is observed evidence for one OpenShift SNO / Rook Ceph scenario. Do not
turn these host-specific values into defaults without confirming the target
cluster.

## Cluster Details

- OpenShift version: 4.22
- Rook version: v1.20.2
- Ceph version: v20.2.2
- Topology: Single Node OpenShift (SNO)
- Storage services: RBD, CephFS, RGW

## Disk Layout

- One dedicated NVMe disk for OSD data (SNO has one node, one disk).
- The cluster used explicit `/dev/disk/by-id/<stable-id>` device pinning instead
  of `useAllDevices: true`.

## CephCluster Configuration (SNO)

```yaml
spec:
  mon:
    count: 1
    allowMultiplePerNode: true
  mgr:
    count: 1
    allowMultiplePerNode: true
  cephConfig:
    global:
      osd_pool_default_size: "1"
      mon_warn_on_pool_no_redundancy: "false"
      mon_max_pg_per_osd: "500"
  storage:
    useAllNodes: false
    useAllDevices: false
    nodes:
    - name: "<sno-node>"
      devices:
      - name: /dev/disk/by-id/<stable-id>
```

## Pool Configuration

- RBD pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS metadata pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS data pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- RGW metadata pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- RGW data pool: `replicated.size: 1`, `requireSafeReplicaSize: false`

## StorageClasses

- `lvms-vg1` remained the default StorageClass
- `rook-ceph-block` (non-default RBD)
- `rook-cephfs` (non-default CephFS)
- `rook-ceph-rgw-obc` (ObjectBucketClaim provisioning)

## Validation Notes

- After install, `ceph -s` showed `HEALTH_OK`.
- OSD was created on the dedicated disk.
- Smoke tests for RBD and CephFS passed.
- RGW Route returned an HTTP response from `Ceph Object Gateway`, and an
  ObjectBucketClaim created the expected Secret and ConfigMap.
- The dashboard Route worked with edge termination to the `http-dashboard` mgr
  service port.
- Dashboard metrics used an internal Prometheus with `PROMETHEUS_API_HOST`
  pointing at a persistent PVC-backed StatefulSet in `rook-ceph`.
- `ceph orch status` reported `Backend: rook` and `Available: Yes`.
- Post-reboot checks showed mon in quorum, OSD up, MDS active, and cluster
  health remained `HEALTH_OK`.
