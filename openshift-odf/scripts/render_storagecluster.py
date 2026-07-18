#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

STORAGECLUSTER_TEMPLATE = """\
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: {name}
  namespace: {namespace}
spec:
  manageNodes: false
  monDataDirHostPath: /var/lib/rook
  storageDeviceSets:
  - name: ocs-deviceset
    count: {count}
    replica: {replica}
    portable: false
    dataPVCTemplate:
      spec:
        accessModes:
        - ReadWriteOnce
        volumeMode: Block
        storageClassName: {local_storage_class}
        resources:
          requests:
            # LSO localblock PVs represent whole disks; "1" intentionally
            # requests the smallest positive capacity so any disk-sized PV can bind.
            storage: "1"
  managedResources:
    cephBlockPools:
      reconcileStrategy: manage
"""


def render_storagecluster(
    name: str,
    namespace: str,
    local_storage_class: str,
    replica: int,
    count: int,
    output: str,
) -> None:
    """Render an ODF StorageCluster CR. replica=1 is SNO; replica=3 is multi-node."""
    if replica not in {1, 3}:
        raise ValueError("replica must be 1 or 3 (SNO or multi-node)")
    if count < 1:
        raise ValueError("count must be >= 1")
    yaml = STORAGECLUSTER_TEMPLATE.format(
        name=name,
        namespace=namespace,
        local_storage_class=local_storage_class,
        replica=replica,
        count=count,
    )
    Path(output).write_text(yaml, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render an ODF StorageCluster CR for internal-attached deployments"
    )
    parser.add_argument("--name", default="ocs-storagecluster", help="StorageCluster name")
    parser.add_argument(
        "--namespace", default="openshift-storage", help="Target namespace"
    )
    parser.add_argument(
        "--local-storage-class",
        default="localblock",
        help="Local Storage Operator StorageClass backing the device set",
    )
    parser.add_argument(
        "--replica",
        type=int,
        default=3,
        help="OSD replica per device set (3 multi-node, 1 SNO)",
    )
    parser.add_argument(
        "--count", type=int, default=1, help="Number of device sets (capacity units)"
    )
    parser.add_argument("--output", required=True, help="Output YAML path")
    args = parser.parse_args()

    render_storagecluster(
        args.name,
        args.namespace,
        args.local_storage_class,
        args.replica,
        args.count,
        args.output,
    )
    print(f"StorageCluster manifest written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
