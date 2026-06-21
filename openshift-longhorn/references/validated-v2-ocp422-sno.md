# Validated V2 OpenShift 4.22 SNO Evidence

This journal records one observed Longhorn `v1.12.0` V2 Data Engine conversion on OpenShift 4.22 SNO. Treat host names, device names, versions, and command outputs as evidence from that environment, not universal defaults.

## Environment

- Cluster: OpenShift 4.22.1 / Kubernetes 1.35.5
- Node: `sno1.example.com`
- OS/kernel observed before V2 prep: RHCOS/RHEL CoreOS 9.8, `5.14.0-687.13.1.el9_8.x86_64`
- Longhorn: `v1.12.0`
- Starting state:
  - `v1-data-engine=true`
  - `v2-data-engine=false`
  - default `longhorn` StorageClass used `dataEngine: v1`
  - no Longhorn volumes, replicas, or engines existed
  - image registry PVC used `lvms-vg1`, not Longhorn
  - dedicated Longhorn disk was `/dev/nvme2n1`, ext4 label `longhorn`, mounted at `/var/mnt/longhorn`

## Key Lessons So Far

- RHEL 9.8 has supported NVMe/TCP initiator support; the live preflight confirmed `nvme_tcp` was loaded.
- Longhorn V2/SPDK still requires more than NVMe/TCP:
  - hugepages, by default 1024 x 2Mi pages
  - `uio_pci_generic`
  - `vfio_pci`
  - block-type Longhorn disk, not a filesystem-mounted path
- The official `longhornctl check preflight --enable-spdk` creates a privileged hostPath/hostPID DaemonSet. On OpenShift it needs temporary privileged SCC for service account `longhorn-preflight-checker`.

## Preflight Result Before Host Prep

Command:

```bash
/tmp/longhornctl --kubeconfig ~/.kube/config check preflight --enable-spdk
```

Temporary OpenShift SCC grant needed:

```bash
oc adm policy add-scc-to-user privileged -z longhorn-preflight-checker -n longhorn-system
```

Result highlights:

- OK:
  - `iscsid` running
  - `nfs-utils`, `iscsi-initiator-utils`, `cryptsetup`, `device-mapper` installed
  - `iscsi_tcp` loaded
  - `nvme_tcp` loaded
  - `sse4_2` supported
- Failed:
  - HugePages insufficient: required 1024 x 2Mi, available 0
  - `uio_pci_generic` not loaded
  - `vfio_pci` not loaded
- Warning:
  - `ublk` not included in kernel

Cleanup after preflight:

```bash
oc adm policy remove-scc-from-user privileged -z longhorn-preflight-checker -n longhorn-system
```

## Host Prep MachineConfig Applied

Final `81-longhorn-v2-spdk-master` content:

- Adds kernel args:
  - `hugepagesz=2M`
  - `hugepages=1024`
- Adds `/etc/modules-load.d/longhorn-v2-spdk.conf`:
  - `vfio_pci`
  - `uio_pci_generic`
  - `nvme_tcp`

This triggers SNO reboot through the master MachineConfigPool.

## MachineConfig Validation Issue

The initial attempt included a mask for `var-mnt-longhorn.mount` in a later
MachineConfig. That caused MCP degradation:

```text
unexpected on-disk state validating against rendered-master-<hash>:
mode mismatch for file: "/etc/systemd/system/var-mnt-longhorn.mount";
expected: -rw-r--r--/420/0644; received: Lrwxrwxrwx/.../0777
```

Cause: MachineConfigDaemon validates current on-disk state against the previous rendered config before applying the new rendered config. The mount unit had already become a mask symlink, so validation against the old regular file failed.

Recovery:

```bash
oc debug node/sno1.example.com -- chroot /host bash -c '
  rm -f /etc/systemd/system/var-mnt-longhorn.mount
  printf "%s\n" \
    "[Unit]" \
    "Description=Mount dedicated Longhorn disk for Longhorn data" \
    "Before=local-fs.target" \
    "[Mount]" \
    "Where=/var/mnt/longhorn" \
    "What=/dev/disk/by-label/longhorn" \
    "Type=ext4" \
    "Options=rw,relatime,discard" \
    "[Install]" \
    "WantedBy=local-fs.target" \
    > /etc/systemd/system/var-mnt-longhorn.mount
  chmod 0644 /etc/systemd/system/var-mnt-longhorn.mount
  systemctl daemon-reload
'
```

