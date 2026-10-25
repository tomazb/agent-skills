#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

RBD_SMOKE_YAML = """\
apiVersion: v1
kind: Namespace
metadata:
  name: {namespace}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: rbd-smoke-pvc
  namespace: {namespace}
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: {storage_class}
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: rbd-smoke-writer
  namespace: {namespace}
spec:
  {node_affinity_block}containers:
  - name: writer
    image: registry.access.redhat.com/ubi9/ubi-minimal
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: data
      mountPath: /data
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
      runAsNonRoot: true
      seccompProfile:
        type: RuntimeDefault
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: rbd-smoke-pvc
"""

CEPHFS_SMOKE_YAML = """\
apiVersion: v1
kind: Namespace
metadata:
  name: {namespace}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cephfs-smoke-pvc
  namespace: {namespace}
spec:
  accessModes:
  - ReadWriteMany
  storageClassName: {storage_class}
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: cephfs-smoke-writer
  namespace: {namespace}
spec:
  {node_affinity_block}containers:
  - name: writer
    image: registry.access.redhat.com/ubi9/ubi-minimal
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: data
      mountPath: /data
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
      runAsNonRoot: true
      seccompProfile:
        type: RuntimeDefault
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: cephfs-smoke-pvc
"""

# Matches Kubernetes IsDNS1123Subdomain: max 253 characters total, not 63 per label.
_DNS1123_SUBDOMAIN_RE = re.compile(
    r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*"
)


def _node_affinity_block(node_name: str | None) -> str:
    """Constrain scheduling to a Node by name without bypassing the scheduler.

    Return an empty string when no target node was requested. This keeps
    WaitForFirstConsumer volume binding compatible with pinned smoke tests.
    """
    if not node_name:
        return ""
    if len(node_name) > 253 or _DNS1123_SUBDOMAIN_RE.fullmatch(node_name) is None:
        raise ValueError(f"invalid node name: {node_name}")
    # matchFields uses the Node object's name, not a potentially different hostname label.
    # Unlike spec.nodeName, required node affinity still uses the scheduler (including WFFC).
    return (
        "affinity:\n"
        "    nodeAffinity:\n"
        "      requiredDuringSchedulingIgnoredDuringExecution:\n"
        "        nodeSelectorTerms:\n"
        "        - matchFields:\n"
        "          - key: metadata.name\n"
        "            operator: In\n"
        "            values:\n"
        f"            - {node_name}\n"
        "  "
    )


def render_smoke_manifest(
    mode: str,
    namespace: str,
    storage_class: str,
    output: str,
    node_name: str | None = None,
) -> None:
    """Write a PVC-writer Pod manifest, optionally pinned by scheduler affinity."""
    node_affinity_block = _node_affinity_block(node_name)
    if mode == "rbd":
        yaml = RBD_SMOKE_YAML.format(
            namespace=namespace, storage_class=storage_class, node_affinity_block=node_affinity_block
        )
    elif mode == "cephfs":
        yaml = CEPHFS_SMOKE_YAML.format(
            namespace=namespace, storage_class=storage_class, node_affinity_block=node_affinity_block
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}. Use 'rbd' or 'cephfs'.")
    Path(output).write_text(yaml, encoding="utf-8")


def main() -> int:
    """Parse smoke-test options and render the requested manifest."""
    parser = argparse.ArgumentParser(description="Render Rook Ceph smoke test manifests")
    parser.add_argument(
        "--mode", choices=["rbd", "cephfs"], required=True, help="Storage mode"
    )
    parser.add_argument("--namespace", default="rook-smoke", help="Smoke test namespace")
    parser.add_argument(
        "--storage-class", default=None, help="StorageClass name (defaults: rbd=rook-ceph-block, cephfs=rook-cephfs)"
    )
    parser.add_argument("--output", required=True, help="Output YAML path")
    parser.add_argument(
        "--node-name",
        default=None,
        help="Constrain scheduling to this Node's metadata.name (supports WaitForFirstConsumer).",
    )
    args = parser.parse_args()

    storage_class = args.storage_class or ("rook-ceph-block" if args.mode == "rbd" else "rook-cephfs")
    render_smoke_manifest(
        args.mode, args.namespace, storage_class, args.output, node_name=args.node_name
    )
    print(f"Smoke manifest written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
