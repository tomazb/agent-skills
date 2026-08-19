# Validated ODF SNO Scenario

This is observed evidence for OpenShift SNO / ODF scenarios across multiple versions. Do not turn these host-specific values into defaults without confirming the target cluster.

## Cluster Details

- OpenShift version: 4.16
- ODF version: 4.16
- Topology: Single Node OpenShift (SNO)
- Deployment mode: internal-attached (Local Storage Operator)
- Storage services: ceph-rbd, cephfs, MCG/RGW object

## Disk Layout

- One dedicated NVMe disk for OSD data (SNO has one node, one disk).
- The disk was selected through a `LocalVolumeSet` (`localblock`) filtering by device attributes, not by naming a raw `/dev/sdX` path.

## StorageCluster Configuration (SNO)

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  manageNodes: false
  monDataDirHostPath: /var/lib/rook
  storageDeviceSets:
  - name: ocs-deviceset
    count: 1
    replica: 1
    portable: false
    dataPVCTemplate:
      spec:
        accessModes:
        - ReadWriteOnce
        volumeMode: Block
        storageClassName: localblock
        resources:
          requests:
            storage: "1"
  managedResources:
    cephBlockPools:
      reconcileStrategy: manage
```

In this and the ODF 4.22 example below, `storage: "1"` is intentional for LSO `localblock` whole-disk Block PVs. It requests the smallest positive capacity so any matching disk-sized PV can bind; the OSD uses that PV's block device.

## Pool Configuration

- Block pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS metadata pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS data pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- RGW metadata pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- RGW data pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- Single mon and single mgr (reduced counts for one failure domain).

## StorageClasses

- `lvms-vg1` (from a pre-existing LVM Storage install) remained the cluster default StorageClass; ODF did not override it, so exactly one default StorageClass stayed in place.
- `ocs-storagecluster-ceph-rbd` (non-default RBD).
- `ocs-storagecluster-cephfs` (non-default CephFS).
- `ocs-storagecluster-ceph-rgw` (RGW ObjectBucketClaim provisioning).
- `openshift-storage.noobaa.io` (MCG ObjectBucketClaim provisioning).

## Validation Notes

- After install, the `StorageCluster` reached `Ready` and `ceph -s` showed `HEALTH_OK`.
- One OSD was created on the dedicated LSO-provisioned disk.
- Smoke tests for RBD and CephFS passed.
- An ObjectBucketClaim created the expected Secret and ConfigMap against the MCG StorageClass.
- ODF metrics appeared in the OpenShift console **Storage → Data Foundation** dashboards using the built-in cluster Prometheus.
- Post-reboot checks showed mon in quorum, OSD up, MDS active, and cluster health remained `HEALTH_OK`.

---

# ODF 4.20 SNO Scenario (OCP 4.20.32) — Regression Workarounds Required

This section documents observed evidence and workarounds for ODF 4.20 on SNO (OCP 4.20.32, node `prod2`). ODF 4.20 has several SNO-specific regressions; re-check ODF release notes and current documentation before applying these workarounds to other ODF releases.

## Cluster Details

- OpenShift version: 4.20.32
- ODF version: 4.20.16-rhodf (channel: `stable-4.20`)
- Topology: Single Node OpenShift (SNO) — `infrastructure.status.controlPlaneTopology: SingleReplica`
- Deployment mode: internal-attached (Local Storage Operator, `LocalVolume` resource for exact disk selection)
- Storage services: ceph-rbd block, cephfs shared filesystem, MCG/RGW object (all validated; see Validation Notes)
- Disk: one dedicated virtio block device (`/dev/disk/by-path/pci-0000:00:08.0`, ~500 GiB), raw (unpartitioned, no signatures)

## StorageCluster Configuration (ODF 4.20 SNO)

The StorageCluster below bakes in `flexibleScaling: true` and placement overrides that avoid the empty `topologyKey` regression **for `mon`, OSD, and OSD-prepare only** — those are the placements the manifest defines. MDS (`CephFilesystem`) and RGW (`CephObjectStore`) placements are emitted later by ocs-operator and still hit the same regression; fix them with the Regression 4 procedure below once CephFS and Object are enabled. Apply this manifest from the start — do not use the generic SNO manifest and add placements reactively.

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  manageNodes: false
  monDataDirHostPath: /var/lib/rook
  flexibleScaling: true
  managedResources:
    cephBlockPools:
      reconcileStrategy: manage
  placement:
    mon:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: rook-ceph-mon
  storageDeviceSets:
  - name: ocs-deviceset
    count: 1
    replica: 1
    portable: false
    dataPVCTemplate:
      spec:
        accessModes:
        - ReadWriteOnce
        volumeMode: Block
        storageClassName: localblock
        resources:
          requests:
            storage: "1"
    placement:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: rook-ceph-osd
    preparePlacement:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: rook-ceph-osd-prepare
```

