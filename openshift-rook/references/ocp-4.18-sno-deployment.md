# OpenShift 4.18 SNO Deployment Record

Observed on 2026-11-09. This is a redacted deployment record, not a manifest to
reapply blindly. Node names, disk serials, stable hardware IDs, API endpoints,
and credentials are intentionally omitted. Rediscover them on the target cluster.

## Versions and topology

- OpenShift 4.18.44; Kubernetes v1.31.14; oc client 5.0.1.
- RHCOS kernel `5.14.0-427.130.1.el9_4.x86_64`; FIPS disabled.
- One Ready, schedulable node without taints.
- Upstream Rook v1.20.10; Ceph `quay.io/ceph/ceph:v20.2.5`.
- ceph-csi v3.17.1, whose RBD plugin reports a Ceph 20.2.4 client.
- Rook v1.20 supports Kubernetes 1.31. Rook v1.21 requires Kubernetes 1.32:
  a reported successful deployment outside that matrix is not supported-version
  evidence. No OpenShift, kernel, or LVMS upgrade was performed.

## Disk ownership and preparation

The larger NVMe disk, 1,024,209,543,168 bytes (about 953.9 GiB), was dedicated to
Ceph through one explicitly verified `/dev/disk/by-id/<osd-disk-id>` selector.
The OS disk and the smaller LVMS disk were excluded.

The ownership classifier found no Rook or ODF installation. The target disk had
an old raw BlueStore OSD signature, but no partitions, mounts, holders, or LVM OSD.
`/var/lib/rook` and stale RBD mappings were absent. After exact-disk destructive
approval and fresh safety checks, `ceph-bluestore-tool zap-device` from the pinned
Ceph image cleared the old labels. An empty `ceph-volume raw list` and clean
`wipefs -n` / `lsblk -f` confirmed reuse readiness. This was metadata reset, not
whole-device sanitization. See [OSD preparation](osd-disk-prep.md).

## Deployed configuration

Version-pinned `crds.yaml`, `common.yaml`, `csi-operator.yaml`, and
`operator-openshift.yaml` installed upstream Rook in `rook-ceph`, using the
dedicated `rook-ceph` and `rook-ceph-csi` SCCs. The daemon SCC retained
`allowHostNetwork: false` and `allowHostPorts: false`; Ceph uses pod networking.
The CSI SCC keeps its upstream permissions.

- CephCluster `rook-ceph`, namespace `rook-ceph`, data directory `/var/lib/rook`.
- One monitor and one manager, both with `allowMultiplePerNode: true`.
- One OSD on the explicitly selected larger disk, `osdsPerDevice: "1"`,
  `useAllNodes: false`, and `useAllDevices: false`.
- `cephConfig.global`: `osd_pool_default_size: "1"`,
  `mon_warn_on_pool_no_redundancy: "false"`, and `mon_max_pg_per_osd: "500"`.
  The redundancy warning setting documents the deliberate SNO exception; it
  does not provide redundancy. These are not multi-node production defaults.
- Optional `rook` manager module disabled; Prometheus and crash reporting kept.
  Dashboard enabled without an external Route; toolbox pinned to Ceph 20.2.5.
- `ceph-csi-operator-config.spec.driverSpecDefaults.controllerPlugin.replicas: 1`,
  preserving `imageSet.name: rook-csi-operator-image-set-configmap`.
- Shipped RBD and CephFS Drivers use `snapshotPolicy: volumeSnapshot`.
  No group-snapshot feature gates or duplicate snapshot controllers were added.
- Ceph monitoring enabled, with ServiceMonitors, `prometheus-ceph-rules`,
  namespace monitoring label, and metrics RBAC for
  `openshift-monitoring/prometheus-k8s`.

RBD pool `replicapool` has `failureDomain: host`, replica `size: 1`,
`requireSafeReplicaSize: false`, and `compression_mode: none`. PG autoscaling
was left enabled. StorageClass `rook-ceph-block` uses:

- Provisioner `rook-ceph.rbd.csi.ceph.com`, `clusterID: rook-ceph`,
  `pool: replicapool`, image format 2, `imageFeatures: layering`, and ext4.
- `reclaimPolicy: Delete`, `allowVolumeExpansion: true`, and
  `volumeBindingMode: Immediate`.
- Provisioning and controller-expansion references to
  `rook-ceph/rook-csi-rbd-provisioner`; node-stage reference to
  `rook-ceph/rook-csi-rbd-node`. The expansion-reference checker passed.
- Non-default status: `lvms-vg1` remains the sole Kubernetes default.

VolumeSnapshotClass `rook-ceph-block-snapclass` uses the same RBD driver,
`clusterID: rook-ceph`, snapshotter reference
`rook-ceph/rook-csi-rbd-provisioner`, and `deletionPolicy: Delete`.
Tests selected this class explicitly. No CephFS filesystem, RGW store, or NFS
service was created; installed CSI Drivers alone do not provide those services.
Virtualization defaults were unchanged.

