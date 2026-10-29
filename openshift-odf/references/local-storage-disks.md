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

If `oc wait --for=jsonpath=...` fails with `unrecognized condition`, poll `.status.phase` instead.

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

### Disks with no `/dev/disk/by-id/` entry (virtio and generic virtual disks)

Some hypervisor disks (virtio `/dev/vdX`, or a generic virtual disk with no serial) have no
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

## Choose reuse or sanitization first

For reinstall, the default is complete BlueStore metadata reset. ODF's authorized
`cleanup-policy=delete` normally performs that cleanup; verify all label copies
and `ceph-volume raw list` before reuse. It is not a media-sanitization claim.
Release the ODF/LSO PVC/PV claims, stop cleanup/prepare pods, and recheck the exact
stable device identity before any manual Disk Cleanup command.

```bash
python3 scripts/plan_osd_disk_prep.py
```

Only an explicit requirement to sanitize the whole device selects the following
secure-erase section. The planner delegates capability selection to the unchanged
`scripts/select_erase_method.py`; its output does not grant permission to erase:

```bash
python3 scripts/plan_osd_disk_prep.py --intent sanitize --device-class virtio
```

Do not benchmark zero writes or run another erase after successful reuse cleanup.
Keep exact-disk destructive approval and every unused-disk gate in both paths.

## NVMe and SATA secure erase

For explicit sanitization intent, SSDs and NVMe devices often destroy previous contents by changing the media encryption key (cryptographic erase) or by a sanitize / secure-erase command. Either one covers the whole device, which the BlueStore offset wipe does not. A device can support one, both, or neither. Discover that read-only, then run `scripts/select_erase_method.py` and use the fastest method that erases the whole device. Run an erase only after explicit destructive confirmation for the exact `/dev/disk/by-id/` path.

This is the controller command `nvme sanitize` / `nvme format`. It is not ODF's `cleanup-policy=delete` job, which only quick-wipes OSD metadata. Delete any released local PV for the disk first, and do not start an erase while an LSO volume or a cleanup pod still holds the device.

Refuse `nvme format`, `nvme sanitize`, and ATA security erase unless all of these are true:

- `readlink -f` of the by-id path is the device you mean, and it is not the boot disk (no mounted root, boot, or EFI partition on it).
- The NVMe controller's `nn` is 1, and that single namespace is the confirmed device. Format and sanitize can apply to every namespace on the controller.
- `fna` bit 0 (format applies to all namespaces) and bit 1 (secure erase applies to all namespaces) are unset, or `nn` is 1 so "all namespaces" is still only this disk. If either bit is set and `nn` is greater than 1, stop.
- Nothing else has the device open (no mount, holder, local PV, or OSD prepare).

