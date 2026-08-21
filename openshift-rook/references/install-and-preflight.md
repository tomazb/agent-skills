# Install And Preflight

Use this runbook for discovery, installation planning, OpenShift/OKD prerequisites, and first Rook Ceph deployment.

## Live Discovery

Collect current state before choosing a path:

```bash
oc version
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc get ns rook-ceph || true
oc -n rook-ceph get pods,cephclusters.ceph.rook.io,cephblockpools.ceph.rook.io,cephfilesystems.ceph.rook.io,cephobjectstores.ceph.rook.io 2>/dev/null || true
```

## Leftover Install Detection (Rook or ODF)

Before any fresh install, detect uncleaned state from a previous Rook **or** ODF lifecycle. A prior ODF install ships the same Rook/Ceph components under different names, so check for **both** products — a stale mon store or an OSD disk that still carries a BlueStore label will make a fresh mon crash (SIGABRT) and make OSD prepare skip the disk (`Has BlueStore device label`). Namespace or CRD presence alone is not proof of ownership — classify with the Product Ownership Gate first.

Cluster-scoped and namespaced leftovers (survive a namespace delete and must be removed by name):

```bash
# Prior Rook AND prior ODF footprints
oc get ns rook-ceph openshift-storage 2>/dev/null || true
for g in ceph.rook.io ocs.openshift.io csi.ceph.io noobaa.io; do oc api-resources --api-group="$g" 2>/dev/null; done  # one --api-group per call; the flag is not repeatable
oc get crd | grep -E 'ceph\.rook\.io|ocs\.openshift\.io|csi\.ceph\.io|noobaa\.io' || echo "no rook/odf CRDs"
oc get storagecluster -A 2>/dev/null || true         # ODF ownership signal
oc get subscription,csv -A 2>/dev/null | grep -Ei 'rook|ocs|odf|mcg|cephcsi' || echo "no rook/odf OLM operators"
# Orphaned cluster-scoped objects that block a clean reinstall:
oc get sc | grep -E 'rook-ceph|ocs-storagecluster|ceph\.rook\.io|csi\.ceph\.com|noobaa' || echo "no leftover StorageClasses"
oc get csidriver | grep -E 'rook-ceph|ceph\.com' || echo "no leftover Ceph CSIDrivers"
oc get scc | grep -E 'rook-ceph|noobaa' || echo "no leftover Ceph SCCs"
oc get machineconfig | grep -iE 'rook|ocs|odf' || true
oc get pv,pvc -A -o wide 2>/dev/null | grep -E 'rook-ceph|ocs-storagecluster' || echo "no leftover PV/PVC"
```

Node-level leftovers on every candidate storage node (the most common cause of a failed reinstall):

```bash
NODE="<node>"
oc debug "node/${NODE}" -- chroot /host bash -c '
  DISKS="/dev/disk/by-id/<osd-disk-id>"   # edit: space-separated candidate OSD disk(s) by stable path
  echo "== stale mon/OSD dataDirHostPath =="
  if [ ! -d /var/lib/rook ]; then echo "/var/lib/rook absent (clean)"
  else n=$(ls -A /var/lib/rook | wc -l); [ "$n" -eq 0 ] && echo "/var/lib/rook present but empty" || { echo "STALE ($n entries):"; ls -A /var/lib/rook; }; fi
  for p in /var/lib/rook/mon-* /var/lib/rook/openshift-storage; do [ -e "$p" ] && echo "stale dir: $p"; done
  echo "== OSD disk still carries a BlueStore label? =="
  # lsblk -f shows FSTYPE "ceph_bluestore" for a raw BlueStore label; ceph-volume lvm list only covers LVM-backed OSDs.
  for d in $DISKS; do lsblk -f "$d"; ceph-volume lvm list "$d" 2>/dev/null || true; done
  echo "== stale krbd device mappings (leaked by a prior teardown)? =="
  ls /dev/rbd[0-9]* 2>/dev/null && echo "STALE krbd present" || echo "no /dev/rbd[0-9]* devices"
  for r in /sys/bus/rbd/devices/*; do [ -e "$r" ] && echo "rbd $(basename $r): pool=$(cat $r/pool 2>/dev/null) image=$(cat $r/name 2>/dev/null)"; done
'
```

