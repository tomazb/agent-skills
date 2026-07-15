# Validated ODF SNO Scenario

This is observed evidence for one OpenShift SNO / ODF scenario. Do not turn these host-specific values into defaults without confirming the target cluster.

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

# ODF 4.22 SNO Scenario (OCP 4.22.5) — Regression Workarounds Required

This section documents additional observed evidence and workarounds for ODF 4.22 on SNO. ODF 4.22 has several SNO-specific regressions relative to 4.16; re-check the release notes and current ODF documentation before applying these workarounds to other ODF releases.

## Cluster Details

- OpenShift version: 4.22.5
- ODF version: 4.22.0 (channel: `stable-4.22`)
- Topology: Single Node OpenShift (SNO) — `infrastructure.status.controlPlaneTopology: SingleReplica`
- Deployment mode: internal-attached (Local Storage Operator, `LocalVolume` resource for exact disk selection)
- Storage services: ceph-rbd, MCG/RGW object (**CephFS not validated in this scenario**)

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
      "cephObjectStores": {"reconcileStrategy": "ignore"}
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

Also apply the `rook-config-override` ConfigMap so that any future pools ODF creates default to size=1:

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

## CSI Controller Plugin Replicas on SNO

ODF deploys 2 replicas of each CSI controller plugin for HA. On SNO the second replica can never schedule (pod anti-affinity). Reduce to 1 replica via the `OperatorConfig` CR:

```bash
oc -n openshift-storage patch operatorconfigs.csi.ceph.io ceph-csi-operator-config \
  --type merge \
  -p '{"spec":{"driverSpecDefaults":{"controllerPlugin":{"replicas":1}}}}'
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

- After applying the SINGLE_NODE patch, placement overrides, pool size workaround, and CSI replica fix, the `StorageCluster` reached `Ready`.
- `ceph -s` showed `HEALTH_OK` (with `POOL_NO_REDUNDANCY` muted).
- One OSD on the dedicated NVMe disk; NooBaa writing data actively.
- RBD and MCG/RGW object validated. **CephFS not validated in this scenario.**
- ODF console plugin enabled and visible in OpenShift console **Storage → Data Foundation**.
- The `POOL_NO_REDUNDANCY` mute suppresses expected warning noise — it does not restore data redundancy. SNO ODF has no OSD redundancy by design.
