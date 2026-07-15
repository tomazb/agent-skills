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
