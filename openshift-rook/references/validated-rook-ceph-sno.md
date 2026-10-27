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
- `HEALTH_WARN` for `AUTH_INSECURE_KEYS_ALLOWED` stayed after the successful mount because `allowedCiphers` was left empty. An empty list allows every cipher. The install default is now `allowedCiphers: [aes256k]` once every key prefix is `Ag`.
- The kernel release string was below 7.0, and the volume still mapped. The probe, not `uname -r`, decided the cipher.

## OpenShift 4.18.56 SNO

Observed on one SNO node. The node also had a boot disk and an LVMS disk. Record versions and topology only.

- OpenShift 4.18.56, Kubernetes 1.31.14, kernel `5.14.0-427.151.1.el9_4`, FIPS off.
- Rook v1.21.1, Ceph v20.2.4, ceph-csi v3.18.1. ceph-csi-operator v1.1.0 was the operator; its image-set `plugin` field was empty and the running plugin was the built-in `quay.io/cephcsi/cephcsi:v3.18.1`.
- The OSD disk was a 954G NVMe. `ceph-volume lvm list` exited 1 with `No valid Ceph lvm devices found` because the disk had no LVM OSD. `ceph-volume raw list` printed `{}` while `lsblk` and `wipefs` still reported `ceph_bluestore`. The OSD came up only after both probes were clean. The boot disk and the LVMS PV stayed untouched.
- `driverSpecDefaults.controllerPlugin.replicas` was 1. The controller Deployment has required anti-affinity on `kubernetes.io/hostname`, so the built-in replica count of 2 cannot schedule on one node.
- The toolbox image was pinned to `quay.io/ceph/ceph:v20.2.4` instead of the example tag `v20`.
- RBD pool replica size was 1. `rook-ceph-block` was not the default StorageClass. `lvms-vg1` remained the default, and the registry claim stayed on it.
- The AES256K probe wrote `ok` through `/dev/rbd0`. A full key audit reported 25 `aes256k` keys.
- `status.phase` was `Ready` while `status.ceph.health` was still `HEALTH_WARN`. `ceph health detail` was `HEALTH_OK`, and a two-minute observation stayed `HEALTH_OK` with no new crash records.
- An RBD snapshot restore matched the source. The optional Rook manager module stayed disabled.
- `oc apply` of `operator-openshift.yaml` warned about PodSecurity `restricted:latest`. The `rook-ceph` SCC admitted the operator pod.
