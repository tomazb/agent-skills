#!/usr/bin/env python3
"""Render a restricted smoke manifest for LVMS (filesystem or block mode).

Produces a Namespace, PVC, and Pod that are compatible with OpenShift's
restricted-v2 PodSecurity. The pod runs as non-root with no capabilities.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc


FS_POD = """\
apiVersion: v1
kind: Pod
metadata:
  name: lvms-smoke-writer
  namespace: {namespace}
spec:
  containers:
    - name: writer
      image: registry.access.redhat.com/ubi9/ubi-minimal:latest
      command: ["sh", "-c", "echo ok > /data/probe && sleep 3600"]
      volumeMounts:
        - name: data
          mountPath: /data
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop:
            - ALL
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: lvms-smoke-pvc
  restartPolicy: Never
"""

BLOCK_POD = """\
apiVersion: v1
kind: Pod
metadata:
  name: lvms-smoke-writer
  namespace: {namespace}
spec:
  containers:
    - name: writer
      image: registry.access.redhat.com/ubi9/ubi-minimal:latest
      command: ["sh", "-c", "test -b /dev/block-device && echo 'block device present' && sleep 3600"]
      volumeDevices:
        - name: block-data
          devicePath: /dev/block-device
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop:
            - ALL
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
  volumes:
    - name: block-data
      persistentVolumeClaim:
        claimName: lvms-smoke-pvc
  restartPolicy: Never
"""


FS_PVC = """\
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: lvms-smoke-pvc
  namespace: {namespace}
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: {storage_class}
  resources:
    requests:
      storage: 1Gi
"""

BLOCK_PVC = """\
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: lvms-smoke-pvc
  namespace: {namespace}
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: {storage_class}
  volumeMode: Block
  resources:
    requests:
      storage: 1Gi
"""


NAMESPACE = """\
apiVersion: v1
kind: Namespace
metadata:
  name: {namespace}
"""


MODES = {
    "fs": (FS_PVC, FS_POD),
    "block": (BLOCK_PVC, BLOCK_POD),
}


def render(mode: str, namespace: str, storage_class: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES.keys())}")
    pvc_template, pod_template = MODES[mode]
    parts = [
        NAMESPACE.format(namespace=namespace),
        pvc_template.format(namespace=namespace, storage_class=storage_class),
        pod_template.format(namespace=namespace),
    ]
    return "---\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render LVMS smoke manifest")
    parser.add_argument("--mode", required=True, choices=["fs", "block"], help="Smoke test mode")
    parser.add_argument("--namespace", required=True, help="Smoke test namespace")
    parser.add_argument("--storage-class", required=True, help="StorageClass name")
    parser.add_argument("--output", required=True, type=Path, help="Output manifest path")
    args = parser.parse_args()

    manifest = render(args.mode, args.namespace, args.storage_class)
    args.output.write_text(manifest, encoding="utf-8")
    print(f"Rendered smoke manifest to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
