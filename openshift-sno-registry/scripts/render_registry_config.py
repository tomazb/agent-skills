#!/usr/bin/env python3
"""Render merge patches for the SNO internal image registry config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CLAIM_NAME = "image-registry-storage"


def managed_patch(*, clear_emptydir: bool) -> dict[str, Any]:
    storage: dict[str, Any] = {
        "managementState": "Managed",
        "pvc": {"claim": CLAIM_NAME},
    }
    if clear_emptydir:
        storage["emptyDir"] = None
    return {
        "spec": {
            "managementState": "Managed",
            "replicas": 1,
            "rolloutStrategy": "Recreate",
            "storage": storage,
        }
    }


def removed_patch() -> dict[str, Any]:
    return {"spec": {"managementState": "Removed"}}


def render_registry_config(management_state: str, *, clear_emptydir: bool = False) -> str:
    if management_state == "Managed":
        payload = managed_patch(clear_emptydir=clear_emptydir)
    elif management_state == "Removed":
        if clear_emptydir:
            raise ValueError("clear-emptydir applies only to the Managed patch")
        payload = removed_patch()
    else:
        raise ValueError(f"unsupported management state {management_state}")
    return json.dumps(payload, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--management-state", required=True, choices=["Managed", "Removed"])
    parser.add_argument(
        "--clear-emptydir",
        action="store_true",
        help="Delete spec.storage.emptyDir in the Managed merge patch",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        text = render_registry_config(
            args.management_state,
            clear_emptydir=args.clear_emptydir,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.write_text(text, encoding="utf-8")
    print(f"Rendered registry config patch to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
