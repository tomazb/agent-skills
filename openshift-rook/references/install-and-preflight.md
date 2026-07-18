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

Also discover leftovers from a previous lifecycle before reinstalling:

```bash
oc api-resources --api-group=ceph.rook.io
oc get sc
oc get machineconfig | grep -i rook || true
oc get pv,pvc -A -o wide
```

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
