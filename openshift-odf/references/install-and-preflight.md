# Install And Preflight

Use this runbook for discovery, installation planning, OpenShift/OKD prerequisites, and first OpenShift Data Foundation (ODF) deployment.

ODF is installed through Operator Lifecycle Manager (OLM), not through raw upstream Rook manifests. The ODF operator manages the `ocs-operator`, `rook-ceph-operator`, `mcg-operator`, and CSI drivers for you in the `openshift-storage` namespace.

## Live Discovery

Collect current state before choosing a path:

```bash
oc version
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc get infrastructure cluster -o jsonpath='{.status.controlPlaneTopology}{"\n"}'
oc get ns openshift-storage || true
oc -n openshift-storage get subscription,csv,pods 2>/dev/null || true
oc -n openshift-storage get storagecluster,cephcluster 2>/dev/null || true
oc -n openshift-storage get storagesystem 2>/dev/null || true
```

Also discover leftovers from a previous lifecycle before reinstalling:

```bash
oc api-resources --api-group=ocs.openshift.io
oc api-resources --api-group=ceph.rook.io
oc get sc
oc get pv,pvc -A -o wide
oc get localvolumeset,localvolumediscovery -A 2>/dev/null || true
```

### Leftover Install Detection (ODF or Rook)

A prior **ODF** uninstall and a prior upstream **Rook** uninstall leave the same Ceph/Rook byproducts. Detect uncleaned state from **either** product before installing — a stale mon store or an OSD disk that still carries a BlueStore label makes the fresh mon crash and makes OSD prepare skip the disk (`Has BlueStore device label`). Do not treat namespace or CRD presence alone as ownership; classify with the Product Ownership Gate first.

```bash
# Cluster-scoped/namespaced leftovers from ODF or Rook (survive a namespace delete):
oc get ns openshift-storage rook-ceph 2>/dev/null || true
oc get crd | grep -E 'ceph\.rook\.io|ocs\.openshift\.io|csi\.ceph\.io|noobaa\.io' || echo "no rook/odf CRDs"
oc get sc | grep -E 'ocs-storagecluster|rook-ceph|ceph\.rook\.io|csi\.ceph\.com|noobaa' || echo "no leftover StorageClasses"
oc get csidriver | grep -E 'openshift-storage|rook-ceph|ceph\.com' || echo "no leftover Ceph CSIDrivers"
oc get scc | grep -E 'rook-ceph|noobaa' || echo "no leftover Ceph SCCs"
# Node-level leftovers on every candidate storage node:
NODE="<node>"
DISKS="/dev/disk/by-id/<osd-disk-id>"   # edit: space-separated candidate OSD disk(s) by stable path
oc debug "node/${NODE}" -- chroot /host bash -c '
  for p in /var/lib/rook/mon-* /var/lib/rook/openshift-storage; do [ -e "$p" ] && echo "stale dir: $p"; done
  # lsblk -f shows FSTYPE "ceph_bluestore" for a raw BlueStore label.
  for d in '"$DISKS"'; do lsblk -f "$d"; done
  # stale krbd device mappings leaked by a prior teardown (NooBaa DB and app PVCs use ceph-rbd):
  ls /dev/rbd[0-9]* 2>/dev/null && echo "STALE krbd present" || echo "no /dev/rbd[0-9]* devices"
  for r in /sys/bus/rbd/devices/*; do [ -e "$r" ] && echo "rbd $(basename $r): pool=$(cat $r/pool 2>/dev/null) image=$(cat $r/name 2>/dev/null)"; done'

# RHCOS does not ship ceph-volume. Run the LVM residue audit from a node-local helper
# container that carries it and bind the host device/LVM paths into that container.
# If this command fails, fail closed and do not reuse the disk.
CEPH_VOLUME_IMAGE="quay.io/ceph/ceph:v19.2.2"   # replace with the Ceph image shipped by your ODF release
oc debug "node/${NODE}" --image="${CEPH_VOLUME_IMAGE}" -- bash -ceu '
  mkdir -p /run/lvm /etc/lvm
  mount --rbind /host/dev /dev
  mount --rbind /host/run/lvm /run/lvm
  mount --rbind /host/etc/lvm /etc/lvm
  for d in '"$DISKS"'; do ceph-volume lvm list "$d"; done
' || { echo "LVM residue audit failed; do not reuse the disk" >&2; exit 1; }
```

