#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc


@dataclass(frozen=True)
class SmokeOptions:
    mode: str
    namespace: Optional[str] = None
    storage_class: str = "longhorn"
    pvc_name: str = "data"
    pod_name: str = "writer"
    size: str = "1Gi"
    image: str = "registry.access.redhat.com/ubi9/ubi-minimal:latest"


def default_namespace(mode: str) -> str:
    if mode not in {"v1", "v2"}:
        raise ValueError("mode must be v1 or v2")
    return f"longhorn-{mode}-smoke"


def render_smoke_documents(options: SmokeOptions) -> list[dict[str, Any]]:
    namespace = options.namespace or default_namespace(options.mode)
    if options.mode not in {"v1", "v2"}:
        raise ValueError("mode must be v1 or v2")

    labels = {
        "app.kubernetes.io/name": "longhorn-smoke",
        "longhorn.io/data-engine": options.mode,
    }
    return [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": namespace,
                "labels": labels,
            },
        },
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": options.pvc_name,
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": options.storage_class,
                "volumeMode": "Filesystem",
                "resources": {"requests": {"storage": options.size}},
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": options.pod_name,
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "restartPolicy": "Always",
                "terminationGracePeriodSeconds": 5,
                "securityContext": {
                    "runAsNonRoot": True,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "writer",
                        "image": options.image,
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["/bin/sh", "-c"],
                        "args": [
                            "set -eu\n"
                            "while true; do\n"
                            "  date -Iseconds > /data/probe\n"
                            "  cat /data/probe\n"
                            "  sleep 30\n"
                            "done\n"
                        ],
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                    }
                ],
                "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": options.pvc_name}}],
            },
        },
    ]


def dump_documents(docs: list[dict[str, Any]]) -> str:
    return "---\n" + "\n---\n".join(yaml.safe_dump(doc, sort_keys=False).rstrip() for doc in docs) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a restricted-PodSecurity-compatible Longhorn smoke manifest."
    )
    parser.add_argument("--mode", required=True, choices=["v1", "v2"], help="Longhorn data engine label.")
    parser.add_argument("--namespace", help="Smoke namespace. Defaults to longhorn-<mode>-smoke.")
    parser.add_argument("--storage-class", default="longhorn", help="StorageClass to bind.")
    parser.add_argument("--pvc-name", default="data", help="PVC name.")
    parser.add_argument("--pod-name", default="writer", help="Writer pod name.")
    parser.add_argument("--size", default="1Gi", help="PVC requested size.")
    parser.add_argument("--image", default=SmokeOptions.image, help="Writer container image.")
    parser.add_argument("--output", default="-", type=Path, help="Output path, or - for stdout.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = dump_documents(
            render_smoke_documents(
                SmokeOptions(
                    mode=args.mode,
                    namespace=args.namespace,
                    storage_class=args.storage_class,
                    pvc_name=args.pvc_name,
                    pod_name=args.pod_name,
                    size=args.size,
                    image=args.image,
                )
            )
        )
    except (ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if str(args.output) == "-":
        sys.stdout.write(manifest)
    else:
        args.output.write_text(manifest, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
