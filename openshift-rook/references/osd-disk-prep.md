# OSD Disk Preparation

Use this runbook for preparing dedicated block disks for Ceph OSDs on OpenShift/RHCOS nodes.

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

Never proceed from `/dev/sdX`, `/dev/nvmeXnY`, or guessed paths. Resolve and record the stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` identity first.

## Choose the intent first

Reinstall and reuse default to metadata reset, not full-device sanitization:

```bash
python3 scripts/plan_osd_disk_prep.py
```

Follow `rook_wipe_osd_disk` in [maintenance-uninstall.md](maintenance-uninstall.md)
after exact-disk destructive confirmation and fresh unused-disk evidence. It
clears every BlueStore label that fits; partition metadata must also be cleared
after inspection. Require `ceph-volume raw list` to print `{}` before reuse.
This leaves old payload bytes on the medium and is not a sanitization claim.
Do not benchmark zero writes or run secure erase just to reinstall Ceph.

Only an explicit requirement to sanitize the whole device selects the following
section. The read-only planner delegates to `scripts/select_erase_method.py`:

```bash
python3 scripts/plan_osd_disk_prep.py --intent sanitize --device-class virtio
```

The returned method is a plan, not permission to erase. Preserve the exact-disk
approval and every safety gate below. Run one chosen method and verify completion;
never follow a successful metadata reset with an unsolicited full-disk write.

## NVMe and SATA secure erase

For explicit sanitization intent, SSDs and NVMe devices often destroy previous contents by changing the media encryption key (cryptographic erase) or by a sanitize / secure-erase command. Either one covers the whole device, which the BlueStore offset wipe does not. A device can support one, both, or neither. Discover that read-only, then use the fastest supported whole-device method. Run an erase only after explicit destructive confirmation for the exact `/dev/disk/by-id/` path and sanitization intent.

Refuse `nvme format`, `nvme sanitize`, and ATA security erase unless all of these are true:

- `readlink -f` of the by-id path is the device you mean, and it is not the boot disk (no mounted root, boot, or EFI partition on it).
- The NVMe controller's `nn` is 1, and that single namespace is the confirmed device. Format and sanitize can apply to every namespace on the controller.
- `fna` bit 0 (format applies to all namespaces) and bit 1 (secure erase applies to all namespaces) are unset, or `nn` is 1 so "all namespaces" is still only this disk. If either bit is set and `nn` is greater than 1, stop.
- Nothing else has the device open (no mount, holder, or OSD prepare).

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

Virtio (`/dev/vd*`, driver `virtio_blk`) and other virtual disks are not blanked with `fstrim`. `fstrim` only discards free space on a mounted filesystem, and RHCOS rejects it on a raw device. Classify the resolved whole disk before choosing an erase. A virtual NVMe controller (driver `nvme`, including a QEMU NVMe model) stays on the NVMe path above.

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

## Raw Block Preparation (BlueStore)

For BlueStore, the disk should be unpartitioned and free of filesystem signatures. Ceph OSDs use LVM on top of the raw block device.

Clean a disk only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target.

`wipefs -af` and `sgdisk --zap-all` are not sufficient for a disk that previously held a Ceph BlueStore OSD. BlueStore replicates its block-device label at offsets **0, 1 GiB, 10 GiB, 100 GiB, and 1000 GiB** (whichever fit on the device). A wipe of the start of the disk leaves the 10 GiB and 100 GiB copies intact. `lsblk -f` and `wipefs -n` then look clean while OSD prepare fails with `osd.0 belonging to a different ceph cluster "<old-fsid>"`.

When the `cephVersion.image` you plan to deploy is Ceph `v19.2.1` or later, clear the labels with Ceph's own tool. `ceph-bluestore-tool zap-device` zeros the label block at every location that fits: 0, 1 GiB, 10 GiB, 100 GiB, and 1000 GiB. It does not write past the end of a smaller disk. RHCOS does not ship the tool, so run it from that image. It needs the same exact-disk confirmation as any other wipe, and it refuses to run without `--yes-i-really-really-mean-it`. It clears only those label blocks, not partition tables or other signatures. Ceph `v19.2.0` and earlier have no `zap-device`; use the label wipe below. From `v19.2.1`, `ceph-volume lvm zap` runs `zap-device` too, so Rook's `cleanupPolicy` job clears every label copy.

```bash
ROOK_CEPH_IMAGE="quay.io/ceph/ceph:v20.2.4"   # the cephVersion.image you plan to deploy; v19.2.1 or later
oc debug "node/${NODE}" --image="${ROOK_CEPH_IMAGE}" -- bash -c '
  set -eu
  mount --rbind /host/dev /dev
  ceph-bluestore-tool zap-device --dev '"${DISK}"' --yes-i-really-really-mean-it
