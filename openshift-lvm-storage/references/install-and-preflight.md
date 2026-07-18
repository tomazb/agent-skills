# Install And Preflight

Use this runbook for discovery, installation planning, OpenShift/OKD prerequisites, and first LVMS deployment.

## Live Discovery

Collect current state before choosing a path:

```bash
oc version
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc get ns openshift-storage || true
oc -n openshift-storage get operatorgroup 2>/dev/null || true
oc -n openshift-storage get subscription,csv 2>/dev/null || true
oc -n openshift-storage get pods 2>/dev/null || true
oc -n openshift-storage get lvmclusters.lvm.topolvm.io 2>/dev/null || true
oc -n openshift-storage get logicalvolumes.topolvm.io 2>/dev/null || true
```

Also discover leftovers from a previous lifecycle before reinstalling:

```bash
oc api-resources --api-group=topolvm.io
oc api-resources --api-group=lvm.topolvm.io
oc get sc
oc get machineconfig | grep -i lvm || true
oc get pv,pvc -A -o wide
oc get csidriver topolvm.io 2>/dev/null || true
oc get scc | grep -i lvm || true
```

For each candidate disk, use a stable path and capture non-destructive evidence:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${DISK}'
  lsblk -f '${DISK}'
  pvs '${DISK}' || true
  vgs || true
  lvs || true
  wipefs -n '${DISK}' || true
"
```

Never proceed from `/dev/nvmeXnY`, `/dev/sdX`, or a guessed path alone. Resolve and record the `/dev/disk/by-id/*` or `/dev/disk/by-path/*` identity first.

## OpenShift Prerequisites

LVMS on OpenShift requires the LVM Storage Operator (also known as the TopoLVM operator). It is typically installed via the Operator Lifecycle Manager (OLM) from the Red Hat or Community catalog.

### OLM Install (Recommended)

Install the operator via the OperatorHub or a Subscription. The resources must be created in order: the `openshift-storage` namespace first, then an `OperatorGroup`, then the `Subscription`. A `Subscription` created in a namespace with no `OperatorGroup` never produces a CSV — OLM reports `no operator group found`.

First ensure the namespace exists:

```bash
oc create namespace openshift-storage || true
```

Then create an `OperatorGroup` (skip this if one already exists in `openshift-storage`, for example from a prior ODF install — `oc -n openshift-storage get operatorgroup`):

```yaml
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-storage-operatorgroup
  namespace: openshift-storage
spec:
  targetNamespaces:
    - openshift-storage
```

Then create the Subscription:

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: lvms-operator
  namespace: openshift-storage
spec:
  channel: stable
  name: lvms-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

Or via CLI:

```bash
oc create -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: lvms-operator
  namespace: openshift-storage
spec:
  channel: stable
  name: lvms-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
EOF
```

Wait for the operator CSV to reach `Succeeded`:

```bash
oc -n openshift-storage get csv -w
oc -n openshift-storage get pods -o wide
```

### Namespace and Project

The LVMS operator typically runs in `openshift-storage`. The namespace and its `OperatorGroup` are created as the first steps of the OLM install above. Confirm both exist before troubleshooting a stuck Subscription:

```bash
oc get namespace openshift-storage
oc -n openshift-storage get operatorgroup
```

## LVMCluster CR

After the operator is installed, create the `LVMCluster` CR that defines volume groups, device selectors, and thin pool settings.

### Minimal LVMCluster for SNO

```yaml
apiVersion: lvm.topolvm.io/v1alpha1
kind: LVMCluster
metadata:
  name: lvmcluster
  namespace: openshift-storage
spec:
  storage:
    deviceClasses:
      - name: vg1
        thinPoolConfig:
          name: thin-pool-1
          overprovisionRatio: 10
          sizePercent: 90
        deviceSelector:
          paths:
            - /dev/disk/by-id/<stable-disk-id>
        default: true
        nodeSelector:
          nodeSelectorTerms:
            - matchExpressions:
                - key: kubernetes.io/hostname
                  operator: In
                  values:
                    - <node-name>
```

### Multi-Node LVMCluster

```yaml
apiVersion: lvm.topolvm.io/v1alpha1
kind: LVMCluster
metadata:
  name: lvmcluster
  namespace: openshift-storage
spec:
  storage:
    deviceClasses:
      - name: vg1
        thinPoolConfig:
          name: thin-pool-1
          overprovisionRatio: 10
          sizePercent: 90
        deviceSelector:
          paths:
            - /dev/disk/by-id/<disk-node-1>
            - /dev/disk/by-id/<disk-node-2>
            - /dev/disk/by-id/<disk-node-3>
        default: true
        nodeSelector:
          nodeSelectorTerms:
            - matchExpressions:
                - key: node-role.kubernetes.io/worker
                  operator: Exists
```

`deviceSelector.paths` is evaluated independently on every node matched by `nodeSelector`. A path that does not exist on a given node is skipped on that node (it does not fail the whole cluster). The `<disk-node-1>`, `<disk-node-2>`, `<disk-node-3>` placeholders above are not "one disk per node" routing — list every `/dev/disk/by-id/*` path that should be claimed on any matched node, and use a stable naming convention that resolves correctly per node. If nodes have genuinely different disk layouts, define a separate `deviceClass` with its own `nodeSelector` per group.

When adjusting an existing `LVMCluster` manifest before apply, prefer the packaged
YAML-aware helper for thin-pool and device-selector edits:

```bash
python3 scripts/patch_lvms_manifest.py \
  --input /tmp/lvmcluster.yaml \
  --output /tmp/lvmcluster-patched.yaml \
  --device-paths /dev/disk/by-id/<stable-disk-id> \
  --overprovision-ratio 10 \
  --size-percent 90 \
  --device-class-default true

oc apply --dry-run=server -f /tmp/lvmcluster-patched.yaml
oc apply -f /tmp/lvmcluster-patched.yaml
```

Apply the LVMCluster and wait for it to become ready:

```bash
oc apply -f /tmp/lvmcluster.yaml
oc -n openshift-storage wait lvmcluster/lvmcluster --for=condition=Ready --timeout=10m
```

## Install Validation

Wait for the TopoLVM CSI components and verify the StorageClass was created:

```bash
oc -n openshift-storage get pods -o wide
oc -n openshift-storage get lvmcluster -o wide
oc get sc
oc get csidriver
```

Before declaring success, verify:

- The `LVMCluster` status is `Ready`.
- TopoLVM CSI driver pods are running on all target nodes.
- The default StorageClass was created by the operator (if `default: true` was set in the `LVMCluster`).
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

## SCC Requirements

The LVMS/TopoLVM operator and CSI node plugin require privileged access to manage LVM on the host. On OpenShift, the operator typically creates the necessary SCCs. If using manual manifests or a non-OLM install, ensure the TopoLVM CSI node plugin service account has the required SCC:

```bash
oc get scc | grep topolvm || true
oc -n openshift-storage get serviceaccount
```

Do not grant broad `privileged` SCC manually unless the operator's dedicated SCCs are absent and the docs explicitly require it.