**Watch for stale krbd devices.** If a prior ODF/Rook teardown deleted an RBD-backed PVC (ODF's NooBaa DB and any `ceph-rbd` PVC) or its namespace before the volume was unmapped — or destroyed the pool under a mapped image — the node keeps a wedged `/dev/rbdN` pointing at a pool that no longer exists. A later OSD prepare then hangs forever at `ceph-volume raw list`. Remediation is node-local (run it inside `oc debug node/<node> -- chroot /host`): a forced unmap `timeout 30 rbd device unmap --force /dev/rbdN` (or the `/sys/bus/rbd/remove*` sysfs write when the `rbd` client is unavailable on the host), escalating to a node reboot or hypervisor power-cycle when the mapping is fully wedged. See the Rook cleanup runbook's "Stale krbd Devices" section for the exact commands.

Remove any leftover before installing: hand off ODF-owned leftovers to this skill's `maintenance-uninstall.md`, and upstream-Rook leftovers to the [Rook cleanup runbook](../../openshift-rook/references/maintenance-uninstall.md). Clearing orphaned StorageClasses/CSIDrivers, stuck `clientprofiles.csi.ceph.io` finalizers, the `dataDirHostPath` (`/var/lib/rook`), and stale krbd mappings is required in both cases. **Full-disk BlueStore zeroing is destructive and is only appropriate once ownership is classified, the operator has confirmed the disk is not a recovery candidate, and destructive confirmation is given for the exact device** — see the Disk Cleanup gate in `references/local-storage-disks.md`.

### Upstream Rook Conflict Check (SNO / Bare-Metal)

Before installing ODF on a node that has ever run a storage system, check for an upstream (non-OLM) Rook cluster:

```bash
oc get ns | grep rook
oc get crd | grep ceph.rook.io
oc get subscription -A | grep -E 'rook|ceph|odf|ocs' || echo "no relevant OLM subscriptions"
```

**If an upstream Rook cluster is found with no OLM Subscription**, it is an incompatible non-ODF Rook installation. ODF cannot be installed alongside it — both operators fight over the same CRDs and block device assignments. You must remove the upstream Rook cluster first using the repository's [Rook cleanup runbook](../../openshift-rook/references/maintenance-uninstall.md), not this ODF `maintenance-uninstall.md` runbook. Then verify:

1. All stale Rook namespaces, CRs, CRDs, and StorageClasses are deleted.
2. Stale mon host directories (`/var/lib/rook/mon-*/`) are removed from the node **only after confirming the cluster is fully abandoned** (not a recovery candidate). If there is any chance the data is needed, treat the host path as a backup candidate before deletion.
3. Any OSD disk that was used by the upstream Rook cluster has been fully zeroed — see the Disk Cleanup section in `references/local-storage-disks.md`.

## SNO Pre-flight Gate

If the Live Discovery returned `controlPlaneTopology: SingleReplica` (SNO) **and** the target ODF channel is `stable-4.20` or `stable-4.22`, **stop here**.

Both ODF 4.20 and 4.22 have known SNO-specific regressions (`SINGLE_NODE` auto-detection missing, empty `topologyKey` in mon/OSD placement, pool sizes not reduced for a single-OSD cluster, CSI controller anti-affinity). Following the generic install path below will hit these regressions reactively. Instead, follow the complete validated procedure for your version in **`references/validated-odf-sno.md`**:

- ODF 4.20 SNO → see the **ODF 4.20 SNO Scenario** section
- ODF 4.22 SNO → see the **ODF 4.22 SNO Scenario** section

For ODF versions on SNO that are not listed in `validated-odf-sno.md`, continue with the generic install path and record any new regressions encountered.

## Sizing And Prerequisites

- **Node count and failure domains.** Internal-mode production needs at least three OSD nodes spread across three failure domains (host, rack, or zone). Compact 3-node and SNO clusters are supported but are topology constraints, not high availability.
- **Resources.** Each ODF/OSD node needs reserved CPU and memory for Ceph daemons. Verify the current ODF documentation for the CPU/memory requirements of the target release before committing node sizing.
- **Storage nodes.** Label the nodes that will run ODF so the operator schedules OSDs, mons, and mgrs on them:

```bash
oc label node <node-1> cluster.ocs.openshift.io/openshift-storage='' --overwrite
oc label node <node-2> cluster.ocs.openshift.io/openshift-storage='' --overwrite
oc label node <node-3> cluster.ocs.openshift.io/openshift-storage='' --overwrite
```

- **Deployment mode.** Choose one:
  - *Internal* — ODF creates OSDs on dynamically provisioned PVs from an existing StorageClass (typical on cloud).
  - *Internal-attached (local devices)* — ODF creates OSDs on local disks discovered by the Local Storage Operator (typical on bare metal, SNO, and on-prem). See `references/local-storage-disks.md`.
  - *External* — ODF connects to an existing external Ceph cluster; no local OSDs are created.

## Security Context Constraints

ODF ships and binds its own SecurityContextConstraints through the operator bundle (for example `rook-ceph`, `rook-ceph-csi`, and the NooBaa endpoint SCCs). Do not grant the broad built-in `privileged` SCC to service accounts by hand — the OLM install wires the scoped SCCs for you. Confirm they exist after install:

```bash
oc get scc | grep -E 'rook-ceph|noobaa' || true
```

If a custom install requires a manual grant, scope it to the exact ODF service account rather than a wildcard, and record why the exception is needed.

## Install The Operator (OLM)

### Namespace and OperatorGroup

Create the `openshift-storage` namespace with the required monitoring label, then an OperatorGroup:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: openshift-storage
  labels:
    openshift.io/cluster-monitoring: "true"
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-storage-operatorgroup
  namespace: openshift-storage
spec:
  targetNamespaces:
  - openshift-storage
```

### Subscription

Subscribe to the ODF operator on a pinned channel. Discover the available channel from the PackageManifest instead of assuming one:

```bash
oc get packagemanifest odf-operator -n openshift-marketplace \
  -o jsonpath='{.status.channels[*].name}{"\n"}'
```

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: odf-operator
  namespace: openshift-storage
spec:
  channel: <stable-x.y>
  name: odf-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

Use `installPlanApproval: Manual` when you want to gate upgrades explicitly (see `references/upgrade.md`).

Apply and wait for the CSV to reach `Succeeded`:

```bash
oc apply -f /tmp/odf-namespace-operatorgroup.yaml
oc apply -f /tmp/odf-subscription.yaml
oc -n openshift-storage get csv -w
oc -n openshift-storage wait csv -l operators.coreos.com/odf-operator.openshift-storage \
  --for=jsonpath='{.status.phase}'=Succeeded --timeout=15m
```

## Create The StorageCluster

The `StorageCluster` CR is the single source of truth for an ODF internal deployment. `ocs-operator` reconciles the Rook `CephCluster`, pools, filesystem, object store, and NooBaa system from it. Do not create or edit those Rook CRs directly.

Prefer the packaged helper when generating a starting `StorageCluster` manifest, then review and adjust topology-specific fields before apply:

```bash
python3 scripts/render_storagecluster.py \
  --name ocs-storagecluster \
  --namespace openshift-storage \
  --local-storage-class localblock \
  --replica 3 \
  --count 1 \
  --output /tmp/ocs-storagecluster.yaml

oc apply --dry-run=server -f /tmp/ocs-storagecluster.yaml
```

Use `--replica 1` only for confirmed SNO single-replica deployments. Do not treat helper defaults as the production topology without live discovery. After reviewing live topology and editing the rendered manifest as needed, apply:

```bash
oc apply -f /tmp/ocs-storagecluster.yaml
```

### Multi-Node Production (local devices)

Reference a Local Storage Operator StorageClass (for example `localblock`) created per `references/local-storage-disks.md`:

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
    replica: 3
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
```

`replica: 3` places one OSD per failure domain; `count` is the number of device sets (increase `count` to add capacity in units of three OSDs). Do not lower `replica` below 3 for multi-node production without explicit direction.

`storage: "1"` is intentional with LSO `localblock` whole-disk Block PVs: it requests the smallest positive capacity so any matching disk-sized PV can bind, and the OSD receives that PV's block device. Keep the request no larger than the LSO PV capacity.

### SNO / Compact Single-Replica

On SNO, run a single-replica device set and let ODF reduce mon/mgr and pool resiliency for a single failure domain:

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  manageNodes: false
  monDataDirHostPath: /var/lib/rook
  resources: {}
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

Do not copy `replica: 1` into multi-node production plans without explicit direction. On a single OSD, ODF may need a higher `mon_max_pg_per_osd` ceiling once rbd, cephfs, and RGW pools coexist; raise it deliberately through the documented `StorageCluster` override and record why.

**ODF 4.20 and 4.22 SNO — additional required steps:** ODF 4.20 and 4.22 have known SNO regressions (missing `SINGLE_NODE` auto-detection, empty `topologyKey` bug, pool sizes not reduced for single-OSD). If deploying ODF 4.20 or 4.22 on SNO, follow the complete procedure documented in `references/validated-odf-sno.md` for the matching version before considering the StorageCluster ready. The steps in those sections are version-specific regressions, not general SNO guidance. Re-check ODF release notes when using any other version.

## Install Validation

Wait for the operator and StorageCluster to reach a healthy state:

```bash
oc -n openshift-storage rollout status deploy/rook-ceph-operator --timeout=10m
oc -n openshift-storage wait storagecluster/ocs-storagecluster \
  --for=jsonpath='{.status.phase}'=Ready --timeout=20m
oc -n openshift-storage get storagecluster,cephcluster -o wide
oc -n openshift-storage get pods -o wide
```

Check Ceph cluster health via the toolbox (enable it first):

```bash
oc patch OCSInitialization ocsinit -n openshift-storage --type merge \
  -p '{"spec":{"enableCephTools":true}}'
oc -n openshift-storage rollout status deploy/rook-ceph-tools --timeout=5m
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph health detail
```

> **Some builds reject `spec.enableCephTools`** (observed on `ocs-operator.v4.20.17-rhodf`, which returns `Warning: unknown field "spec.enableCephTools"`). The `rook-ceph-tools` Deployment then never appears and the `rollout status` above times out after 5m. If you hit that, skip the toolbox and run Ceph commands through the rook-operator pod with the cluster config instead (see `references/validated-odf-sno.md`, "ODF 4.20.17 Fresh-Install Observations"):
>
> ```bash
> ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
> CONF=/var/lib/rook/openshift-storage/openshift-storage.config
> oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" -s
> ```

Before declaring success, verify:

- All mons are in quorum.
- All OSDs are `up` and `in`.
- Ceph cluster health is `HEALTH_OK` or `HEALTH_WARN` with known, documented warnings.
- No PGs are stuck in `creating`, `degraded`, or `peering`.
- The default ODF StorageClasses exist (`ocs-storagecluster-ceph-rbd`, `ocs-storagecluster-cephfs`, and `ocs-storagecluster-ceph-rgw` if RGW is enabled).
- Exactly one default StorageClass exists when defaulting is expected.

## MachineConfig Discipline

MachineConfig changes can reboot nodes. On SNO, warn that API access can disappear until the single node returns. Apply one purpose per MachineConfig, wait for MCP recovery, then verify host state:

```bash
oc apply -f <machineconfig.yaml>
oc wait mcp/<pool> --for=condition=Updated=True --timeout=45m
oc get mcp <pool> -o wide
oc get nodes
```

If the MCP degrades, stop mutating and inspect:

```bash
oc describe mcp/<pool>
oc -n openshift-machine-config-operator get pods -o wide
oc -n openshift-machine-config-operator logs <machine-config-daemon-pod> -c machine-config-daemon
```