Then update `81-longhorn-v2-spdk-master` to remove the systemd mask and keep only:

- `kernelArguments: hugepagesz=2M`, `hugepages=1024`
- `/etc/modules-load.d/longhorn-v2-spdk.conf`

Article note: remove or disable the old filesystem mount in a separate controlled host step after the MCP is healthy, or replace the original MachineConfig rather than masking the unit from a later one.

After restoring the unit file, restarting the `machine-config-daemon` pod caused
the daemon to revalidate the host and the MCP recovered:

```bash
oc delete pod -n openshift-machine-config-operator <machine-config-daemon-pod>
oc get mcp master -o wide
```

## Host Prep Verification

After the V2 prerequisite MachineConfig settled:

- `/proc/cmdline` included `hugepagesz=2M hugepages=1024`
- `/proc/meminfo` showed:
  - `HugePages_Total: 1024`
  - `HugePages_Free: 1024`
  - `Hugepagesize: 2048 kB`
- Loaded modules included:
  - `uio_pci_generic`
  - `vfio_pci`
  - `vfio_iommu_type1`
  - `nvme_tcp`

Command used:

```bash
oc debug node/sno1.example.com -- chroot /host bash -c '
  cat /proc/cmdline
  grep -i Huge /proc/meminfo
  lsmod | egrep "^(vfio_pci|vfio_iommu_type1|uio_pci_generic|nvme_tcp)"
'
```

## Remove Old Filesystem Mount

Patch the original `80-longhorn-prereqs-master` MachineConfig so it keeps only
`iscsid.service` and no longer defines `var-mnt-longhorn.mount`.

```bash
oc patch machineconfig 80-longhorn-prereqs-master --type=merge -p \
  '{"spec":{"config":{"ignition":{"version":"3.5.0"},"systemd":{"units":[{"enabled":true,"name":"iscsid.service"}]}}}}'
oc wait mcp/master --for=condition=Updated=True --timeout=45m
```

Validated state:

- MCP `master` updated and not degraded.
- `var-mnt-longhorn.mount` no longer exists.
- `/var/mnt/longhorn` is not mounted.
- `/dev/nvme2n1` still had the old ext4 signature at this point.

## Convert Dedicated Disk To Raw Block

Confirmed there were no Longhorn volumes, replicas, or engines before wiping.
Then marked the old filesystem disk unschedulable:

```bash
oc -n longhorn-system patch nodes.longhorn.io sno1.example.com --type=json -p='[
  {"op":"replace","path":"/spec/disks/longhorn-disk/allowScheduling","value":false}
]'
```

Wiped the dedicated disk signature:

```bash
oc debug node/sno1.example.com -- chroot /host bash -c '
  set -e
  wipefs -a /dev/disk/by-id/nvme-SAMSUNG_MZVL21T0HCLR-00B00_SXXXXXXXXXXXXX
  udevadm settle
  lsblk -f /dev/disk/by-id/nvme-SAMSUNG_MZVL21T0HCLR-00B00_SXXXXXXXXXXXXX
'
```

Validation after `wipefs`:

- `wipefs -n` returned no filesystem signatures.
- `lsblk -f` showed empty `FSTYPE` and `LABEL`.

## Enable Longhorn V2 And Add Block Disk

Enabled the V2 data engine:

```bash
oc -n longhorn-system patch settings.longhorn.io v2-data-engine --type=merge -p '{"value":"true"}'
```

Kept V1 enabled during the transition:

- `v1-data-engine=true`
- `v2-data-engine=true`
- `default-replica-count={"v1":"1","v2":"1"}`
- `data-engine-hugepage-enabled={"v2":"true"}`
- `data-engine-memory-size={"v2":"2048"}`

After switching to an explicit V2 block disk, changed old filesystem default
disk behavior to avoid recreating `/var/mnt/longhorn` later:

```bash
oc -n longhorn-system patch settings.longhorn.io create-default-disk-labeled-nodes \
  --type=merge -p '{"value":"false"}'
oc -n longhorn-system patch settings.longhorn.io default-data-path \
  --type=merge -p '{"value":"/var/lib/longhorn/"}'
oc label node sno1.example.com node.longhorn.io/create-default-disk-
```

