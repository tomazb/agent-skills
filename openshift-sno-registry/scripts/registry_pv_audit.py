#!/usr/bin/env python3
"""Print PVs still bound to the registry claim and exit 1 when any remain.

A PersistentVolume matches only when both ``claimRef.name`` and
``claimRef.namespace`` point at ``image-registry-storage`` in
``openshift-image-registry``. The same claim name in another namespace is
not this registry's disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CLAIM_NAME = "image-registry-storage"
CLAIM_NAMESPACE = "openshift-image-registry"


def leftover_registry_pvs(document: dict) -> list[str]:
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        raise ValueError("PV list must be an object with an items array")
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        claim_ref = ((item.get("spec") or {}).get("claimRef") or {})
        if not isinstance(claim_ref, dict):
            continue
        if claim_ref.get("name") != CLAIM_NAME or claim_ref.get("namespace") != CLAIM_NAMESPACE:
            continue
        metadata = item.get("metadata") or {}
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="PV list JSON. Reads stdin when omitted.")
    args = parser.parse_args(argv)
    raw = args.input.read_text(encoding="utf-8") if args.input is not None else sys.stdin.read()
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        print("PV list must be a JSON object", file=sys.stderr)
        return 1
    names = leftover_registry_pvs(loaded)
    if names:
        print("\n".join(names))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
