# Local Storage Operator Disk Preparation

Use this runbook for preparing dedicated local block disks for ODF OSDs on OpenShift/RHCOS nodes using the Local Storage Operator (LSO). Internal-attached ODF consumes disks through LSO-provisioned local PVs, not by naming raw devices in a Rook CR.

## Disk Selection Gate

Before every destructive disk action, collect non-destructive evidence:

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

Never proceed from `/dev/sdX`, `/dev/nvmeXnY`, or guessed paths. Resolve and record the stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` identity first. ODF/Ceph OSDs use BlueStore on the raw block device; for a fresh OSD the disk should be unpartitioned and free of filesystem signatures.

## Install The Local Storage Operator

Install LSO through OLM into its own `openshift-local-storage` namespace:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: openshift-local-storage
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-local-storage
  namespace: openshift-local-storage
spec:
  targetNamespaces:
  - openshift-local-storage
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: local-storage-operator
  namespace: openshift-local-storage
spec:
  channel: stable
  name: local-storage-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

```bash
oc apply -f /tmp/lso-subscription.yaml
oc -n openshift-local-storage wait csv \
  -l operators.coreos.com/local-storage-operator.openshift-local-storage \
  --for=jsonpath='{.status.phase}'=Succeeded --timeout=10m
```

## Discover Devices

Create a `LocalVolumeDiscovery` to inventory available disks per node without consuming them:

```yaml
apiVersion: local.storage.openshift.io/v1alpha1
kind: LocalVolumeDiscovery
metadata:
  name: auto-discover-devices
  namespace: openshift-local-storage
spec:
  nodeSelector:
    nodeSelectorTerms:
    - matchExpressions:
      - key: cluster.ocs.openshift.io/openshift-storage
        operator: Exists
```

Review the results before selecting disks:

```bash
oc -n openshift-local-storage get localvolumediscoveryresults -o yaml
```

## Provision Local Block PVs

Create a `LocalVolumeSet` that selects the intended disks and provisions raw `Block` PVs into a dedicated StorageClass (for example `localblock`). Filter by device attributes rather than naming raw kernel paths so selection is stable across reboots:

```yaml
apiVersion: local.storage.openshift.io/v1alpha1
kind: LocalVolumeSet
metadata:
  name: localblock
  namespace: openshift-local-storage
spec:
  nodeSelector:
    nodeSelectorTerms:
    - matchExpressions:
      - key: cluster.ocs.openshift.io/openshift-storage
        operator: Exists
  storageClassName: localblock
  volumeMode: Block
  deviceInclusionSpec:
    deviceTypes:
    - disk
    minSize: 100Gi
```

Validate that PVs were created for each intended disk:

```bash
oc get sc localblock
oc get pv | grep localblock
oc -n openshift-local-storage get localvolumeset localblock -o wide
```

The `StorageCluster` in `references/install-and-preflight.md` then references `storageClassName: localblock` in its `dataPVCTemplate`.

## Raw Block Cleanup (after explicit confirmation)

If a disk still carries old signatures and must be reused for a new OSD, clean it only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"
```

Verify it is clean:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  lsblk -f '${DISK}'
  wipefs -n '${DISK}' || true
  ceph-volume lvm list '${DISK}' || true
"
```

## Validation

After the StorageCluster is applied and OSDs are created, validate OSD health:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd df
oc -n openshift-storage get pods -l app=rook-ceph-osd -o wide
```

Confirm:

- One OSD exists per selected local PV.
- All OSDs are `up` and `in`.
- OSD weights are balanced.
- No OSDs are in `out` or `down` state unless deliberately being replaced.

## SNO OSD Considerations

On SNO, all OSDs run on the same node. ODF tolerates this with a single-replica device set, but availability is limited by the single node. Use `replica: 1` in the `StorageDeviceSet` and expect reduced mon/mgr counts.
