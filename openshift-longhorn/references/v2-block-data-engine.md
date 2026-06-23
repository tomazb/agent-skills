# V2 Block Data Engine

Use this runbook for Longhorn V2 Data Engine, SPDK, NVMe/TCP, raw block disks, or V2 StorageClass work.

## V2 Prerequisites

Verify live prerequisites instead of assuming from version numbers:

- Raw block disk with no filesystem signature or partition table.
- Kernel module support for `nvme_tcp`, `vfio_pci`, and `uio_pci_generic` where
  applicable. Longhorn's SPDK setup and `longhornctl` preflight require these
  three; `vfio_iommu_type1` is not a documented Longhorn requirement and
  auto-loads as a VFIO dependency on IOMMU-enabled hosts.
- Huge pages configured persistently, commonly `hugepagesz=2M hugepages=1024` for 2 GiB.
- `iscsid.service` active for Longhorn attach workflows.
- AMD64 nodes support SSE4.2.
- CPU budget for V2 instance-manager pods.
- V1 filesystem mount MachineConfigs are removed or intentionally disabled if
  the V2 test should use only raw block disks.

Run `longhornctl check preflight --enable-spdk` when available. On OpenShift, use the temporary privileged SCC workflow from `install-and-preflight.md` and remove the SCC grant after the check.

If the V2 preflight reports `ublk_drv cannot be loaded`, treat it as a warning
unless the target design needs the ublk frontend. For a V2 engine using
`diskDriver: aio` and the NVMe/TCP frontend, confirm the other V2 prerequisites
and the Longhorn smoke test before declaring it a blocker.

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
          source: data:text/plain;charset=utf-8;base64,dmZpb19wY2kKdWlvX3BjaV9nZW5lcmljCm52bWVfdGNwCg==
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

On SNO, apply V2 MachineConfig changes only after V1 workloads and Longhorn V1
state have been removed. Wait for the master MCP to update and the node to
return `Ready` before touching raw block disks.

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

For SNO smoke tests, prefer a spare stable disk such as
`/dev/disk/by-id/<stable-id>`. Never use an LVM PV backing another StorageClass,
the root disk, or an ambiguous `/dev/nvmeXnY` path.

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

For a clean V2-only end state, disable V1 only after all V1 volumes, engines,
and replicas are gone:

```bash
oc -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io -o wide
oc -n longhorn-system patch settings.longhorn.io v1-data-engine \
  --type=merge -p '{"value":"false"}'
oc -n longhorn-system get instancemanagers.longhorn.io -o wide
```

If switching from automatic filesystem disk discovery to explicit block disks:

```bash
oc -n longhorn-system patch settings.longhorn.io create-default-disk-labeled-nodes \
  --type=merge -p '{"value":"false"}'
oc -n longhorn-system patch settings.longhorn.io default-data-path \
  --type=merge -p '{"value":"/var/lib/longhorn/"}'
oc label node "${NODE}" node.longhorn.io/create-default-disk-
```

If a stale node annotation still points to `/var/mnt/longhorn`, remove it before
Longhorn manager first starts or before adding the V2 disk:

```bash
oc annotate node "${NODE}" node.longhorn.io/default-disks-config- || true
oc label node "${NODE}" node.longhorn.io/create-default-disk- || true
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

For the `aio` path, only `nvme_tcp` is strictly required for storage I/O over the
NVMe/TCP frontend. The `vfio_pci` and `uio_pci_generic` modules are loaded mainly
to satisfy `longhornctl check preflight --enable-spdk` and SPDK initialization,
not because `aio` performs PCI passthrough.

After patching, wait for the Longhorn node disk to report ready and schedulable:

```bash
oc -n longhorn-system get nodes.longhorn.io "${NODE}" -o yaml
```

It is normal to briefly see `NoDiskInfo`, `DiskNotReady`, or
`mismatching disks in node resource object and monitor collected data` while the
manager creates the V2 disk. Continue polling and check manager logs if the disk
does not become `Ready=True` and `Schedulable=True` within a few minutes.

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
  backupTargetName: "default"  # requires Longhorn v1.8.0+; omit on older versions
```

Keep `longhorn-storageclass` ConfigMap aligned with the live class to prevent reconcile drift.

## Validation

Confirm:

- `volumes.longhorn.io` shows `DATA ENGINE=v2`, attached, and healthy.
- `replicas.longhorn.io` shows the intended replica count and the V2 disk UUID.
- `engines.longhorn.io` shows `DATA ENGINE=v2`.
- The block disk is unmounted and `wipefs -n` shows no filesystem signature.
- Hugepages, modules, `iscsid`, MCP, and node readiness survive reboot.
- `longhorn-storageclass` ConfigMap matches the V2 StorageClass parameters.
