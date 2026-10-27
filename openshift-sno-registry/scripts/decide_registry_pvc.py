#!/usr/bin/env python3
"""Decide whether to create, keep, or refuse the registry PVC.

``create`` means no claim exists. ``reuse`` means the existing claim is
compatible and must not be replaced or shrunk. ``stop`` means the claim is
present but unsafe to adopt; the caller must not apply and must not delete it.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CLAIM_NAME = "image-registry-storage"
CLAIM_NAMESPACE = "openshift-image-registry"
MINIMUM_BYTES = 100 * 1024**3
_QUANTITY_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E)?")
_UNITS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
    "k": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "P": 1000**5,
    "E": 1000**6,
}


def parse_quantity(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = _QUANTITY_RE.fullmatch(value.strip())
    if match is None:
        return None
    number = match.group(1)
    suffix = match.group(2)
    multiplier = 1 if suffix is None else _UNITS[suffix]
    if "." in number:
        whole, fraction = number.split(".", 1)
        scale = 10 ** len(fraction)
        coefficient = int(whole) * scale + int(fraction)
    else:
        scale = 1
        coefficient = int(number)
    return (coefficient * multiplier) // scale


def decide_registry_pvc(pvc: dict | None, storage_class: str) -> dict[str, str]:
    if not isinstance(storage_class, str) or not storage_class:
        raise ValueError("storage class is required")
    if not pvc:
        return {"action": "create", "reason": "no claim exists"}
    if not isinstance(pvc, dict):
        return {"action": "stop", "reason": "claim document is not an object"}

    metadata = pvc.get("metadata")
    if not isinstance(metadata, dict):
        return {"action": "stop", "reason": "claim document is not an object"}
    if metadata.get("deletionTimestamp"):
        return {"action": "stop", "reason": "claim is being deleted"}
    if metadata.get("name") != CLAIM_NAME or metadata.get("namespace") != CLAIM_NAMESPACE:
        return {
            "action": "stop",
            "reason": "claim name or namespace does not match image-registry-storage",
        }

    status = pvc.get("status")
    if status is not None and not isinstance(status, dict):
        return {"action": "stop", "reason": "claim phase is not usable"}
    phase = status.get("phase") if isinstance(status, dict) else None
    if phase in {"Failed", "Lost"}:
        return {"action": "stop", "reason": "claim phase is not usable"}

    spec = pvc.get("spec")
    if not isinstance(spec, dict):
        return {"action": "stop", "reason": "claim document is not an object"}
    if spec.get("storageClassName") != storage_class:
        return {"action": "stop", "reason": "storage class does not match the selected class"}
    if spec.get("accessModes") != ["ReadWriteOnce"]:
        return {"action": "stop", "reason": "access mode is not ReadWriteOnce"}
    volume_mode = spec.get("volumeMode", "Filesystem")
    if volume_mode != "Filesystem":
        return {"action": "stop", "reason": "volume mode is not Filesystem"}

    resources = spec.get("resources")
    requests = resources.get("requests") if isinstance(resources, dict) else None
    request = requests.get("storage") if isinstance(requests, dict) else None
    size = parse_quantity(request)
    if size is None or size < MINIMUM_BYTES:
        return {"action": "stop", "reason": "requested capacity is below 100Gi"}
    return {
        "action": "reuse",
        "reason": "existing claim is compatible; do not apply a new size",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-class", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--missing", action="store_true")
    args = parser.parse_args(argv)

    pvc = None
    if args.input is not None:
        loaded = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            print(json.dumps({"action": "stop", "reason": "claim document is not an object"}))
            return 1
        pvc = loaded or None

    decision = decide_registry_pvc(pvc, args.storage_class)
    print(json.dumps(decision, sort_keys=True))
    return 0 if decision["action"] in {"create", "reuse"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
