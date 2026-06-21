# V2 Block Data Engine

Use this runbook for Longhorn V2 Data Engine, SPDK, NVMe/TCP, raw block disks, or V2 StorageClass work.

## V2 Prerequisites

Verify live prerequisites instead of assuming from version numbers:

- Raw block disk with no filesystem signature or partition table.
- Kernel module support for `nvme_tcp`, `vfio_pci`, `vfio_iommu_type1`, and `uio_pci_generic` where applicable.
- Huge pages configured persistently, commonly `hugepagesz=2M hugepages=1024` for 2 GiB.
- `iscsid.service` active for Longhorn attach workflows.
- AMD64 nodes support SSE4.2.
- CPU budget for V2 instance-manager pods.

Run `longhornctl check preflight --enable-spdk` when available. On OpenShift, use the temporary privileged SCC workflow from `install-and-preflight.md` and remove the SCC grant after the check.

## Host Preparation

A MachineConfig can persist hugepages and modules:

```yaml
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  name: 81-longhorn-v2-spdk-master
  labels:
    machineconfiguration.openshift.io/role: master
spec:
  kernelArguments:
  - hugepagesz=2M
  - hugepages=1024
  config:
    ignition:
      version: 3.5.0
    storage:
      files:
      - path: /etc/modules-load.d/longhorn-v2-spdk.conf
        mode: 0644
        contents:
          source: data:text/plain;charset=utf-8;base64,dmZpb19wY2kKdmZpb19pb21tdV90eXBlMQp1aW9fcGNpX2dlbmVyaWMKbnZtZV90Y3AK
    systemd:
      units:
      - name: iscsid.service
        enabled: true
```

Warn that MachineConfig can reboot nodes. On SNO, wait for MCP recovery before changing disks.

Validate:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  grep -i Huge /proc/meminfo
  lsmod | egrep '^(vfio_pci|vfio_iommu_type1|uio_pci_generic|nvme_tcp)'
  systemctl is-active iscsid
"
```

## Raw Block Disk Gate

Adding or converting a V2 disk can require `wipefs`. This requires explicit destructive confirmation for the exact `/dev/disk/by-id/*` path.

Before every `wipefs`, collect:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${BLOCK_DISK}'
  lsblk -f '${BLOCK_DISK}'
  findmnt -S '${BLOCK_DISK}' || true
  wipefs -n '${BLOCK_DISK}' || true
"
```

Only after confirmation:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -a '${BLOCK_DISK}'
  udevadm settle
  wipefs -n '${BLOCK_DISK}' || true
  lsblk -f '${BLOCK_DISK}'
"
```

## Longhorn Settings

Enable V2 deliberately:

```bash
oc -n longhorn-system patch settings.longhorn.io v2-data-engine \
  --type=merge -p '{"value":"true"}'
```

During migration, keep V1 enabled unless the user explicitly chooses to disable it after all V1 volumes are gone. For SNO with Longhorn versions that support structured replica settings:

```bash
oc -n longhorn-system patch settings.longhorn.io default-replica-count \
  --type=merge \
  -p '{"value":"{\"v1\":\"1\",\"v2\":\"1\"}"}'
oc -n longhorn-system patch settings.longhorn.io data-engine-hugepage-enabled \
  --type=merge -p '{"value":"{\"v2\":\"true\"}"}'
oc -n longhorn-system patch settings.longhorn.io data-engine-memory-size \
  --type=merge -p '{"value":"{\"v2\":\"2048\"}"}'
```

If switching from automatic filesystem disk discovery to explicit block disks:

```bash
oc -n longhorn-system patch settings.longhorn.io create-default-disk-labeled-nodes \
  --type=merge -p '{"value":"false"}'
oc -n longhorn-system patch settings.longhorn.io default-data-path \
  --type=merge -p '{"value":"/var/lib/longhorn/"}'
oc label node "${NODE}" node.longhorn.io/create-default-disk-
```

## Add A Block Disk

Discover disk keys first. Patch only known keys:

```bash
oc -n longhorn-system get nodes.longhorn.io "${NODE}" -o json
```

Example V2 disk entry:

```bash
oc -n longhorn-system patch nodes.longhorn.io "${NODE}" --type=json -p="[
  {\"op\":\"add\",\"path\":\"/spec/disks/longhorn-v2-nvme\",\"value\":{
    \"allowScheduling\":true,
    \"diskDriver\":\"aio\",
    \"diskType\":\"block\",
    \"evictionRequested\":false,
    \"path\":\"${BLOCK_DISK}\",
    \"storageReserved\":0,
    \"tags\":[\"dedicated\",\"v2\"]
  }}
]"
```

Use `diskDriver: aio` when IOMMU grouping or PCI detachment is not safe; this still uses the V2 engine and NVMe/TCP frontend path. Use SPDK NVMe only when IOMMU group isolation is verified.

## V2 StorageClass

StorageClass parameters are immutable for already created volumes. Recreate the class or create a new class when changing from V1 to V2. Keep exactly one default StorageClass when Longhorn is default.

```yaml
parameters:
  numberOfReplicas: "1"
  staleReplicaTimeout: "30"
  fromBackup: ""
  fsType: "ext4"
  dataLocality: "disabled"
  unmapMarkSnapChainRemoved: "ignored"
  dataEngine: "v2"
  diskSelector: "v2"
  backupTargetName: "default"
```

Keep `longhorn-storageclass` ConfigMap aligned with the live class to prevent reconcile drift.

## Validation

Confirm:

- `volumes.longhorn.io` shows `DATA ENGINE=v2`, attached, and healthy.
- `replicas.longhorn.io` shows the intended replica count and the V2 disk UUID.
- `engines.longhorn.io` shows `DATA ENGINE=v2`.
- The block disk is unmounted and `wipefs -n` shows no filesystem signature.
- Hugepages, modules, `iscsid`, MCP, and node readiness survive reboot.
