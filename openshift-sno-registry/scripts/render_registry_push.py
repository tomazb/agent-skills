#!/usr/bin/env python3
"""Render the in-cluster push used to prove registry PVC writes."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

DNS1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

PUSH_TEMPLATE = """\
apiVersion: v1
kind: ServiceAccount
metadata:
  name: registry-smoke
  namespace: {namespace}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: registry-smoke-builder
  namespace: {namespace}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:image-builder
subjects:
  - kind: ServiceAccount
    name: registry-smoke
    namespace: {namespace}
---
apiVersion: v1
kind: Pod
metadata:
  labels:
    app.kubernetes.io/part-of: registry-smoke
  name: registry-smoke-push
  namespace: {namespace}
spec:
  restartPolicy: Never
  serviceAccountName: registry-smoke
  containers:
    - name: push
      image: registry.access.redhat.com/ubi9/skopeo:latest
      command: ["sh", "-c"]
      args:
        - |
          set -eu
          mkdir -p /tmp/certs
          cp /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt /tmp/certs/service-ca.crt
          token=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
          skopeo copy --remove-signatures --dest-tls-verify=true --dest-cert-dir=/tmp/certs \\
            --dest-creds="registry-smoke:${{token}}" \\
            docker://{source} \\
            docker://{destination}
          echo registry-push-ok
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop:
            - ALL
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
"""


def parse_namespace(value: str) -> str:
    if len(value) > 63 or DNS1123_LABEL.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(f"namespace must be a DNS-1123 label, got {value!r}")
    return value


def parse_image(value: str) -> str:
    if IMAGE_RE.fullmatch(value) is None or "://" in value:
        raise argparse.ArgumentTypeError(
            f"image must be a registry reference without a scheme, got {value!r}"
        )
    return value


def render_registry_push(namespace: str, source: str, destination: str) -> str:
    parse_namespace(namespace)
    parse_image(source)
    parse_image(destination)
    return PUSH_TEMPLATE.format(namespace=namespace, source=source, destination=destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True, type=parse_namespace)
    parser.add_argument("--source", required=True, type=parse_image)
    parser.add_argument("--destination", required=True, type=parse_image)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    args.output.write_text(
        render_registry_push(args.namespace, args.source, args.destination),
        encoding="utf-8",
    )
    print(f"Rendered registry push manifest to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