RHCOS often ships `/usr/sbin/nvme` (nvme-cli 2.x). If `nvme` is absent, do not guess that erase is supported. Use the BlueStore label wipe below.

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c '
set -euo pipefail
DISK=$1
command -v nvme
d=$(readlink -f "$DISK")
ctrl=${d%n*}
echo "device=$d controller=$ctrl"
echo "namespaces:"
ls -d /sys/class/nvme/${ctrl#/dev}/nvme*n*
nvme id-ctrl "$d" -o json
nvme id-ns "$d" -H
' _ "$DISK"
```

From Identify Controller:

- `nn`: number of namespaces. Greater than 1 stops the erase.
- `fna` bit 2 (value 4): Format cryptographic erase is supported (`nvme format --ses=2`). This replaces the media encryption key.
- `fna` bit 3 (value 8): that cryptographic erase applies to all namespaces.
- `sanicap` bit 0 (value 1): sanitize cryptographic erase (`--sanact=4`).
- `sanicap` bit 1 (value 2): sanitize block erase (`--sanact=2`). This is a media erase, not a key change.
- `sanicap` bit 2 (value 4): sanitize overwrite (`--sanact=3`).

`fna` 0 with `sanicap` 2 means the device cannot change an encryption key and can block-erase. Do not walk the commands below until a bit is set. Pass the identify bits and the estimated seconds from `nvme sanitize-log` to the selector, then run only the method it prints. `4294967295` is not a duration. Time that one command until the erase is proper (`SSTAT` bits 2:0 equal to `1`, or zero reads at the BlueStore offsets and `ceph-volume raw list` printing `{}`). Do not run a second method after that succeeds.

```bash
python3 scripts/plan_osd_disk_prep.py --intent sanitize \
  --fna <fna> --sanicap <sanicap> --nn <nn> \
  --crypto-seconds <estimated> \
  --block-seconds <estimated> \
  --overwrite-seconds <estimated>
```

A key change with no reported duration is counted as finishing with the command. A reported block-erase duration that is shorter than a reported key-change duration wins. An untimed block erase still wins over a reported overwrite or an extrapolated full-disk zero. The BlueStore offset wipe is rejected: it does not erase the device. For `fna` 0, `sanicap` 2, and every estimate `4294967295`, the selector prints `sanitize-block`.

Run the command the script names:

1. **Sanitize cryptographic erase** when the script prints `sanitize-crypto`. This changes the key and does not rewrite the LBA format:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c '
set -euo pipefail
DISK=$1
d=$(readlink -f "$DISK")
ctrl=${d%n*}
nvme sanitize "$ctrl" --sanact=4 --ause
' _ "$DISK"
```

2. **Format cryptographic erase** when the script prints `format-crypto`. nvme-cli 2.x requires `--lbaf`. Copy the in-use LBA format index from `nvme id-ns -H`. The wrong index changes the sector size:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c '
set -euo pipefail
d=$(readlink -f "$1")
nvme format "$d" --lbaf=<in-use-lbaf> --ses=2 --force
' _ "$DISK"
```

3. **Sanitize block erase** when the script prints `sanitize-block`. `nvme sanitize` returns when the controller accepts the command, so the debug pod can exit while the erase continues. Estimated time may read `4294967295` (no time period reported); the erase can still finish in seconds. Poll instead of guessing a window:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c '
set -euo pipefail
DISK=$1
d=$(readlink -f "$DISK")
ctrl=${d%n*}
nvme sanitize "$ctrl" --sanact=2 --ause
' _ "$DISK"
```

`--ause` requests unrestricted completion so a failed sanitize can be exited. The first log can still show the erase in progress. Do not reboot the node, and on SNO do not power-cycle, while it is in progress:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c '
d=$(readlink -f "$1")
nvme sanitize-log "${d%n*}"
' _ "$DISK"
```

Read `SSTAT` and `SPROG` from that log:

- Bits 2:0 of `SSTAT` are `2` while the sanitize is in progress (`0x2` at the start, with `SPROG` `0`).
- `SPROG` `65535` only means no sanitize is running. That is also the value before any sanitize, when `SSTAT` is `0`.
- Success is bits 2:0 equal to `1`. Bit 8 (`0x100`, Global Data Erased) set means no user data has been written since that success. A completed block erase reports `0x101`.
- `SCDW10` `0xa` is AUSE plus block erase (`sanact` 2). That is the controller's record of this command.
- Status `3` is failure. Stop. `nvme sanitize --sanact=1` on that same controller exits failure mode only when the controller allows it. Do not start OSD prepare on a device stuck in sanitize.

On RHCOS with nvme-cli 2.16, a single-namespace controller reporting `fna` 0 and `sanicap` 2 accepted `--sanact=2 --ause` and finished with `SSTAT` `0x101`. Reads at 0, 1 GiB, 10 GiB, and 100 GiB were zeros, and `ceph-volume raw list` stayed `{}`.

Two blank single-namespace disks on that same host, with a marker planted at 0, 1 GiB, and 2 GiB, separated the methods that blank the device from the ones that only look fast:

- Controller `fna` 4, `sanicap` 3, 512-byte LBA format in use, every estimate `4294967295`. Format cryptographic erase (`--ses=2 --lbaf=0`) finished in 71 ms and destroyed the marker, but the reads were not zeros, so this is not a blank. The in-use LBA format stayed 512 and `ceph-volume raw list` stayed `{}`. Sanitize cryptographic erase (`--sanact=4`) finished in 234 ms with `SSTAT` `0x101` and the three markers read back as zeros. Sanitize block erase took 6776 ms and also returned zeros with `SSTAT` `0x101`. The selector prints `sanitize-crypto` here: it is the fastest method that blanks the device. Format crypto is faster and does not blank.
- Controller `fna` 0, `sanicap` 2. The five-offset BlueStore label wipe finished in 18 ms, cleared 0 and 1 GiB, and left the 2 GiB marker in place. Sanitize block erase then took 8365 ms, returned `SSTAT` `0x101`, and the 2 GiB marker read back as zeros. A 1 GiB zero write took 0.527 s, which scales to about 502 s for that whole device. Block erase is the proper blank, and it is the one the selector prints.

When the script prints `sanitize-overwrite`, use the block-erase debug wrapper with `--sanact=3` instead of `--sanact=2`. That overwrite rewrites the media; treat it like a full-disk zero.

A SATA SSD may report secure erase or enhanced erase in `hdparm -I`, including a minute count for each. Pass those counts as `--secure-erase-minutes` and `--enhanced-erase-minutes`. The selector prints the shorter one. Do not run either when that output says the security state is frozen or locked. A frozen drive ignores the erase until a power cycle, and on SNO that power cycle drops the API. Do not set an ATA security password on the boot disk. If `hdparm` is missing or the security feature set is unsupported, there is no ATA secure-erase path.

Virtio (`/dev/vd*`, driver `virtio_blk`) and other virtual disks are not blanked with `fstrim`. `fstrim` only discards free space on a mounted filesystem, and RHCOS rejects it on a raw device. Classify the resolved whole disk before choosing an erase. A virtual NVMe controller (driver `nvme`, including a QEMU NVMe model) stays on the NVMe path above. A disk with no `/dev/disk/by-id/` entry uses the virtio udev section above; that recipe applies to a generic virtual disk too.

```bash
oc debug "node/${NODE}" -- chroot /host bash -c '
d=$(readlink -f "$1")
name=${d#/dev/}
if drv=$(readlink -f "/sys/block/$name/device/driver" 2>/dev/null); then driver=$(basename "$drv"); else driver=none; fi
echo "driver=$driver"
echo "write_zeroes_max_bytes=$(cat /sys/block/$name/queue/write_zeroes_max_bytes)"
echo "discard_max_bytes=$(cat /sys/block/$name/queue/discard_max_bytes)"
udevadm info -q property -n "$d" | awk -F= "/^(ID_VENDOR|ID_MODEL|ID_BUS|DEVTYPE)=/"
' _ "$DISK"
```

- driver `nvme` → `--device-class nvme` and the `fna` / `sanicap` path. Do not treat it as a generic virtual disk.
- driver `virtio_blk` → `--device-class virtio`.
- driver `virtio_scsi`, or a vendor/model such as QEMU, VirtIO, VMware, Xen, Virtual Disk, or Msft, and the driver is not `nvme` → `--device-class virtual`. This is the generic virtual disk.

Pass that class and `write_zeroes_max_bytes`. Target the stable `/dev/disk/by-id/` or `/dev/disk/by-path/` path, never `/dev/vdX` or `/dev/sdX`.

```bash
python3 scripts/plan_osd_disk_prep.py --intent sanitize \
  --device-class <virtio|virtual> \
  --write-zeroes-max-bytes <write_zeroes_max_bytes>
```

When `write_zeroes_max_bytes` is greater than 0, the script prints `write-zeroes`. `blkdiscard --zeroout` is that blank for both virtio and a generic virtual disk: the guest reads zeros afterward, and when the device also advertises discard the kernel can unmap the range in the same call. That unmap is the trim. Do not run `fstrim` as well.

```bash
oc debug "node/${NODE}" -- chroot /host bash -c '
set -euo pipefail
d=$(readlink -f "$1")
blkdiscard --zeroout "$d"
' _ "$DISK"
```

When the class is `virtio` or `virtual` and `write_zeroes_max_bytes` is 0, the script prints `full-disk-zero` and notes that writing zeroes is the blank. A generic virtual disk is fine with that write. Do not issue `nvme sanitize` or an ATA secure erase at it. `discard_max_bytes` greater than 0 is only a hint; plain `blkdiscard` and `fstrim` do not promise zeros. NVMe disks that advertise discard but report `write_zeroes_max_bytes` 0 stay on the sanitize path above.

When the script prints `full-disk-zero`, that is the proper erase. The BlueStore offset wipe is faster and only clears label copies; use it when the goal is to drop a foreign Ceph label, not when the device contents must be erased. After a successful device erase, resolve the by-id path again (the namespace node can disappear during sanitize) and do not reuse the disk until `ceph-volume raw list` prints `{}`.

## Raw Block Cleanup (after explicit confirmation)

If a disk still carries old signatures and must be reused for a new OSD, clean it only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target.

**Important:** `wipefs -af` + `sgdisk --zap-all` alone are **not sufficient** for disks that previously held a Ceph BlueStore OSD. Modern BlueStore replicates its **block device label** at offsets **0, 1 GiB, 10 GiB, 100 GiB, and 1000 GiB** (whichever fit on the device). A head/tail (or even midpoint) wipe leaves the 10 GiB / 100 GiB copies intact. On a live ODF 4.20 reinstall, `ceph-volume raw list` then fails with:

```text
osd.0 belonging to a different ceph cluster "<old-fsid>"
```

even when `lsblk -f` and `wipefs -n` look clean.

With a Ceph image of `v19.2.1` or later, `ceph-bluestore-tool zap-device` clears the label block at every location that fits: 0, 1 GiB, 10 GiB, 100 GiB, and 1000 GiB. It does not write past the end of a smaller disk, and it refuses to run without `--yes-i-really-really-mean-it`. RHCOS does not ship the tool, so use a Ceph image; ODF 4.20.20 ships Red Hat Ceph `19.2.1-405`, which has `zap-device`. The tool only writes zeros at fixed offsets, so the version that wrote the labels does not matter. It clears label blocks only; partition tables and filesystem signatures require separate cleanup. Ceph `v19.2.0` and earlier have no `zap-device` and use the targeted offset wipe below.

### Ceph v19.2.1+ reuse cleanup

After explicit destructive confirmation for the exact stable disk path, clear BlueStore labels, then remove partition-table and filesystem-signature metadata. Finally, verify that Ceph no longer detects an OSD on the disk:

```bash
DISK="/dev/disk/by-id/<stable-disk-id>"

# Clear BlueStore labels with a Ceph v19.2.1+ image:
oc debug "node/${NODE}" --image=quay.io/ceph/ceph:v19.2.2 -- bash -c '
  set -eu
  mount --rbind /host/dev /dev
  ceph-bluestore-tool zap-device --dev '"${DISK}"' --yes-i-really-really-mean-it
'

# Clear partition-table and filesystem-signature metadata:
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"

# Verify; do not reuse unless raw list returns {}:
oc debug "node/${NODE}" --image=quay.io/ceph/ceph:v19.2.2 -- bash -c '
  mount --rbind /host/dev /dev
  ceph-volume raw list '"${DISK}"' --format json   # must print {}
'
```

### Ceph v19.2.0 and earlier (or no suitable zap-device image)

After the same exact-disk confirmation, clear every BlueStore label offset that fits, then clear partition and signature metadata. Verify with `ceph-volume raw list` and proceed only when it returns `{}`:

```bash
oc debug "node/${NODE}" -- chroot /host bash -ceu "
  DISK='${DISK}'
  BYTES=\$(blockdev --getsize64 \"\$DISK\")
  G=\$((1024*1024*1024))
  for mult in 0 1 10 100 1000; do
    off=\$((mult * G))
    [ \"\$off\" -ge \"\$BYTES\" ] && continue
    dd if=/dev/zero of=\"\$DISK\" bs=4096 seek=\$((off/4096)) count=256 status=none conv=fsync
  done
  wipefs -af \"\$DISK\"
  sgdisk --zap-all \"\$DISK\"
  sync
"
oc debug "node/${NODE}" --image=quay.io/ceph/ceph:v19.2.2 -- bash -c '
  mount --rbind /host/dev /dev
  ceph-volume raw list '"${DISK}"' --format json   # must print {}
'
```

### Explicit whole-device sanitization

A full-device zero is only one possible method when policy explicitly requires sanitization. Use the **Choose reuse or sanitization first** workflow above to select the device-wide erase method; do not use full-disk zeroing for ordinary BlueStore label cleanup.

Do not call the disk clean until `ceph-volume raw list` returns `{}`. The OSD prepare job runs the same check and CrashLoopBackOffs on a foreign-cluster label.

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