Replaced the old filesystem disk with a V2 block disk:

```bash
oc -n longhorn-system patch nodes.longhorn.io sno1.example.com --type=json -p='[
  {"op":"remove","path":"/spec/disks/longhorn-disk"},
  {"op":"add","path":"/spec/disks/longhorn-v2-nvme","value":{
    "allowScheduling":true,
    "diskDriver":"aio",
    "diskType":"block",
    "evictionRequested":false,
    "path":"/dev/disk/by-id/nvme-SAMSUNG_MZVL21T0HCLR-00B00_SXXXXXXXXXXXXX",
    "storageReserved":0,
    "tags":["dedicated","v2"]
  }}
]'
```

Article note: `aio` was used deliberately on this SNO. It avoids relying on PCI
device detachment/IOMMU grouping while still using Longhorn V2 for the volume
engine and NVMe/TCP frontend path.

Validated Longhorn disk state:

- `longhorn-v2-nvme`:
  - `diskType: block`
  - `diskDriver: aio`
  - `Ready=True`
  - `Schedulable=True`
  - `storageMaximum: 1020207824896`
  - `storageAvailable: 1020207824896`
- V2 instance manager:
  - `DATA ENGINE: v2`
  - `STATE: running`
  - `TYPE: aio`

## Default StorageClass Recreated For V2

Updated both the live `longhorn` StorageClass and the `longhorn-storageclass`
ConfigMap. StorageClass parameters are immutable, so the old class was deleted
and recreated. No PVCs were using the old `longhorn` class.

Key parameters:

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

Validation:

- `longhorn` remains the cluster default StorageClass.
- `longhorn` has `dataEngine: v2`.
- `longhorn` has `diskSelector: v2`.
- `longhorn-storageclass` ConfigMap matches the live class, preventing drift.
- `create-default-disk-labeled-nodes=false`
- `default-data-path=/var/lib/longhorn/`
- node label `node.longhorn.io/create-default-disk` removed

## Smoke Test

Created namespace `longhorn-v2-smoke`, a PVC without `storageClassName`, and a
pod that wrote to `/data/ok`.

Result:

- PVC `longhorn-v2-smoke/default-longhorn-v2`:
  - `STATUS: Bound`
  - `STORAGECLASS: longhorn`
  - volume `pvc-d6ac882f-7cbc-4595-b9a7-b01010e96877`
- Pod `longhorn-v2-smoke/longhorn-v2-writer`:
  - `READY: 1/1`
  - mounted the volume and wrote a timestamp
- Longhorn volume:
  - `DATA ENGINE: v2`
  - `STATE: attached`
  - `ROBUSTNESS: healthy`
  - `SIZE: 1073741824`
- Longhorn replica:
  - exactly one replica
  - `DATA ENGINE: v2`
  - `STATE: running`
  - `NODE: sno1.example.com`
  - `DISK: 761fa8b8-321d-479a-85dd-90690730afff`
- Longhorn engine:
  - `DATA ENGINE: v2`
  - `STATE: running`
  - V2 instance manager image `docker.io/longhornio/longhorn-instance-manager:v1.12.0`

## Final Live State

Cluster health:

- `mcp/master`: `UPDATED=True`, `UPDATING=False`, `DEGRADED=False`
- `machine-config`, `kube-apiserver`, and `etcd` cluster operators:
  - `AVAILABLE=True`
  - `PROGRESSING=False`
  - `DEGRADED=False`

Longhorn pods:

- Longhorn manager, CSI plugin, driver deployer, UI, engine image, and CSI sidecars running.
- Instance managers:
  - V1 instance manager still running.
  - V2 instance manager running with `TYPE=aio`.

Longhorn V2 disk:

```text
longhorn-v2-nvme block aio max=1020207824896 avail=1020150153216 Ready=True Schedulable=True
```

Storage:

- `longhorn` is the only default StorageClass.
- `longhorn` parameters include `dataEngine=v2`, `diskSelector=v2`, and `numberOfReplicas=1`.
- `longhorn-static` and `lvms-vg1` remain available and non-default.

Smoke resources intentionally left for inspection:

- Namespace: `longhorn-v2-smoke`
- PVC: `default-longhorn-v2`
- Pod: `longhorn-v2-writer`
