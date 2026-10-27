#!/usr/bin/env python3
"""Render the ReadWriteOnce PVC the internal registry mounts on SNO."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DNS1123_SUBDOMAIN = re.compile(
    r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
)
SIZE_RE = re.compile(r"^([1-9][0-9]*)Gi$")
MINIMUM_SIZE_GI = 100

PVC_TEMPLATE = """\
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: image-registry-storage
  namespace: openshift-image-registry
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: {storage_class}
  volumeMode: Filesystem
  resources:
    requests:
      storage: {size}
"""


def parse_size(value: str) -> str:
    match = SIZE_RE.fullmatch(value)
    if match is None or int(match.group(1)) < MINIMUM_SIZE_GI:
        raise argparse.ArgumentTypeError(
            f"size must be at least {MINIMUM_SIZE_GI}Gi, got {value!r}"
        )
    return value


def parse_storage_class(value: str) -> str:
    if len(value) > 253 or DNS1123_SUBDOMAIN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            f"storage class must be a DNS-1123 subdomain, got {value!r}"
        )
    return value


def render_registry_pvc(storage_class: str, size: str) -> str:
    parse_storage_class(storage_class)
    parse_size(size)
    return PVC_TEMPLATE.format(storage_class=storage_class, size=size)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-class", required=True, type=parse_storage_class)
    parser.add_argument("--size", default="100Gi", type=parse_size)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    args.output.write_text(
        render_registry_pvc(args.storage_class, args.size),
        encoding="utf-8",
    )
    print(f"Rendered registry PVC to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except argparse.ArgumentTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
