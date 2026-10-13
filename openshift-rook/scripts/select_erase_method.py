#!/usr/bin/env python3
"""Choose the fastest erase that destroys the whole device.

The BlueStore offset wipe is never a candidate. It only clears label copies.

Reported durations come from ``nvme sanitize-log`` or from ``hdparm -I``.
``4294967295`` is not a duration. ``0`` means the controller expects the
operation to finish when the command completes.

A missing duration for a key change counts as finishing with the command,
because the media is not rewritten. Sanitize cryptographic erase wins a tie
with format cryptographic erase: on a controller with ``fna`` 4 and ``sanicap``
3, format (``--ses=2``) finished in 71 ms and left non-zero data, while
sanitize (``--sanact=4``) finished in 234 ms and read back as zeros. Reported
durations for a key change and for a device media erase are compared with
each other, so a faster reported media erase wins over a slower reported key
change. A reported overwrite or full-disk zero does not replace an untimed
device erase. Those rewrites are used only when no key change and no device
erase exist.

Virtio and other virtual disks are not NVMe sanitize targets. When
``write_zeroes_max_bytes`` is greater than 0, ``blkdiscard --zeroout`` blanks
the guest view and can unmap the range if discard is also advertised.
Otherwise writing zeroes across the device is the blank. ``fstrim`` is not a
candidate: it only discards free space on a mounted filesystem. Discard alone
is not a blank. A virtual NVMe controller stays in the NVMe class so its
``fna`` and ``sanicap`` are still used.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional

UNREPORTED = 4294967295

_RANK = {
    "sanitize-crypto": 0,
    "format-crypto": 1,
    "sata-enhanced": 2,
    "sanitize-block": 3,
    "sata-secure": 4,
    "write-zeroes": 5,
    "sanitize-overwrite": 6,
    "full-disk-zero": 7,
}

_COMMANDS = {
    "sanitize-crypto": "nvme sanitize <controller> --sanact=4 --ause",
    "format-crypto": "nvme format <namespace> --lbaf=<in-use-lbaf> --ses=2 --force",
    "sanitize-block": "nvme sanitize <controller> --sanact=2 --ause",
    "sanitize-overwrite": "nvme sanitize <controller> --sanact=3 --ause",
    "sata-enhanced": "hdparm --security-erase-enhanced",
    "sata-secure": "hdparm --security-erase",
    "write-zeroes": "blkdiscard --zeroout <disk>",
    "full-disk-zero": "dd if=/dev/zero",
}


def _measured(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    number = int(value)
    if number < 0:
        raise ValueError("estimate must be >= 0")
    if number == UNREPORTED:
        return None
    return number


def _candidate(method: str, seconds: Optional[int], key_change: bool) -> Dict[str, object]:
    measured = _measured(seconds)
    if measured is None and key_change:
        return {"method": method, "seconds": 0, "basis": "key-change", "rank": _RANK[method]}
    if measured is None:
        return {"method": method, "seconds": None, "basis": "unmeasured", "rank": _RANK[method]}
    return {"method": method, "seconds": measured, "basis": "reported", "rank": _RANK[method]}


_REWRITES = {"sanitize-overwrite", "full-disk-zero"}
_DEVICE_CLASSES = {"nvme", "virtio", "virtual", "physical"}
_VIRTUAL_CLASSES = {"virtio", "virtual"}


def _sort_key(item: Dict[str, object]) -> tuple:
    rewrite = item["method"] in _REWRITES
    if item["basis"] == "unmeasured":
        band = 3 if rewrite else 1
        return (band, 0, item["rank"])
    if rewrite:
        return (2, item["seconds"], item["rank"])
    return (0, item["seconds"], item["rank"])


def choose_erase_method(
    fna: int = 0,
    sanicap: int = 0,
    crypto_seconds: Optional[int] = None,
    block_seconds: Optional[int] = None,
    overwrite_seconds: Optional[int] = None,
    secure_erase_minutes: Optional[int] = None,
    enhanced_erase_minutes: Optional[int] = None,
    sata_secure: bool = False,
    sata_enhanced: bool = False,
    zero_seconds: Optional[int] = None,
    nn: Optional[int] = None,
    write_zeroes_max_bytes: Optional[int] = None,
    device_class: Optional[str] = None,
) -> Dict[str, object]:
    """Return the fastest proper erase for these identify and timing inputs."""
    if device_class is not None and device_class not in _DEVICE_CLASSES:
        raise ValueError("device_class must be nvme, virtio, virtual, or physical")
    if nn is not None and int(nn) != 1:
        raise ValueError("nn must be 1; format and sanitize can cover every namespace")

    fna = int(fna)
    sanicap = int(sanicap)
    if device_class in _VIRTUAL_CLASSES:
        # A virtio or generic virtual disk does not take NVMe or ATA erase commands.
        fna = 0
        sanicap = 0
        secure_erase_minutes = None
        enhanced_erase_minutes = None
        sata_secure = False
        sata_enhanced = False
    key_changes: List[Dict[str, object]] = []
    device_media: List[Dict[str, object]] = []
    rewrites: List[Dict[str, object]] = []

    if sanicap & 1:
        key_changes.append(_candidate("sanitize-crypto", crypto_seconds, True))
    if fna & 4:
        key_changes.append(_candidate("format-crypto", None, True))
    if sanicap & 2:
        device_media.append(_candidate("sanitize-block", block_seconds, False))
    if write_zeroes_max_bytes is not None and int(write_zeroes_max_bytes) > 0:
        device_media.append(_candidate("write-zeroes", None, False))
    if enhanced_erase_minutes is not None or sata_enhanced:
        minutes = None if enhanced_erase_minutes is None else int(enhanced_erase_minutes) * 60
        device_media.append(_candidate("sata-enhanced", minutes, False))
    if secure_erase_minutes is not None or sata_secure:
        minutes = None if secure_erase_minutes is None else int(secure_erase_minutes) * 60
        device_media.append(_candidate("sata-secure", minutes, False))
    if sanicap & 4:
        rewrites.append(_candidate("sanitize-overwrite", overwrite_seconds, False))
    rewrites.append(_candidate("full-disk-zero", zero_seconds, False))

    primary = key_changes + device_media
    pool = primary if primary else rewrites
    chosen = min(pool, key=_sort_key)
    if chosen["method"] in ("sanitize-crypto", "format-crypto"):
        pool_name = "key-change"
    elif chosen["method"] in _REWRITES:
        pool_name = "rewrite"
    else:
        pool_name = "device-media"

    note = ""
    if device_class in _VIRTUAL_CLASSES and chosen["method"] == "full-disk-zero":
        note = "writing zeroes is the blank for this virtual disk"
    elif chosen["method"] == "write-zeroes":
        note = "write zeroes advertised; blkdiscard --zeroout blanks and can unmap"

    return {
        "method": chosen["method"],
        "seconds": chosen["seconds"],
        "basis": chosen["basis"],
        "pool": pool_name,
        "device_class": device_class or "",
        "command": _COMMANDS[str(chosen["method"])],
        "considered": [item["method"] for item in pool],
        "proper": True,
        "rejected": ["bluestore-offset-wipe"],
        "note": note,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Choose the fastest proper device erase.")
    parser.add_argument("--fna", type=int, default=0)
    parser.add_argument("--sanicap", type=int, default=0)
    parser.add_argument("--nn", type=int)
    parser.add_argument("--crypto-seconds", type=int)
    parser.add_argument("--block-seconds", type=int)
    parser.add_argument("--overwrite-seconds", type=int)
    parser.add_argument("--secure-erase-minutes", type=int)
    parser.add_argument("--enhanced-erase-minutes", type=int)
    parser.add_argument("--sata-secure", action="store_true")
    parser.add_argument("--sata-enhanced", action="store_true")
    parser.add_argument("--zero-seconds", type=int)
    parser.add_argument("--write-zeroes-max-bytes", type=int)
    parser.add_argument("--device-class", choices=sorted(_DEVICE_CLASSES))
    args = parser.parse_args(argv)
    try:
        result = choose_erase_method(
            fna=args.fna,
            sanicap=args.sanicap,
            crypto_seconds=args.crypto_seconds,
            block_seconds=args.block_seconds,
            overwrite_seconds=args.overwrite_seconds,
            secure_erase_minutes=args.secure_erase_minutes,
            enhanced_erase_minutes=args.enhanced_erase_minutes,
            sata_secure=args.sata_secure,
            sata_enhanced=args.sata_enhanced,
            zero_seconds=args.zero_seconds,
            nn=args.nn,
            write_zeroes_max_bytes=args.write_zeroes_max_bytes,
            device_class=args.device_class,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