`flexibleScaling: true` allows ODF to accept a single node (without it the StorageCluster reconciler rejects the CR with "Not enough nodes found: Expected 3, found 1").

Do **not** set `resourceProfile: lean` — in ODF 4.20 this traps the StorageCluster in `Progressing` indefinitely.

## ODF 4.20 Regression 1: `SINGLE_NODE=true` Not Auto-Set

ODF 4.20 does **not** auto-detect `controlPlaneTopology: SingleReplica` to set its internal `SINGLE_NODE` flag. Patch the `ocs-operator` CSV to inject it. **Patch the CSV, not the Deployment**; OLM reverts deployment-level env changes within seconds.

```bash
# Select exactly one ocs-operator CSV. Stop if zero or several match: patching
# the wrong CSV (or an old one left by a failed upgrade) silently does nothing.
# Anchored on "ocs-operator." so ocs-client-operator does not match.
mapfile -t OCS_CSVS < <(oc -n openshift-storage get csv \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | grep '^ocs-operator\.')
[ "${#OCS_CSVS[@]}" -eq 1 ] || { echo "expected 1 ocs-operator CSV, found ${#OCS_CSVS[@]}: ${OCS_CSVS[*]}" >&2; exit 1; }
OCS_CSV="csv/${OCS_CSVS[0]}"

# Confirm the flag is absent from that CSV before patching. Appending to the env
# array is not idempotent — a rerun would add a duplicate SINGLE_NODE entry.
if oc -n openshift-storage get "$OCS_CSV" \
     -o jsonpath='{.spec.install.spec.deployments[0].spec.template.spec.containers[0].env[*].name}' \
     | tr ' ' '\n' | grep -qx SINGLE_NODE; then
  echo "SINGLE_NODE already present in $OCS_CSV - nothing to patch" >&2
  exit 0
fi

# Append SINGLE_NODE=true to the ocs-operator CSV env array
oc -n openshift-storage patch "$OCS_CSV" \
  --type json \
  -p '[{"op":"add","path":"/spec/install/spec/deployments/0/spec/template/spec/containers/0/env/-","value":{"name":"SINGLE_NODE","value":"true"}}]'

# Verify after rollout
oc -n openshift-storage rollout status deploy/ocs-operator --timeout=3m
oc -n openshift-storage exec deploy/ocs-operator -- env | grep SINGLE_NODE
```

## ODF 4.20 Regression 2: Pool Sizes Not Reduced for SNO

In ODF 4.20, `getCephPoolReplicatedSize()` always returns `3` for SNO. All Ceph pools are created with `size=3, min_size=2` even with one OSD. In addition, the `CephBlockPool` is created with `failureDomain: osd` and `replicasPerFailureDomain: 1`, which causes Rook to reject `size=1` with a validation error ("size must be greater than replicasPerFailureDomain"). Both issues must be fixed.

**This is a version-scoped exception to the skill's "do not edit Rook CRs directly" rule.**

After the StorageCluster and CephCluster reach `Ready` (or you see Ceph OSDs are up):

```bash
# Step 1: Freeze ODF reconciliation for pools/object stores/filesystems.
# cephFilesystems must be frozen too, otherwise the CephFilesystem pool-size and
# topologyKey patches below (and in Regression 4) are reverted by ocs-operator.
oc -n openshift-storage patch storagecluster ocs-storagecluster --type merge -p '{
  "spec": {
    "managedResources": {
      "cephBlockPools":   {"reconcileStrategy": "ignore"},
      "cephObjectStores": {"reconcileStrategy": "ignore"},
      "cephFilesystems":  {"reconcileStrategy": "ignore"}
    }
  }
}'

# Step 2: Fix all pools via rook-ceph-operator
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"
for pool in $(oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF osd pool ls); do
  oc -n openshift-storage exec $ROOK_OP -- \
    ceph -c $CONF osd pool set "$pool" size 1 --yes-i-really-mean-it
  oc -n openshift-storage exec $ROOK_OP -- \
    ceph -c $CONF osd pool set "$pool" min_size 1
done

# Step 3: Set global config so future pools default to size=1
oc -n openshift-storage exec $ROOK_OP -- \
  ceph -c $CONF config set global osd_pool_default_size 1
oc -n openshift-storage exec $ROOK_OP -- \
  ceph -c $CONF config set global osd_pool_default_min_size 1
oc -n openshift-storage exec $ROOK_OP -- \
  ceph -c $CONF config set global mon_max_pg_per_osd 600

# Step 4 (ODF 4.20-specific): Fix CephBlockPool failureDomain and persist size=1
# Rook rejects size=1 with failureDomain=osd + replicasPerFailureDomain=1.
# Remove replicasPerFailureDomain and change failureDomain to host.
# Set size in the CR as well: `cephBlockPools: ignore` only stops ocs-operator
# from rewriting the CR — the Rook operator still reconciles it, so the live
# `ceph osd pool set ... size 1` from Step 2 is reverted to the CR's size (3)
# on the next reconcile unless the CR itself carries size 1.
oc -n openshift-storage patch cephblockpool ocs-storagecluster-cephblockpool \
  --type json \
  -p '[
    {"op":"replace","path":"/spec/failureDomain","value":"host"},
    {"op":"remove","path":"/spec/replicated/replicasPerFailureDomain"},
    {"op":"replace","path":"/spec/replicated/size","value":1},
    {"op":"add","path":"/spec/replicated/requireSafeReplicaSize","value":false}
  ]'

# Verify the CR (not just the live pool) carries the reduced size:
oc -n openshift-storage get cephblockpool ocs-storagecluster-cephblockpool \
  -o jsonpath='{.spec.replicated.size}{"\n"}'   # must print 1

# Step 5: Patch ODF-managed object store CR to size=1
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type merge \
  -p '{"spec":{"dataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}},"metadataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}}}}'

# Step 6: Archive crash history and mute expected SNO warning
oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF crash archive-all
oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF health mute POOL_NO_REDUNDANCY
```

