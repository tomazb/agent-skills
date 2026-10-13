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
- The cluster used explicit `/dev/disk/by-id/<stable-disk-id>` device pinning instead
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
      - name: /dev/disk/by-id/<stable-disk-id>
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

## AES256K Probe

Observed on an OpenShift 4.20 SNO node running RHCOS kernel `5.14.0-570.134.1.el9_6`, Rook v1.20.5, and a fresh Ceph `v20.2.4` cluster with `keyType: aes256k` on daemon and CSI keys.

- ceph-csi `v3.17.0` left the RBD claim `Pending` with `rados: ret=-22, Invalid argument`.
- ceph-csi `v3.17.1` (librados `20.2.4`) bound the claim. The pod mounted `/dev/rbd0` and the write returned `ok`.
- `HEALTH_WARN` for `AUTH_INSECURE_KEYS_ALLOWED` stayed after the successful mount.
- The kernel release string was below 7.0, and the volume still mapped. The probe, not `uname -r`, decided the cipher.
