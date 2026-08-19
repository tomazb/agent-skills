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

First resolve which stable path the candidate disk actually has. Not every disk gets a `/dev/disk/by-id/` entry: virtio disks presented without a serial (common on KVM/libvirt and OpenStack) appear only under `/dev/disk/by-path/`, so a by-id path for them does not exist to be found.

```bash
NODE="<node>"
oc debug "node/${NODE}" -- chroot /host bash -c '
  echo "=== by-id ==="; ls -l /dev/disk/by-id/ 2>/dev/null || echo "(no by-id entries)"
  echo "=== by-path ==="; ls -l /dev/disk/by-path/
'
```

Pick the by-id path when the disk has one — it survives controller and slot changes. When the disk appears only under `by-path`, use that: it is stable for as long as the disk stays on the same PCI address, which is the documented selector for virtual environments (see `volume-group-provisioning.md`). Either way, record the resolved path; never target `/dev/vdX`, `/dev/sdX`, or `/dev/nvmeXnY` directly, since those names are assignment-order dependent and can move across reboots.

Then, for each candidate disk, capture non-destructive evidence against the resolved path:

```bash
NODE="<node>"
# by-id when the disk has one, otherwise the by-path entry resolved above
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${DISK}'
  lsblk -f '${DISK}'
  pvs --devices '${DISK}' '${DISK}' || true
  vgs || true
  lvs || true
  wipefs -n '${DISK}' || true
"
```

Never proceed from `/dev/nvmeXnY`, `/dev/sdX`, or a guessed path alone. Resolve and record the `/dev/disk/by-id/*` or `/dev/disk/by-path/*` identity first.

On RHEL 9 / RHCOS hosts, running plain `pvs <disk>` against a disk that is not in the LVM devices file prints `Cannot use <disk>: device is not in devices file`. The devices file is only an allowlist for LVM scanning, so this message says nothing about on-disk metadata — a PV created on another host, a cloned disk, or a PV removed from `system.devices` prints the same message. Treat it as informational, neither an error that blocks the safety gate nor evidence that the disk is unclaimed. Read the actual metadata with `pvs --devices '${DISK}' '${DISK}'` as above (`--devices` bypasses the devices file for that invocation): `Failed to find physical volume` from that form is the real no-PV evidence, and the claim/wipe decision must rest on it together with the `lsblk -f` and `wipefs -n` output.

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

Then discover the real Subscription channel. LVMS channels in the catalog are version-pinned (for example `stable-4.21`, `stable-4.22`); a Subscription with a channel the catalog does not serve (such as a bare `stable`) sits forever with no CSV. Do not guess the channel — read it from the catalog:

```bash
oc get packagemanifest lvms-operator -n openshift-marketplace \
  -o jsonpath='{.status.defaultChannel}{"\n"}{.status.channels[*].name}{"\n"}{.status.catalogSource}{"\n"}{.status.catalogSourceNamespace}{"\n"}'
```

Use the `defaultChannel` output as `<default-channel>` below unless the user pins a different served channel. The Subscription examples below assume the Red Hat catalog (`redhat-operators` in `openshift-marketplace`); if the discovery output shows the package resolving from a community or custom catalog, set `spec.source` and `spec.sourceNamespace` from the discovered `catalogSource` and `catalogSourceNamespace` instead. Then create the Subscription:

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: lvms-operator
  namespace: openshift-storage
spec:
  channel: <default-channel>
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
  channel: <default-channel>
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

### Decide `default:` before applying any template

`default: true` on a `DeviceClass` makes the operator mark its generated StorageClass as the cluster default. The templates below set `default: true`, which is only correct when the cluster has **no** default StorageClass today. Check first — a cluster running ODF, or any prior LVMS install, may already have one:

```bash
oc get sc -o custom-columns=\
'NAME:.metadata.name,DEFAULT:.metadata.annotations.storageclass\.kubernetes\.io/is-default-class'
```

- **No default today** → `default: true` is fine, and the generated StorageClass becomes the cluster default.
- **A default already exists** → set `default: false`, or you end up with two defaults. Kubernetes does not pick a winner for a PVC that omits `storageClassName`; the outcome depends on which StorageClass the API server happens to return first, so it is not merely untidy.

With `default: false` the operator prints a warning at apply time, and it means what it says: every PVC must then name the StorageClass explicitly.

```text
Warning: no default deviceClass was specified, it will be mandatory to specify
the generated storage class in any PVC explicitly or you will have to declare
another default StorageClass
```

If the cluster has no default StorageClass at all, a PVC that omits `storageClassName` gets no class assigned and stays `Pending` indefinitely — it is not a provisioning failure and nothing in the LVMS logs will explain it. Set `storageClassName: lvms-<deviceclass>` in the PVC, or declare a default deliberately.

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
YAML-aware helper for thin-pool and device-selector edits. Apply the patched
output (not the pre-patch input):

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
oc -n openshift-storage wait lvmcluster/lvmcluster --for=jsonpath='{.status.state}'=Ready --timeout=10m
```

The `LVMCluster` CR has no condition named `Ready` (its conditions are `ResourcesAvailable` and `VolumeGroupsReady`; readiness is reported in `.status.state`), so `oc wait --for=condition=Ready` hangs until timeout even on a healthy install. Wait on `.status.state` as shown above.

If you skip the helper and apply a hand-edited manifest instead, use that same
manifest path consistently for dry-run, apply, and wait.

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

Finish with a functional smoke test from `references/validation-hardening.md` (PVC plus consumer pod, then cleanup). TopoLVM StorageClasses use `volumeBindingMode: WaitForFirstConsumer`, so an unconsumed PVC stays `Pending` by design — a PVC alone proves nothing, and a `Pending` PVC without a pod is not a failure. This applies only to `WaitForFirstConsumer`: on a StorageClass with `volumeBindingMode: Immediate` (which TopoLVM StorageClasses must not use), a PVC stuck `Pending` without a consumer does indicate a provisioning problem.

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