'
```

Without `zap-device`, or when the secure-erase section above does not apply, prefer either:

1. **Targeted label wipe** (fast; enough when you only need to clear BlueStore ownership), or
2. **full-disk zero** of the whole device (slow; when policy requires total erasure).

```bash
# Standard wipe (filesystem signatures and GPT). Enough only for a disk that
# never held a BlueStore OSD.
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"

# Required when the disk previously held a BlueStore OSD. Zero every main-device
# label offset that fits (0 / 1 GiB / 10 GiB / 100 GiB / 1000 GiB):
oc debug "node/${NODE}" -- chroot /host bash -ceu "
  set -euo pipefail
  DISK='${DISK}'
  BYTES=\$(blockdev --getsize64 \"\$DISK\")
  G=\$((1024*1024*1024))
  for mult in 0 1 10 100 1000; do
    off=\$((mult * G))
    [ \"\$off\" -ge \"\$BYTES\" ] && continue
    dd if=/dev/zero of=\"\$DISK\" bs=4096 seek=\$((off/4096)) count=256 status=none conv=fsync
  done
  wipefs -af \"\$DISK\" || true
  sgdisk --zap-all \"\$DISK\" || true
  sync
"

# Full-disk zero only when policy requires total erasure (can take a long time):
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -euo pipefail
  dd if=/dev/zero of='${DISK}' bs=4M status=progress
  sync
  echo 'Full-disk zero complete'
"
```

Verify with **`ceph-volume raw list`**, not only `wipefs -n` or `lsblk -f`. RHCOS has no `ceph-volume`. Run it from the Ceph image you plan to deploy:

```bash
ROOK_CEPH_IMAGE="quay.io/ceph/ceph:v19.2.2"   # or the cephVersion.image you plan to deploy
oc debug "node/${NODE}" --image="${ROOK_CEPH_IMAGE}" -- bash -c '
  mount --rbind /host/dev /dev
  ceph-volume raw list '"${DISK}"' --format json
  lsblk -f '"${DISK}"'
  wipefs -n '"${DISK}"' || true
'
```

Do not call the disk clean until `ceph-volume raw list` prints `{}` and `wipefs -n` and `lsblk -f` no longer report `ceph_bluestore`. Either result alone is incomplete. An empty raw list can still leave a signature that OSD prepare skips with `Has BlueStore device label`. A clean `lsblk` can still leave a foreign OSD that raw list names; OSD prepare runs that check and CrashLoopBackOffs on the foreign-cluster label. `rook_wipe_osd_disk` in `references/maintenance-uninstall.md` zeroes the same offsets during uninstall; run this check after it too, because the host has no `ceph-volume`.

## FileStore (Legacy)

FileStore was removed from Rook in v1.9 and from Ceph in Quincy (v17). It is not an option for any current deployment. Only mention it if the user explicitly asks about migrating away from a very old installation.

## Disk Discovery in Rook CephCluster

Rook discovers OSD disks via the `CephCluster` `storage` spec. Use explicit device names for production, or `useAllDevices: true` with a `deviceFilter` for controlled auto-discovery.

```yaml
spec:
  storage:
    useAllNodes: false
    nodes:
    - name: "node-1"
      devices:
      - name: "/dev/disk/by-id/<disk-1>"
    - name: "node-2"
      devices:
      - name: "/dev/disk/by-id/<disk-2>"
```

## Label Storage Nodes

Label nodes that host OSDs so the Rook operator can place them correctly:

```bash
oc label node <node-1> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-2> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-3> node.ocs.openshift.io/storage=true --overwrite
```

## Validation

After the CephCluster CR is applied and OSDs are created, validate OSD health:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df
oc -n rook-ceph get pods -l app=rook-ceph-osd -o wide
```

Confirm:

- All OSDs are `up` and `in`.
- OSD weights are balanced.
- No OSDs are in `out` or `down` state unless deliberately being replaced.
- LVs created by `ceph-volume` exist on the intended disks.

## SNO OSD Considerations

On SNO, all OSDs run on the same node. Ceph can tolerate this if `allowMultiplePerNode: true` is set, but availability is limited by the single node. Use a reduced replica count and set `mon.count: 1` and `mgr.count: 1`.