Also apply the `rook-config-override` ConfigMap so that any future pools ODF creates default to size=1. This override and the `reconcileStrategy: ignore` values above are temporary — remove them after upgrading to a fixed release, per **Restoring Managed Reconciliation After Upgrade** at the end of this document:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rook-config-override
  namespace: openshift-storage
data:
  config: |
    [global]
    osd_pool_default_size = 1
    osd_pool_default_min_size = 1
    mon_max_pg_per_osd = 600
```

CephFilesystem and CephObjectStore pools need the same treatment as the block
pool: with one OSD, `size=3` + `replicasPerFailureDomain=1` fails Rook validation
("size must be greater than replicasPerFailureDomain"). After
`reconcileStrategy: ignore` is set for `cephFilesystems` and `cephObjectStores`,
patch their metadata and data pools:

```bash
# CephFilesystem: data + metadata pools -> size 1, host failure domain
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem \
  --type json -p '[
    {"op":"replace","path":"/spec/dataPools/0/failureDomain","value":"host"},
    {"op":"replace","path":"/spec/dataPools/0/replicated/size","value":1},
    {"op":"add","path":"/spec/dataPools/0/replicated/requireSafeReplicaSize","value":false},
    {"op":"remove","path":"/spec/dataPools/0/replicated/replicasPerFailureDomain"},
    {"op":"replace","path":"/spec/metadataPool/failureDomain","value":"host"},
    {"op":"replace","path":"/spec/metadataPool/replicated/size","value":1},
    {"op":"add","path":"/spec/metadataPool/replicated/requireSafeReplicaSize","value":false},
    {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}
  ]'

# CephObjectStore: data + metadata pools -> size 1, host failure domain
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type json -p '[
    {"op":"replace","path":"/spec/metadataPool/failureDomain","value":"host"},
    {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"},
    {"op":"replace","path":"/spec/dataPool/failureDomain","value":"host"},
    {"op":"remove","path":"/spec/dataPool/replicated/replicasPerFailureDomain"}
  ]'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type merge -p '{"spec":{"dataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}},"metadataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}}}}'
```

The `.mgr` pool is recreated at `size=3` whenever the mgr restarts. Re-check and
re-apply `size=1`/`min_size=1` on `.mgr` after any mgr restart:

```bash
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool set .mgr size 1 --yes-i-really-mean-it
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool set .mgr min_size 1
```

## ODF 4.20 Regression 3: CSI Controller Plugin Replicas

ODF 4.20 deploys 2 replicas of each CSI controller plugin with `requiredDuringSchedulingIgnoredDuringExecution` pod anti-affinity. On SNO the second replica can never schedule. In ODF 4.20, patching `OperatorConfig` alone is **not sufficient** — the `Driver` CRs (`drivers.csi.ceph.io`) control the replica count and must be patched directly.

```bash
# Reduce replicas to 1 on both CSI driver resources
oc -n openshift-storage patch drivers.csi.ceph.io/openshift-storage.rbd.csi.ceph.com \
  --type merge -p '{"spec":{"controllerPlugin":{"replicas":1}}}'
oc -n openshift-storage patch drivers.csi.ceph.io/openshift-storage.cephfs.csi.ceph.com \
  --type merge -p '{"spec":{"controllerPlugin":{"replicas":1}}}'