**Stale krbd devices are a silent killer.** If a prior Rook/ODF teardown deleted an RBD-backed PVC (or its whole namespace) *before* the volume was unmapped, or deleted the Ceph pool out from under a mapped image, the node keeps a wedged `/dev/rbdN` device pointing at a pool that no longer exists. A fresh Rook OSD prepare then hangs **forever** at `ceph-volume raw list` (it probes every block device, including the dead `/dev/rbdN`). The device cannot be force-removed from userspace — `/sys/bus/rbd/remove*` blocks uninterruptibly, and it can even wedge a node shutdown. Clear it before installing (see `maintenance-uninstall.md`, "Stale krbd Devices"); a wedged device may require a node reboot or hypervisor power-cycle.

If any of these exist and the target node is not running an intended storage system, remove them before installing — follow `maintenance-uninstall.md` (orphaned StorageClasses/CSIDrivers, stuck `clientprofiles.csi.ceph.io` finalizers, `/var/lib/rook` clearing, stale krbd unmap, and full-disk BlueStore zeroing). A Rook cleanup handoff is required when the leftover is upstream Rook; an ODF cleanup handoff (`openshift-odf`) is required when the leftover is ODF-owned. Only after the leftover audit is clean should you proceed.

## Ceph Version And ceph-csi Compatibility

Pin the `CephCluster` `cephVersion.image` to a Ceph release whose cephx key cipher the deployed **ceph-csi** can decode. Discover the ceph-csi build Rook will deploy and match it — do not blindly accept the newest `quay.io/ceph/ceph` tag from the upstream `cluster.yaml`.

**Discover the ceph-csi version *before* creating the CephCluster** — the running CSI Deployment does not exist yet on a fresh install. Read the pinned image from the operator's CSI image-set instead of a live pod:

```bash
# Pre-install: the ceph-csi image Rook will deploy is pinned in the operator config.
# For the OLM/csi-operator path it is the rook-csi-operator-image-set-configmap; for a
# manifest install grep the operator manifest you are about to apply.
oc -n rook-ceph get cm rook-csi-operator-image-set-configmap -o jsonpath='{.data.plugin}{"\n"}' 2>/dev/null \
  || grep -E 'cephcsi/cephcsi:|ROOK_CSI_CEPH_IMAGE' /tmp/rook-ceph-operator.yaml
```

The ceph-csi release notes state the Ceph version its bundled librados targets. After the operator is running you can confirm from the live plugin (this is **post-install verification**, not the pre-install gate):

```bash
oc -n rook-ceph exec deploy/rook-ceph.rbd.csi.ceph.com-ctrlplugin -c csi-rbdplugin -- ceph --version
```

**Known incompatibility:** Ceph **Tentacle** (`v20.2.4`) creates cephx keys with the new **AES256K** cipher (key byte `0x02`, base64 prefix `Ag`). ceph-csi **v3.17** bundles librados **20.2.1**, which cannot decode AES256K keys. Every RBD/CephFS/NFS `PersistentVolumeClaim` then stays `Pending` with `rados: ret=-22, Invalid argument`, and the CSI provisioner logs `failed to decode key`. RGW/OBC provisioning is unaffected because it does not use the CSI librados auth path, which makes the failure easy to misdiagnose. Classic AES keys (byte `0x01`, base64 prefix `AQ`) decode correctly.

