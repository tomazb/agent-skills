#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
  containers:
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
  containers:
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

DEFAULT_STORAGE_CLASSES = {
    "rbd": "ocs-storagecluster-ceph-rbd",
    "cephfs": "ocs-storagecluster-cephfs",
}


def render_smoke_manifest(mode: str, namespace: str, storage_class: str, output: str) -> None:
    if mode == "rbd":
        yaml = RBD_SMOKE_YAML.format(namespace=namespace, storage_class=storage_class)
    elif mode == "cephfs":
        yaml = CEPHFS_SMOKE_YAML.format(namespace=namespace, storage_class=storage_class)
    else:
        raise ValueError(f"Unsupported mode: {mode}. Use 'rbd' or 'cephfs'.")
    Path(output).write_text(yaml, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render ODF smoke test manifests")
    parser.add_argument(
        "--mode", choices=["rbd", "cephfs"], required=True, help="Storage mode"
    )
    parser.add_argument("--namespace", default="odf-smoke", help="Smoke test namespace")
    parser.add_argument(
        "--storage-class",
        default=None,
        help=(
            "StorageClass name (defaults: rbd=ocs-storagecluster-ceph-rbd, "
            "cephfs=ocs-storagecluster-cephfs)"
        ),
    )
    parser.add_argument("--output", required=True, help="Output YAML path")
    args = parser.parse_args()

    storage_class = args.storage_class or DEFAULT_STORAGE_CLASSES[args.mode]
    render_smoke_manifest(args.mode, args.namespace, storage_class, args.output)
    print(f"Smoke manifest written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
