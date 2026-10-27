#!/usr/bin/env python3
"""Render a restricted pod that pulls one image back from the internal registry."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

DNS1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MARKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,62}$")

POD_TEMPLATE = """\
apiVersion: v1
kind: Pod
metadata:
  labels:
    app.kubernetes.io/part-of: registry-smoke
  name: registry-smoke-pull
  namespace: {namespace}
spec:
  automountServiceAccountToken: false
  containers:
    - name: pull
      image: {image}
      command: ["sh", "-c", "echo {marker}"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop:
            - ALL
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
  restartPolicy: Never
"""


def parse_namespace(value: str) -> str:
    if len(value) > 63 or DNS1123_LABEL.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(f"namespace must be a DNS-1123 label, got {value!r}")
    return value


def parse_image(value: str) -> str:
    if not value or any(char.isspace() for char in value) or "://" in value:
        raise argparse.ArgumentTypeError(f"image must be a registry reference without a scheme, got {value!r}")
    return value


def parse_marker(value: str) -> str:
    if MARKER_RE.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(f"marker must be a short token, got {value!r}")
    return value


def render_registry_smoke(namespace: str, image: str, marker: str) -> str:
    parse_namespace(namespace)
    parse_image(image)
    parse_marker(marker)
    return POD_TEMPLATE.format(namespace=namespace, image=image, marker=marker)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True, type=parse_namespace)
    parser.add_argument("--image", required=True, type=parse_image)
    parser.add_argument("--marker", default="registry-smoke-ok", type=parse_marker)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    args.output.write_text(
        render_registry_smoke(args.namespace, args.image, args.marker),
        encoding="utf-8",
    )
    print(f"Rendered registry smoke pod to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
