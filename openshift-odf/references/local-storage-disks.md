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

### LocalVolumeSet (default — recommended for most deployments)

Create a `LocalVolumeSet` that selects only the intended ODF disks and provisions raw `Block` PVs into a dedicated StorageClass (for example `localblock`). A `LocalVolumeSet` claims every matching device on selected nodes, so use filters that uniquely identify the dedicated ODF disks; do not apply a broad size-only filter. Use the exact-path `LocalVolume` workflow below when other storage systems share the node:

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
    # Replace with attributes from LocalVolumeDiscovery that match only ODF disks.
    deviceMechanicalProperties:
    - NonRotational
    minSize: 100Gi
    models:
    - <approved-odf-disk-model-substring>
```

Before applying, verify that the chosen filters return only disks explicitly allocated to ODF. After applying, validate that every `localblock` PV maps to an intended node and stable disk path; stop and investigate before creating the `StorageCluster` if any PV maps to another disk:

```bash
oc get sc localblock
oc get pv | grep localblock
oc -n openshift-local-storage get localvolumeset localblock -o wide
oc get pv -o yaml
```

### Disks with no `/dev/disk/by-id/` entry (virtio and similar)

Some hypervisor disks (for example virtio `/dev/vdX` with no serial) have no
`/dev/disk/by-id/` symlink. The LSO diskmaker refuses to create a PV for them
even when a `LocalVolume` `devicePaths` entry resolves by `by-path`:

```text
unable to find disk ID for local pool ... IDPathNotFoundError: a symlink to
"vdb" was not found in "/dev/disk/by-id/"
```

Create a stable `by-id` symlink with a udev rule delivered by MachineConfig,
then point the `LocalVolume` at the new `/dev/disk/by-id/<name>` path. Resolve
the disk's `ID_PATH` first (`udevadm info -q property -n /dev/<disk> | grep
ID_PATH`) and target that, never a bare kernel name.

```yaml
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  name: 99-odf-virtio-disk-udev
  labels:
    machineconfiguration.openshift.io/role: master
spec:
  config:
    ignition:
      version: 3.4.0
    storage:
      files:
      - path: /etc/udev/rules.d/99-odf-virtio-disk.rules
        mode: 0644
        contents:
          # Decoded rule (match on the stable ID_PATH, not the kernel name).
          # ENV{DEVTYPE}=="disk" is required: partitions of the same disk carry
          # the same ID_PATH, so without it every partition also claims the
          # symlink and udev hands it to whichever device is processed last.
          # Replace pci-0000:00:08.0 with the ID_PATH discovered on YOUR node.
          # SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", ENV{ID_PATH}=="pci-0000:00:08.0", SYMLINK+="disk/by-id/virtio-odf-vdb"
          source: "data:text/plain,SUBSYSTEM%3D%3D%22block%22%2C%20ENV%7BDEVTYPE%7D%3D%3D%22disk%22%2C%20ENV%7BID_PATH%7D%3D%3D%22pci-0000%3A00%3A08.0%22%2C%20SYMLINK%2B%3D%22disk%2Fby-id%2Fvirtio-odf-vdb%22%0A"
```

**Ignition encoding caveat:** the `data:` URL must percent-encode spaces as
`%20`. Ignition decodes `data:` URLs per RFC 2397/3986, where `+` is kept as a
literal `+` (unlike form-encoding, which would turn it into a space). So writing
the rule with `+` separators leaves stray `+` characters
(`SUBSYSTEM==...,+ENV{ID_PATH}==...`) that make udev silently ignore the rule.
Always use `%20`. Verify on the node after the MCP updates:

```bash
oc debug node/<node> -- chroot /host bash -c \
  'cat /etc/udev/rules.d/99-odf-virtio-disk.rules; ls -l /dev/disk/by-id/ | grep vdb'

# Confirm the symlink resolves to the whole disk (not a partition) and that the
# disk's ID_PATH is the one the rule matches on. Both greps are exact-match
# assertions, so this exits non-zero when either value is wrong:
oc debug node/<node> -- chroot /host bash -eu -c '
  expected_id_path="pci-0000:00:08.0"   # keep equal to the udev rule above
  target=$(readlink -f /dev/disk/by-id/virtio-odf-vdb)
  echo "resolved: $target"
  props=$(udevadm info -q property -n "$target")
  grep -Fx "DEVTYPE=disk" <<<"$props"
  grep -Fx "ID_PATH=$expected_id_path" <<<"$props"
'
```

A failure on the `DEVTYPE` line means the rule matched a partition rather than
the whole disk — the missing `ENV{DEVTYPE}=="disk"` clause. A failure on the
`ID_PATH` line means the symlink points at a different device than the rule
targets; do not hand that path to the `LocalVolume`.

A MachineConfig change reboots the node. On SNO the API is unavailable until the
single node returns — wait for the MCP to report `Updated` and the node `Ready`
before continuing. Then reference the new path in the `LocalVolume`:

```yaml
  storageClassDevices:
  - storageClassName: localblock
    volumeMode: Block
    devicePaths:
    - /dev/disk/by-id/virtio-odf-vdb
```

### LocalVolume (exception — when other storage systems share the same node)

When the ODF node also runs other storage systems (Longhorn, LVMS, a second Ceph cluster) that consume raw block devices, `LocalVolumeSet` attribute filters (size, type, model) may accidentally match disks that belong to those systems. Use a `LocalVolume` CR with the exact stable device path to select only the intended ODF disk:

```yaml
apiVersion: local.storage.openshift.io/v1
kind: LocalVolume
metadata:
  name: localblock
  namespace: openshift-local-storage
spec:
  nodeSelector:
    nodeSelectorTerms:
    - matchExpressions:
      - key: cluster.ocs.openshift.io/openshift-storage
        operator: Exists
  storageClassDevices:
  - storageClassName: localblock
    volumeMode: Block
    devicePaths:
    - /dev/disk/by-id/<stable-device-id>
```

Use `LocalVolumeDiscovery` results and `ls -la /dev/disk/by-id/ | grep <kernel-device>` to confirm the stable ID before filling in the path.

The `StorageCluster` in `references/install-and-preflight.md` then references `storageClassName: localblock` in its `dataPVCTemplate`.

## Raw Block Cleanup (after explicit confirmation)

If a disk still carries old signatures and must be reused for a new OSD, clean it only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target.

**Important:** `wipefs -af` + `sgdisk --zap-all` alone are **not sufficient** for disks that previously held a Ceph BlueStore OSD. BlueStore writes its superblock at the start, midpoint (`size/2 - 2K`), and near the end (`size - 4K`) of the device. `ceph-volume raw list` will detect surviving secondary or tertiary copies even after a partial wipe. Full-disk zeroing is required:

```bash
# Standard wipe (removes filesystem signatures and GPT; sufficient for non-Ceph disks)
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"

# Required for disks previously used as Ceph BlueStore OSDs (raw mode)
# Full-disk zero clears all three BlueStore superblock copies
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -euo pipefail
  dd if=/dev/zero of='${DISK}' bs=4M status=progress
  sync
  echo 'Full-disk zero complete'
"
```

Verify it is clean (no signatures, no BlueStore detection):

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  lsblk -f '${DISK}'
  wipefs -n '${DISK}' || true
"
```

Note: `ceph-volume` is not available on RHCOS hosts. The OSD prepare job will run `ceph-volume raw list` inside the container and fail if any BlueStore label remains.

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
