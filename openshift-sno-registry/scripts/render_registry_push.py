#!/usr/bin/env python3
"""Render the in-cluster push used to prove registry PVC writes.

The service-account token is read inside the pod and passed to
``skopeo --dest-creds``. Destination is limited to the OpenShift internal
registry service in the smoke namespace. The source and skopeo images are
pull references supplied by the caller and are not credential targets.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from internal_image import ImageReferenceError, parse_internal_image, parse_source_image

DNS1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

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
      image: {skopeo_image}
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
    if not isinstance(value, str) or len(value) > 63 or DNS1123_LABEL.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("namespace must be a DNS-1123 label")
    return value


def render_registry_push(namespace: str, source: str, destination: str, skopeo_image: str) -> str:
    parse_namespace(namespace)
    source = parse_source_image(source)
    destination = parse_internal_image(destination, namespace)
    skopeo_image = parse_source_image(skopeo_image)
    return PUSH_TEMPLATE.format(
        namespace=namespace,
        source=source,
        destination=destination,
        skopeo_image=skopeo_image,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True, type=parse_namespace)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--skopeo-image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        body = render_registry_push(
            args.namespace,
            args.source,
            args.destination,
            args.skopeo_image,
        )
    except ImageReferenceError as exc:
        parser.error(str(exc))
    args.output.write_text(body, encoding="utf-8")
    print(f"Rendered registry push manifest to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
