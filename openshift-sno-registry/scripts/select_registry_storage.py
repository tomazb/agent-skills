#!/usr/bin/env python3
"""Choose a filesystem StorageClass for the single-node internal registry."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

DEFAULT_ANNOTATIONS = (
    "storageclass.kubernetes.io/is-default-class",
    "storageclass.beta.kubernetes.io/is-default-class",
)

FILESYSTEM_PROVISIONERS = {
    "topolvm.io",
    "rbd.csi.ceph.com",
    "cephfs.csi.ceph.com",
    "rook-ceph.rbd.csi.ceph.com",
    "rook-ceph.cephfs.csi.ceph.com",
    "driver.longhorn.io",
    "ebs.csi.aws.com",
    "disk.csi.azure.com",
    "pd.csi.storage.gke.io",
    "cinder.csi.openstack.org",
    "nfs.csi.k8s.io",
    "kubernetes.io/aws-ebs",
    "kubernetes.io/gce-pd",
    "kubernetes.io/cinder",
    "kubernetes.io/azure-disk",
    "kubernetes.io/rbd",
}

ALLOWED_FSTYPES = {"ext4", "xfs"}
OBJECT_PROVISIONER_MARKERS = ("objectbucket.io", "noobaa.io")
NON_DYNAMIC_PROVISIONERS = {"kubernetes.io/no-provisioner"}


def load_storage_classes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    else:
        raise ValueError("expected a StorageClassList or a list of StorageClasses")
    classes = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("StorageClass entries must be objects")
        name = str((item.get("metadata") or {}).get("name") or "")
        if not name:
            raise ValueError("StorageClass is missing metadata.name")
        classes.append(item)
    return classes


def is_default(storage_class: dict[str, Any]) -> bool:
    annotations = (storage_class.get("metadata") or {}).get("annotations") or {}
    return any(annotations.get(key) == "true" for key in DEFAULT_ANNOTATIONS)


def filesystem_rejection(storage_class: dict[str, Any]) -> str | None:
    metadata = storage_class.get("metadata") or {}
    name = str(metadata.get("name") or "")
    provisioner = str(storage_class.get("provisioner") or "")
    parameters = storage_class.get("parameters") or {}
    fstype = str(parameters.get("csi.storage.k8s.io/fstype") or "")
    if name.endswith("-block"):
        return "class name marks it block-only"
    if provisioner in NON_DYNAMIC_PROVISIONERS or any(
        marker in provisioner for marker in OBJECT_PROVISIONER_MARKERS
    ):
        return "provisioner is not a dynamic filesystem volume provider"
    if fstype and fstype not in ALLOWED_FSTYPES:
        return f"fstype {fstype} is not ext4 or xfs"
    if fstype in ALLOWED_FSTYPES or provisioner in FILESYSTEM_PROVISIONERS:
        return None
    return "filesystem support is not declared"


def _warnings(storage_class: dict[str, Any]) -> list[str]:
    warnings = []
    if storage_class.get("reclaimPolicy", "Delete") == "Delete":
        warnings.append(
            "reclaimPolicy Delete destroys registry images when the PVC is deleted"
        )
    if storage_class.get("volumeBindingMode") == "WaitForFirstConsumer":
        warnings.append(
            "volumeBindingMode WaitForFirstConsumer keeps the PVC Pending until the registry pod is scheduled"
        )
    return warnings


def _use(storage_class: dict[str, Any], reason: str) -> dict[str, Any]:
    metadata = storage_class.get("metadata") or {}
    return {
        "action": "use-class",
        "storageClass": metadata.get("name"),
        "reason": reason,
        "precreatePVC": True,
        "reclaimPolicy": storage_class.get("reclaimPolicy", "Delete"),
        "volumeBindingMode": storage_class.get("volumeBindingMode", ""),
        "warnings": _warnings(storage_class),
    }


def _stop(reason: str) -> dict[str, Any]:
    return {
        "action": "stop",
        "storageClass": None,
        "reason": reason,
        "precreatePVC": False,
        "reclaimPolicy": "",
        "volumeBindingMode": "",
        "warnings": [],
    }


def select_registry_storage(
    storage_classes: list[dict[str, Any]],
    *,
    explicit_storage_class: str | None = None,
) -> dict[str, Any]:
    by_name = {(item.get("metadata") or {}).get("name"): item for item in storage_classes}
    if explicit_storage_class:
        chosen = by_name.get(explicit_storage_class)
        if chosen is None:
            return _stop(f"StorageClass {explicit_storage_class} was not found")
        rejection = filesystem_rejection(chosen)
        if rejection:
            return _stop(f"StorageClass {explicit_storage_class} is not usable: {rejection}")
        decision = _use(chosen, "using the StorageClass named for this deploy")
        defaults = [name for name, item in by_name.items() if is_default(item)]
        if len(defaults) > 1:
            decision["warnings"].append(
                "more than one StorageClass is marked default; the named class is still used"
            )
        return decision

    defaults = [item for item in storage_classes if is_default(item)]
    if len(defaults) > 1:
        names = ", ".join(str((item.get("metadata") or {}).get("name")) for item in defaults)
        return _stop(f"more than one default StorageClass: {names}")

    usable = [item for item in storage_classes if filesystem_rejection(item) is None]
    if len(defaults) == 1:
        default = defaults[0]
        rejection = filesystem_rejection(default)
        if rejection:
            name = (default.get("metadata") or {}).get("name")
            return _stop(
                f"default StorageClass {name} cannot provide a filesystem volume: {rejection}"
            )
        return _use(default, "using the only default filesystem StorageClass")

    if len(usable) == 1:
        return _use(usable[0], "no default StorageClass; using the only filesystem class")
    if not usable:
        return {
            "action": "install-lvms",
            "storageClass": None,
            "reason": "no filesystem StorageClass is available",
            "precreatePVC": False,
            "reclaimPolicy": "",
            "volumeBindingMode": "",
            "warnings": [],
        }
    names = ", ".join(str((item.get("metadata") or {}).get("name")) for item in usable)
    return _stop(f"no default StorageClass and more than one filesystem class: {names}")


def dump_decision(decision: dict[str, Any], output: TextIO) -> None:
    json.dump(decision, output, indent=2, sort_keys=True)
    output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        help="StorageClassList JSON. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--storage-class",
        help="Use this StorageClass instead of the default-selection rules.",
    )
    args = parser.parse_args(argv)

    try:
        if args.input:
            with open(args.input, encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            payload = json.load(sys.stdin)
        decision = select_registry_storage(
            load_storage_classes(payload),
            explicit_storage_class=args.storage_class,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    dump_decision(decision, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