```

After patching, new ReplicaSets are created. Old pods from the previous ReplicaSet may still be running and will block the new pod (anti-affinity on same node). Delete the stale pods once the new ReplicaSet is current:

```bash
# Identify stale pods (from the old ReplicaSet) and delete them
# New RS pods will be Pending; old RS pods will be Running — delete the Running ones
oc -n openshift-storage get pods -l 'app=openshift-storage.rbd.csi.ceph.com-ctrlplugin' -o wide
oc -n openshift-storage delete pod <old-rbd-ctrlplugin-pod>
oc -n openshift-storage get pods -l 'app=openshift-storage.cephfs.csi.ceph.com-ctrlplugin' -o wide
oc -n openshift-storage delete pod <old-cephfs-ctrlplugin-pod>
```

Verify both new pods reach `Running 8/8`:

```bash
oc -n openshift-storage get pods -l 'app=openshift-storage.rbd.csi.ceph.com-ctrlplugin'
oc -n openshift-storage get pods -l 'app=openshift-storage.cephfs.csi.ceph.com-ctrlplugin'
```

## ODF 4.20 Regression 4: Empty `topologyKey` on MDS and RGW Placements

The empty-`topologyKey` regression is not limited to mon/OSD placement. On ODF
4.20 SNO, ocs-operator also sets `topologyKey: ""` with
`whenUnsatisfiable: DoNotSchedule` on:

- `CephFilesystem` `spec.metadataServer.placement.topologySpreadConstraints`
- `CephObjectStore` `spec.gateway.placement.topologySpreadConstraints`

**Symptom:** the `CephFilesystem` and/or `CephObjectStore` stay in `Failure`,
no `rook-ceph-mds-*` or `rook-ceph-rgw-*` pods appear, and `ceph fs ls` reports
"No filesystems enabled". The RBD and CephFS StorageClasses never get created
because the internal `StorageClient` cannot finish while these CRs are failed.

**Workaround** (with `cephFilesystems` / `cephObjectStores` reconciliation set to
`ignore`, patch the empty key to a valid one):

```bash
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem \
  --type json -p '[
    {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
    {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
  ]'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type json -p '[
    {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
    {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
  ]'
```

After both patch, the MDS and RGW pods schedule, the filesystem is created, and
(once onboarding completes) the `ocs-storagecluster-ceph-rbd` and
`ocs-storagecluster-cephfs` StorageClasses appear.

The deterministic patches in this section (Regression 3 + 4, plus
`reconcileStrategy: ignore` and the CephBlockPool failure-domain fix) can be
generated for review with:

```bash
python3 scripts/render_sno_remediation.py --release 4.20 \
  --name ocs-storagecluster --namespace openshift-storage
```

`--release` is mandatory and the emitted blocks differ per release: `4.20`
renders the CephBlockPool failure-domain fix, `4.22` renders the object/file
`replicasPerFailureDomain` removal and the resource-request floor instead.
Running the wrong release's script aborts on the first inapplicable patch.

If the internal `StorageClient` is stuck in `Initializing` with a
"crypto/rsa: verification error" after a reinstall, see the onboarding
troubleshooting entry in `references/validation-hardening.md`.

## Pool Configuration (ODF 4.20 SNO, after workaround)

- All pools (block, RGW, system): `replicated.size: 1`, `requireSafeReplicaSize: false`
- `CephBlockPool`: `failureDomain: host` (patched from `osd`), `replicasPerFailureDomain` removed
- 3 mons + 1 mgr (ODF 4.20 does not reduce mon count for SNO; all run on the single node)
- `POOL_NO_REDUNDANCY` warning is muted — expected for intentional single-replica SNO

## StorageClasses

- `ocs-storagecluster-ceph-rbd` (non-default RBD block)
- `ocs-storagecluster-cephfs` (non-default CephFS shared filesystem)
- `ocs-storagecluster-ceph-rgw` (RGW ObjectBucketClaim provisioning)
- `openshift-storage.noobaa.io` (MCG ObjectBucketClaim provisioning)

No ODF StorageClass became the default; pre-existing default(s) remained in place.

## Validation Notes (ODF 4.20 SNO)

- After applying the `SINGLE_NODE` patch, `flexibleScaling`, placement overrides, pool size workaround (including the `CephBlockPool` `failureDomain` fix), and CSI replica fix, the `StorageCluster` reached `Ready`.
- `ceph -s` showed `HEALTH_OK` (with `POOL_NO_REDUNDANCY` muted).
- 1 OSD on the dedicated disk; 3 mons in quorum; NooBaa writing data actively.
- ceph-rbd PVC provisioning, cephfs PVC provisioning, and MCG/RGW object storage validated. CephFS came up after the Regression 4 MDS `topologyKey` fix (MDS active + 1 hot standby, `ceph fs ls` healthy, a `ReadWriteMany` cephfs PVC bound).
- The `POOL_NO_REDUNDANCY` mute suppresses expected warning noise — it does not restore data redundancy. SNO ODF has no OSD redundancy by design.

---

# ODF 4.22 SNO Scenario (OCP 4.22.5) — Regression Workarounds Required

This section documents additional observed evidence and workarounds for ODF 4.22 on SNO. ODF 4.22 has several SNO-specific regressions relative to 4.16; re-check the release notes and current ODF documentation before applying these workarounds to other ODF releases.

## Cluster Details

- OpenShift version: 4.22.5
- ODF version: 4.22.0 (channel: `stable-4.22`)
- Topology: Single Node OpenShift (SNO) — `infrastructure.status.controlPlaneTopology: SingleReplica`
- Deployment mode: internal-attached (Local Storage Operator, `LocalVolume` resource for exact disk selection)
- Storage services: ceph-rbd, MCG/RGW object (CephFS validated separately on ODF 4.22.1 — see the 4.22 section below).

## Disk Layout

- One dedicated NVMe disk for OSD data selected with a `LocalVolume` CR (exact stable device path), because the node also ran Longhorn and LVMS on other disks that would have been accidentally matched by `LocalVolumeSet` attribute filters.
- The disk had a prior Ceph BlueStore OSD from an upstream Rook install. `wipefs -af` + `sgdisk --zap-all` did **not** remove the BlueStore superblock. Full-disk zeroing was required: see the wipe section in `references/local-storage-disks.md`.

## ODF 4.22 Regression: `SINGLE_NODE=true` Not Auto-Set

ODF 4.22 does **not** auto-detect `controlPlaneTopology: SingleReplica` to set its internal `SINGLE_NODE` flag. It must be injected manually via the `ocs-operator` CSV. **Patch the CSV, not the Deployment**; OLM reverts deployment-level env changes within seconds.

```bash
# Find current env array length (to append correctly)
oc -n openshift-storage get csv ocs-operator.v4.22.0-rhodf \
  -o jsonpath='{range .spec.install.spec.deployments[0].spec.template.spec.containers[0].env[*]}{.name}{"\n"}{end}'

# Append SINGLE_NODE=true to ocs-operator CSV env
oc -n openshift-storage patch csv ocs-operator.v4.22.0-rhodf \
  --type json \
  -p '[{"op":"add","path":"/spec/install/spec/deployments/0/spec/template/spec/containers/0/env/-","value":{"name":"SINGLE_NODE","value":"true"}}]'

# Verify it's running in the pod (after rollout)
oc -n openshift-storage exec deploy/ocs-operator -- env | grep SINGLE_NODE
```

## ODF 4.22 Regression: Empty `topologyKey` in Mon and OSD Placement

When `SINGLE_NODE=true`, ODF sets `failureDomain=osd`. In ODF 4.22, `GetKeyValues("osd")` returns an empty string (the `osd→kubernetes.io/hostname` mapping was missing; fixed in upstream commit `bdff547a` on 2026-06-12, after ODF 4.22 shipped). The empty `topologyKey` causes Kubernetes to reject the `rook-ceph-detect-version` job and the OSD prepare job.

**Workaround:** Override placements in the StorageCluster. Note that `spec.placement.osd` and `spec.placement.prepareosd` are **ignored** by ODF for OSD components — placement for OSDs must be set at the `storageDeviceSets[].placement` and `storageDeviceSets[].preparePlacement` level.

## StorageCluster Configuration (ODF 4.22 SNO)

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  manageNodes: false
  monDataDirHostPath: /var/lib/rook
  flexibleScaling: true
  managedResources:
    cephBlockPools:
      reconcileStrategy: manage
  placement:
    mon:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: rook-ceph-mon
  storageDeviceSets:
  - name: ocs-deviceset
    count: 1
    replica: 1
    portable: false
    dataPVCTemplate:
      spec:
        accessModes:
        - ReadWriteOnce
        volumeMode: Block
        storageClassName: localblock
        resources:
          requests:
            storage: "1"
    placement:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: rook-ceph-osd
    preparePlacement:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: rook-ceph-osd-prepare
```

Do **not** set `resourceProfile: lean` — in ODF 4.22 this traps the StorageCluster in `Progressing` indefinitely (the profile applicator never records completion).

## ODF 4.22 Regression: Pool Sizes Not Reduced for SNO

In ODF 4.22, `getCephPoolReplicatedSize()` has no `SINGLE_NODE` branch and always returns `3`. All Ceph pools are created with `size=3, min_size=2` even on SNO with one OSD. ODF continuously reverts manual pool size changes unless reconciliation is frozen.

**This is a version-scoped exception to the skill's "do not edit Rook CRs directly" rule.** For ODF 4.22 SNO only, due to this operator regression, direct pool and object-store CR patching is required after setting `reconcileStrategy: ignore`.

After the StorageCluster and CephCluster are Ready:

```bash
# Step 1: Freeze ODF reconciliation for pools/object stores (temporary 4.22 workaround)
# Side effects: ODF will not auto-repair drift for these resource classes until re-enabled.
# Remove these ignore strategies once ODF is upgraded to a version with the SNO pool fix.
oc -n openshift-storage patch storagecluster ocs-storagecluster --type merge -p '{
  "spec": {
    "managedResources": {
      "cephBlockPools":   {"reconcileStrategy": "ignore"},
      "cephObjectStores": {"reconcileStrategy": "ignore"},
      "cephFilesystems":  {"reconcileStrategy": "ignore"}
    }
  }
}'

# Step 2: Patch ODF-managed CRs to size=1
oc -n openshift-storage patch cephblockpool ocs-storagecluster-cephblockpool \
  --type merge \
  -p '{"spec":{"replicated":{"size":1,"requireSafeReplicaSize":false}}}'

oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type merge \
  -p '{"spec":{"dataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}},"metadataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}}}}'

oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem \
  --type merge \
  -p '{"spec":{"metadataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}},"dataPools":[{"name":"data0","replicated":{"size":1,"requireSafeReplicaSize":false}}]}}'

# Step 2b: In the SAME pass, remove replicasPerFailureDomain from the object and
# filesystem pools. On Ceph 20.2 "tentacle" (4.22.1) size=1 + replicasPerFailureDomain=1
# is rejected on these CRs ("size must be greater"), so RGW/MDS never start until
# the field is gone. See "replicasPerFailureDomain=1 + size=1 Rejected on Object/File
# Pools" below for the rationale.
#
# These are JSON-Patch 'remove' ops: run them once. A second run fails with a
# missing-target error once the fields are gone.
#
# The CephFilesystem patch assumes exactly ONE data pool (the validated SNO
# layout). Confirm before patching, and repeat the dataPools op per index if
# your filesystem has more:
oc -n openshift-storage get cephfilesystem ocs-storagecluster-cephfilesystem \
  -o jsonpath='{range .spec.dataPools[*]}{.name}{"\n"}{end}'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore --type json -p '[
  {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"},
  {"op":"remove","path":"/spec/dataPool/replicated/replicasPerFailureDomain"}
]'
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem --type json -p '[
  {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"},
  {"op":"remove","path":"/spec/dataPools/0/replicated/replicasPerFailureDomain"}
]'

# Step 3: Fix system pools (not managed by ODF CRs) via rook-ceph-operator
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"
for pool in $(oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF osd pool ls); do
  oc -n openshift-storage exec $ROOK_OP -- \
    ceph -c $CONF osd pool set "$pool" size 1 --yes-i-really-mean-it
  oc -n openshift-storage exec $ROOK_OP -- \
    ceph -c $CONF osd pool set "$pool" min_size 1
done

# Step 4: Set global config so future pools default to size=1
oc -n openshift-storage exec $ROOK_OP -- \
  ceph -c $CONF config set global osd_pool_default_size 1
oc -n openshift-storage exec $ROOK_OP -- \
  ceph -c $CONF config set global osd_pool_default_min_size 1
oc -n openshift-storage exec $ROOK_OP -- \
  ceph -c $CONF config set global mon_max_pg_per_osd 600

# Step 5: Archive crash history and mute expected SNO warning
oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF crash archive-all
# POOL_NO_REDUNDANCY is expected and intentional on SNO single-replica clusters
oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF health mute POOL_NO_REDUNDANCY
```

Also apply the `rook-config-override` ConfigMap so that any future pools ODF creates default to size=1. This override and the `reconcileStrategy: ignore` values above are temporary — remove them after upgrading to a fixed release, per **Restoring Managed Reconciliation After Upgrade** at the end of this document:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rook-config-override
  namespace: openshift-storage
data:
  config: |
    [global]
    osd_pool_default_size = 1
    osd_pool_default_min_size = 1
    mon_max_pg_per_osd = 600
```

## ODF 4.22 Regression: Empty `topologyKey` on MDS and RGW (CephFS + Object)

The mon/OSD empty-`topologyKey` fix (baked into the StorageCluster above) is not
sufficient once CephFS and Object are enabled. On ODF 4.22 SNO, ocs-operator
also emits `topologyKey: ""` + `whenUnsatisfiable: DoNotSchedule` on:

- `CephFilesystem` `spec.metadataServer.placement` — MDS never schedules, the
  `CephFilesystem` stays `Failure`.
- `CephObjectStore` `spec.gateway.placement` — no RGW pod is created, so NooBaa
  cannot create its object-store user and stays `Configuring`.

Freeze `cephFilesystems`/`cephObjectStores` (Step 1 above), then patch both:

```bash
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem --type json -p '[
  {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
  {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
]'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore --type json -p '[
  {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
  {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
]'
```

## ODF 4.22 Regression: `replicasPerFailureDomain=1` + `size=1` Rejected on Object/File Pools

On Ceph 20.2 "tentacle" (RHCEPH-9, shipped with ODF 4.22.1), the object and file
pool controllers reject a pool with `size: 1` while
`replicasPerFailureDomain: 1`:

```text
invalid metadata pool spec: error pool size is 1 and replicasPerFailureDomain is 1, size must be greater
```

`CephBlockPool` tolerates this combination, but `CephObjectStore` and
`CephFilesystem` do not — their reconcile fails and RGW/MDS never start. The fix
is to remove the field (keeping `size: 1`) after freezing reconciliation.

**The commands live in Step 2b of the Pool Sizes regression above — run them
there, once.** They are JSON-Patch `remove` operations, so a second run fails
with "missing target" once the field is gone. This section explains *why* the
step exists; it deliberately does not repeat the patches.

**Note on `.mgr`:** the `.mgr` pool reverts to `size=3` after *any* mgr restart
(including the restart triggered by applying resource requests below). Re-run the
`ceph osd pool set .mgr size 1 --yes-i-really-mean-it` / `min_size 1` step after
such restarts, then re-mute `POOL_NO_REDUNDANCY`.

## ODF 4.22 SNO: CPU-Request Starvation

ODF's default "balanced" resource **requests** (mon `1050m`; mds/osd/rgw
`2050m`; noobaa-core/endpoint `999m`) saturate a single node's schedulable CPU
(observed 99% requested vs ~6% actually used), leaving `noobaa-core` and the
second CSI replica `Pending` with `Insufficient cpu`. Do **not** set
`resourceProfile: lean` (it traps the StorageCluster in `Progressing` on 4.22).
Set minimal per-component requests instead; MDS/RGW are frozen CRs so patch them
directly:

```bash
oc -n openshift-storage patch storagecluster ocs-storagecluster --type merge -p '{
  "spec": {"resources": {
    "mon":             {"requests": {"cpu": "100m", "memory": "1Gi"}},
    "mgr":             {"requests": {"cpu": "100m", "memory": "1Gi"}},
    "noobaa-core":     {"requests": {"cpu": "100m", "memory": "1Gi"}},
    "noobaa-db":       {"requests": {"cpu": "100m", "memory": "512Mi"}},
    "noobaa-endpoint": {"requests": {"cpu": "100m", "memory": "512Mi"}}
  }}
}'
oc -n openshift-storage patch storagecluster ocs-storagecluster --type json -p '[
  {"op":"add","path":"/spec/storageDeviceSets/0/resources","value":{"requests":{"cpu":"100m","memory":"2Gi"},"limits":{"cpu":"2","memory":"5Gi"}}}
]'
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem --type merge \
  -p '{"spec":{"metadataServer":{"resources":{"requests":{"cpu":"100m","memory":"1Gi"},"limits":{"cpu":"2","memory":"4Gi"}}}}}'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore --type merge \
  -p '{"spec":{"gateway":{"resources":{"requests":{"cpu":"100m","memory":"1Gi"},"limits":{"cpu":"2","memory":"4Gi"}}}}}'
```

This dropped observed CPU requests from 99% to ~35% and let all components schedule.

**After this resource patch:** the mgr restarts, which reverts the `.mgr` pool to
`size=3`. Re-run the fix and re-mute before proceeding:

```bash
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"
oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF osd pool set .mgr size 1 --yes-i-really-mean-it
oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF osd pool set .mgr min_size 1
oc -n openshift-storage exec $ROOK_OP -- ceph -c $CONF health mute POOL_NO_REDUNDANCY
```

## CSI Controller Plugin Replicas on SNO

ODF deploys 2 replicas of each CSI controller plugin for HA. On SNO the second
replica can never schedule (pod anti-affinity), and it also wastes scarce CPU
requests. Patching `operatorconfigs.csi.ceph.io` alone is **reverted** by
ocs-client-operator on 4.22.1 — patch the per-driver `drivers.csi.ceph.io` CRs
instead (this sticks):

```bash
oc -n openshift-storage patch drivers.csi.ceph.io openshift-storage.rbd.csi.ceph.com \
  --type merge -p '{"spec":{"controllerPlugin":{"replicas":1}}}'
oc -n openshift-storage patch drivers.csi.ceph.io openshift-storage.cephfs.csi.ceph.com \
  --type merge -p '{"spec":{"controllerPlugin":{"replicas":1}}}'
```

## Pool Configuration (ODF 4.22 SNO, after workaround)

- All pools (block, RGW, system): `replicated.size: 1`, `requireSafeReplicaSize: false`
- 3 mons + 1 mgr (ODF 4.22 does not reduce mon count for SNO; all run on the single node with `allowMultiplePerNode: true`)
- `POOL_NO_REDUNDANCY` warning is muted — expected for intentional single-replica SNO

## StorageClasses

- `lvms-vg1` (pre-existing LVMS) remained the sole default; ODF did not override it.
- `ocs-storagecluster-ceph-rbd` (non-default RBD)
- `ocs-storagecluster-ceph-rgw` (RGW ObjectBucketClaim provisioning)
- `openshift-storage.noobaa.io` (MCG ObjectBucketClaim provisioning)

## Validation Notes (ODF 4.22 SNO)

The deterministic 4.22 patches (reconcile freeze, MDS/RGW `topologyKey`, the
object/file `replicasPerFailureDomain` removal, CSI `Driver` replicas, and the
resource-request floor) can be generated for review with:

```bash
python3 scripts/render_sno_remediation.py --release 4.22 \
  --name ocs-storagecluster --namespace openshift-storage
```

Pool sizing and the `POOL_NO_REDUNDANCY` mute are not emitted as commands —
apply them from the Pool Sizes regression section above.

- After applying the SINGLE_NODE patch, placement overrides, pool size workaround, and CSI replica fix, the `StorageCluster` reached `Ready`.
- `ceph -s` showed `HEALTH_OK` (with `POOL_NO_REDUNDANCY` muted).
- One OSD on the dedicated NVMe disk; NooBaa writing data actively.
- RBD (RWO), CephFS (RWX), and MCG/RGW object (OBC) all validated on ODF 4.22.1: a `ReadWriteOnce` rbd PVC and a `ReadWriteMany` cephfs PVC bound and a pod wrote to both; an `ObjectBucketClaim` bound. MDS ran active + 1 hot standby; `CephFilesystem` Ready.
- Applying minimal resource requests dropped node CPU requests from 99% to ~35%.
- ODF console plugin enabled and visible in OpenShift console **Storage → Data Foundation**.
- The `POOL_NO_REDUNDANCY` mute suppresses expected warning noise — it does not restore data redundancy. SNO ODF has no OSD redundancy by design.

## Restoring Managed Reconciliation After Upgrade

Every workaround above is **temporary and version-scoped**. Both the 4.20 and
4.22 procedures leave three `reconcileStrategy: ignore` values and a persistent
`rook-config-override` ConfigMap in place. While they stand, ocs-operator stops
reconciling the pool, object-store, and filesystem CRs entirely: later
`StorageCluster` changes are silently not propagated, and pools created after
an upgrade keep inheriting the override defaults.

After upgrading to an ODF release that fixes the single-OSD pool sizing, undo
them in this order and confirm the cluster stays healthy at each step.

```bash
# 1. Confirm the new release no longer needs the workaround: on a fixed
#    release ocs-operator creates pools at size=1 on SNO by itself. Check the
#    running ODF version first.
oc -n openshift-storage get csv -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | grep '^ocs-operator\.'

# 2. Remove the global size defaults, then restart the operator so the override
#    is re-read. Keep mon_max_pg_per_osd only if the PG count still needs it.
oc -n openshift-storage delete configmap rook-config-override
oc -n openshift-storage rollout restart deploy/rook-ceph-operator

# 3. Hand the CRs back to ocs-operator.
oc -n openshift-storage patch storagecluster ocs-storagecluster --type merge -p '{
  "spec": {
    "managedResources": {
      "cephBlockPools":   {"reconcileStrategy": "manage"},
      "cephObjectStores": {"reconcileStrategy": "manage"},
      "cephFilesystems":  {"reconcileStrategy": "manage"}
    }
  }
}'

# 4. Watch what ocs-operator does to the pool specs it now owns again. On a
#    still-affected release it pushes size back to 3 on a single OSD, which
#    leaves the pools undersized and degraded — revert to 'ignore' if so.
oc -n openshift-storage get cephblockpool,cephfilesystem,cephobjectstore \
  -o custom-columns='KIND:.kind,NAME:.metadata.name,SIZE:.spec.replicated.size'
oc -n openshift-storage get storagecluster ocs-storagecluster \
  -o jsonpath='{.status.phase}{"\n"}'
```

If step 4 shows the pools being pushed back to `size: 3`, the release still has
the regression: restore `reconcileStrategy: ignore`, re-apply the pool sizing,
and keep the override in place until a later upgrade.

The manual MDS/RGW `topologyKey` and CSI `Driver` replica patches are reverted
automatically once reconciliation is handed back, so re-check that MDS, RGW,
and the CSI controller pods are still scheduled after step 3.