LVMS 4.18.6 remained Ready in `openshift-storage`, using the separate
512,110,190,592-byte disk. Its XFS class `lvms-vg1` uses `WaitForFirstConsumer`;
`vg1/thin-pool-1` is 90% of the VG (about 428.8 GiB) with
`overprovisionRatio: 1` and about 47.7 GiB reserve.

## AES256K kernel-RBD limitation

Initially `allowedCiphers: [aes256k]` and CSI `keyType: aes256k` were configured,
with daemon key type unset. The effective MonMap allowed only AES256K, all
25 keys in the full conventional/rotating audit were AES256K, and Ceph reported
`HEALTH_OK`.

The fresh RBD PVC became Bound and attached, but its consumer stayed
`ContainerCreating`. The node plugin failed at kernel mapping with:

```text
rbd: failed to add secret '<CSI-node-client>' to kernel
rbd: map failed: (524) Unknown error 524
```

No `/dev/rbd` mapping was created. This was not a provisioning failure,
image-pull failure, or the older librados `failed to decode key` failure.
The observation establishes that this exact OpenShift 4.18.44/kernel/CSI
combination could not use AES256K CSI keys with krbd; it does not establish that
all OpenShift 4.18 patches lack support or identify the first fixed kernel.
The later 4.18.56 success cited in [install preflight](install-and-preflight.md#ceph-version-and-ceph-csi-compatibility)
used a different kernel and CSI version. Re-run the live mount/write probe after
an update rather than inferring compatibility from the OpenShift minor version.

## Approved CSI-only fallback

After explicit approval, the deployment retained Ceph 20.2.5 and changed only
the relevant CephX policy and CSI rotation settings:

```yaml
security:
  cephx:
    allowedCiphers:
      - aes
      - aes256k
    csi:
      keyType: aes
      keyRotationPolicy: KeyGeneration
      keyGeneration: 2
      keepPriorKeyCountMax: 1
```

This records the generation used here, not the generation for another cluster:
discover the current value before any rotation. CSI status confirmed generation 2,
type `aes`, and one prior generation before the failed probe was cleaned up.
Daemon keys remained AES256K; no daemon key-type override was added. Rook rotated
both RBD and CephFS CSI identities, not daemon identities. The widened policy
permits classic AES cluster-wide even though only CSI keys were changed; do not
describe the policy as CSI-scoped. No downgrade or second disk wipe was needed.
Use the guarded rotation procedure in [install preflight](install-and-preflight.md).

## Validation and acceptance

- A fresh restricted consumer mounted `/dev/rbd0` and passed write/sync/read.
- `scripts/check_snapshot_smoke.py` passed the snapshot/source-mutation/
  new-PVC restore/token-comparison round trip for RBD filesystem mode.
  Raw-block mode and CephFS recovery were not tested.
- Both probe namespaces and their PVCs, PVs, snapshots, and snapshot contents
  were removed. Backend `rbd ls` and `rbd trash ls` were empty.
- All Rook pods were Ready or Completed, the OSD was up/in, and all 33 PGs were
  active+clean. MachineConfigPools stayed Updated and not Degraded.
- `lvms-vg1` remained the sole default and LVMS stayed Ready.

The final state is **HEALTH_WARN**, solely for the approved classic-AES exception:
`AUTH_INSECURE_CLIENT_KEY_TYPE` (four CSI identities),
`AUTH_INSECURE_KEYS_ALLOWED`, and `AUTH_INSECURE_KEYS_CREATABLE`. No warnings were
muted. The packaged strict `scripts/check_rook_health.py` correctly failed;
this is not a full HEALTH_OK acceptance pass.

A separate read-only observation lasting 122 seconds over nine samples allowed
only those three warning codes, required all 33 PGs active+clean and the single
OSD up/in, and found no new crash records. This was **warning-qualified
acceptance**, not a change to the strict checker or a default warning allowlist.
See [validation hardening](validation-hardening.md#sustained-post-install-acceptance).

RBD snapshots are supported, configured, and restore-tested for the filesystem
mode above; they are not scheduled. Recurring protection requires a workload,
retention, and consistency policy. No off-cluster backup was configured.
One node and one OSD provide no replication or failover; losing the Ceph disk
also loses its local snapshots.

## Version-selection sources

- [Rook v1.20 Kubernetes prerequisites](https://rook.io/docs/rook/v1.20/Getting-Started/Prerequisites/prerequisites/)
- [Rook v1.20.10 release notes](https://github.com/rook/rook/releases/tag/v1.20.10)
- [Pinned OpenShift operator manifest](https://raw.githubusercontent.com/rook/rook/v1.20.10/deploy/examples/operator-openshift.yaml)
- [Ceph Tentacle release notes](https://docs.ceph.com/en/latest/releases/tentacle/)
