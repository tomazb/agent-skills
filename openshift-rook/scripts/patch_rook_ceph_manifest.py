#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def patch_rook_ceph_manifest(
    input_path: str,
    output_path: str,
    rook_version: str,
    ceph_version: str,
    rook_default: bool,
    replicas: int,
    mon_count: int,
    mgr_count: int,
    allow_multiple_per_node: bool,
) -> None:
    text = Path(input_path).read_text(encoding="utf-8")

    # Replace Rook version placeholders if any
    text = text.replace("ROOK_VERSION_PLACEHOLDER", rook_version)

    # Replace Ceph version placeholders if any
    text = text.replace("CEPH_VERSION_PLACEHOLDER", ceph_version)

    # Set mon count
    text = text.replace("MON_COUNT_PLACEHOLDER", str(mon_count))

    # Set mgr count
    text = text.replace("MGR_COUNT_PLACEHOLDER", str(mgr_count))

    # Set allowMultiplePerNode
    text = text.replace(
        "ALLOW_MULTIPLE_PER_NODE_PLACEHOLDER", "true" if allow_multiple_per_node else "false"
    )

    # Set default StorageClass annotation
    if rook_default:
        text = text.replace(
            'storageclass.kubernetes.io/is-default-class: "false"',
            'storageclass.kubernetes.io/is-default-class: "true"',
        )

    # Set replica count in StorageClass parameters
    text = text.replace("REPLICA_COUNT_PLACEHOLDER", str(replicas))

    Path(output_path).write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Rook Ceph manifests for OpenShift")
    parser.add_argument("--input", required=True, help="Path to input manifest YAML")
    parser.add_argument("--output", required=True, help="Path to output patched YAML")
    parser.add_argument("--rook-version", default="v1.14.0", help="Rook version to pin")
    parser.add_argument("--ceph-version", default="v18.2.2", help="Ceph image version to pin")
    parser.add_argument(
        "--rook-default", action="store_true", default=False, help="Set rook StorageClass as default"
    )
    parser.add_argument("--replicas", type=int, default=3, help="Replica count for pools")
    parser.add_argument("--mon-count", type=int, default=3, help="MON count")
    parser.add_argument("--mgr-count", type=int, default=2, help="MGR count")
    parser.add_argument(
        "--allow-multiple-per-node", action="store_true", default=False, help="Allow multiple per node"
    )
    args = parser.parse_args()

    patch_rook_ceph_manifest(
        args.input,
        args.output,
        args.rook_version,
        args.ceph_version,
        args.rook_default,
        args.replicas,
        args.mon_count,
        args.mgr_count,
        args.allow_multiple_per_node,
    )
    print(f"Patched manifest written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