Prefer a Ceph release that uses classic AES keys and is supported by the deployed ceph-csi — for Rook v1.20 with ceph-csi v3.17, pin **Squid `v19.2.2`** (or another Reef/Squid build) rather than Tentacle `v20.2.4`. Verify the cipher after the cluster is `Ready`:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph auth get-key client.admin | head -c 2  # expect 'AQ', not 'Ag'
```

Do not downgrade a running cluster to fix this — a `v20`-formatted mon/OSD store is incompatible with `v19` (`unsupported features: ...aes256k`). Wipe and redeploy on the compatible version instead.

## Node and Disk Discovery

For each candidate OSD disk, use a stable path and capture non-destructive evidence:

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

Never proceed from `/dev/nvmeXnY`, `/dev/sdX`, or a guessed path alone. Resolve and record the `/dev/disk/by-id/*` or `/dev/disk/by-path/*` identity first.

## OpenShift Prerequisites

Rook Ceph needs elevated privileges (host paths for OSDs, privileged CSI). On
OpenShift, prefer the upstream OpenShift manifests, which create dedicated,
scoped SecurityContextConstraints instead of granting the broad built-in
`privileged` SCC to service accounts:

- Use `operator-openshift.yaml` instead of `operator.yaml` (see Direct Manifest
  Install below). It defines a dedicated `rook-ceph` SCC (and a `rook-ceph-csi`
  SCC) bound to the Rook service accounts, and sets
  `ROOK_HOSTPATH_REQUIRES_PRIVILEGED=true` so OSD pods using host paths run
  correctly.
- The dedicated `rook-ceph` SCC binds these service accounts: `rook-ceph-system`,
  `rook-ceph-default`, `rook-ceph-mgr`, `rook-ceph-osd`, and `rook-ceph-rgw`.
  Confirm they are covered before deploying OSDs or an object store.

If you must grant SCCs manually (a customized install), grant **all** the service
accounts the workloads use — omitting `rook-ceph-rgw` or `rook-ceph-default`
causes RGW or OSD-prepare pods to fail admission:

```bash
oc adm policy add-scc-to-user privileged -z rook-ceph-system -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-default -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-osd -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-mgr -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-rgw -n rook-ceph
```

## Install Path

### Helm Install (Recommended)

The `rook-ceph` chart installs the **operator only** — the CephCluster CR and
pools below are applied separately (or via the companion `rook-ceph-cluster`
chart). The operator chart ships the OpenShift SecurityContextConstraints; after
install, verify they exist with `oc get scc rook-ceph rook-ceph-csi`.

```bash
helm repo add rook-release https://charts.rook.io/release
helm repo update rook-release
helm install rook-ceph rook-release/rook-ceph \
  --namespace rook-ceph --create-namespace
```

### Direct Manifest Install (OLM or YAML)

For OLM-based installs, use the OperatorHub or an OLM Subscription. For direct manifest installs, pin the version, create the namespace explicitly on a fresh cluster, apply the Ceph CSI operator manifest (`csi-operator.yaml`), then use the OpenShift operator manifest (`operator-openshift.yaml`), which ships the dedicated SCCs described above:

```bash
ROOK_VERSION="v<version>"
curl -fsSLo /tmp/rook-ceph-crds.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/crds.yaml"
curl -fsSLo /tmp/rook-ceph-common.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/common.yaml"
curl -fsSLo /tmp/rook-ceph-csi-operator.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/csi-operator.yaml"
curl -fsSLo /tmp/rook-ceph-operator.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/operator-openshift.yaml"
```

Create the namespace before `common.yaml` on a fresh cluster. Apply CRDs first (required before common, CSI, and operator manifests), then common, then `csi-operator.yaml`, then the OpenShift operator. Apply the CRDs server-side — the Rook CRDs are large and client-side `oc apply` can fail with a `metadata.annotations: Too long` error:

```bash
oc get ns rook-ceph >/dev/null 2>&1 || oc create ns rook-ceph
oc apply --server-side --force-conflicts -f /tmp/rook-ceph-crds.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-common.yaml
oc apply -f /tmp/rook-ceph-common.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-csi-operator.yaml
oc apply -f /tmp/rook-ceph-csi-operator.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-operator.yaml
oc apply -f /tmp/rook-ceph-operator.yaml
```

Newer Rook releases use `csi.ceph.io/v1` resources such as `CephConnection`,
`Driver`, and `OperatorConfig`. If `csi-operator.yaml` is omitted, a new
`CephCluster` can stall with `no matches for kind "CephConnection"` even though
the main operator deployment is running.

## CephCluster CR for SNO

On SNO, use a CephCluster with minimal mon/mgr counts and explicit device
pinning when the user names a dedicated OSD disk:

```yaml
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata:
  name: rook-ceph
  namespace: rook-ceph
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v<ceph-version>
    allowUnsupported: false
  dataDirHostPath: /var/lib/rook
  mon:
    count: 1
    allowMultiplePerNode: true
  mgr:
    count: 1
    allowMultiplePerNode: true
  dashboard:
    enabled: true
  cephConfig:
    global:
      osd_pool_default_size: "1"
      mon_warn_on_pool_no_redundancy: "false"
      mon_max_pg_per_osd: "500"
  storage:
    useAllNodes: false
    useAllDevices: false
    config:
      osdsPerDevice: "1"
    nodes:
    - name: "<sno-node>"
      devices:
      - name: "/dev/disk/by-id/<stable-disk-id>"
```

Prefer explicit `/dev/disk/by-id/...` device pinning when the user has already
identified one OSD disk. Reserve `useAllDevices: true` for nodes that are
intentionally dedicated to Ceph. If the SNO node is tainted for storage
workloads, add the required toleration block explicitly instead of assuming it.

Do not copy `mon.count: 1`, `allowMultiplePerNode: true`, or
`mon_max_pg_per_osd: "500"` into multi-node production plans without explicit
direction.

When preparing version-pinned example manifests, prefer the packaged helper and
pass explicit Rook/Ceph versions from live discovery (do not treat helper defaults
as the install target). The helper only substitutes exact placeholder tokens such
as `CEPH_VERSION_PLACEHOLDER` and `ROOK_VERSION_PLACEHOLDER`; prose tokens like
`v<ceph-version>` are left unchanged. Put those placeholder tokens in the input
manifest first, for example:

```yaml
spec:
  cephVersion:
    image: quay.io/ceph/ceph:CEPH_VERSION_PLACEHOLDER
```

```bash
python3 scripts/patch_rook_ceph_manifest.py \
  --input /tmp/rook-ceph-cluster.yaml \
  --output /tmp/rook-ceph-cluster-patched.yaml \
  --rook-version "${ROOK_VERSION}" \
  --ceph-version "${CEPH_VERSION}" \
  --replicas 1 \
  --mon-count 1 \
  --mgr-count 1 \
  --allow-multiple-per-node

oc apply --dry-run=server -f /tmp/rook-ceph-cluster-patched.yaml
```

Only after reviewing the patched image pins and topology, apply:

```bash
oc apply -f /tmp/rook-ceph-cluster-patched.yaml
```

## CephCluster CR for Multi-Node Production

```yaml
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata:
  name: rook-ceph
  namespace: rook-ceph
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v<ceph-version>
  dataDirHostPath: /var/lib/rook
  mon:
    count: 3
    allowMultiplePerNode: false
  mgr:
    count: 2
    allowMultiplePerNode: false
  dashboard:
    enabled: true
  storage:
    useAllNodes: false
    nodes:
    - name: "node-1"
      devices:
      - name: "/dev/disk/by-id/<disk-1>"
    - name: "node-2"
      devices:
      - name: "/dev/disk/by-id/<disk-2>"
    - name: "node-3"
      devices:
      - name: "/dev/disk/by-id/<disk-3>"
  network:
    provider: host
    connections:
      requireMsgr2: false
  placement:
    all:
      nodeAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          nodeSelectorTerms:
          - matchExpressions:
            - key: node.ocs.openshift.io/storage
              operator: In
              values:
              - "true"
```

Label storage nodes explicitly:

```bash
oc label node <node-1> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-2> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-3> node.ocs.openshift.io/storage=true --overwrite
```

## Deploy the Toolbox

The Rook Ceph toolbox provides the `ceph` CLI inside the cluster. It is not deployed automatically — apply it explicitly before running any `ceph` commands:

```bash
curl -fsSLo /tmp/rook-ceph-toolbox.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/toolbox.yaml"
oc apply -f /tmp/rook-ceph-toolbox.yaml
oc -n rook-ceph rollout status deploy/rook-ceph-tools --timeout=5m
```

## Install Validation

Wait for the operator and cluster to reach a healthy state:

```bash
oc -n rook-ceph rollout status deploy/rook-ceph-operator --timeout=10m
oc -n rook-ceph wait cephcluster/rook-ceph --for=condition=Ready --timeout=15m
oc -n rook-ceph get pods -o wide
oc -n rook-ceph get cephcluster -o wide
```

Check Ceph cluster health via the toolbox:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
```

Before declaring success, verify:

- All mons are in quorum.
- All OSDs are `up` and `in`.
- Ceph cluster health is `HEALTH_OK` or `HEALTH_WARN` with known, documented warnings.
- No PGs are stuck in `creating`, `degraded`, or `peering`.
- Exactly one default StorageClass exists when defaulting is expected.

## Enable The Rook Orchestrator Backend

The dashboard Orchestrator page and `ceph orch` commands stay unavailable until
the mgr uses the Rook backend. Run this after the CephCluster is Ready and the
mgr is active:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph mgr module enable rook
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph orch set backend rook
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph orch status
```

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
