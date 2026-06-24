#!/usr/bin/env python3
"""Patch LVMS manifests for OpenShift/OKD with YAML-aware editing.

Supports patching LVMCluster CRs for device class settings, thin pool config,
node selectors, and StorageClass parameters. Used for install-time manifest
preparation before `oc apply`.
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

LVMCLUSTER_KIND = "LVMCluster"
STORAGECLASS_KIND = "StorageClass"


def _find_documents(docs: list[Any], *, kind: str) -> list[dict[str, Any]]:
    return [
        doc
        for doc in docs
        if isinstance(doc, dict) and doc.get("kind") == kind
    ]


def _patch_lvmcluster_thin_pool(
    doc: dict[str, Any],
    *,
    overprovision_ratio: int | None = None,
    size_percent: int | None = None,
) -> bool:
    if overprovision_ratio is None and size_percent is None:
        return False
    spec = doc.get("spec", {})
    if not isinstance(spec, dict):
        return False
    storage = spec.get("storage", {})
    if not isinstance(storage, dict):
        return False
    device_classes = storage.get("deviceClasses", [])
    if not isinstance(device_classes, list):
        return False
    patched = False
    for dc in device_classes:
        if not isinstance(dc, dict):
            continue
        thin_pool = dc.setdefault("thinPoolConfig", {})
        if not isinstance(thin_pool, dict):
            continue
        if overprovision_ratio is not None:
            thin_pool["overprovisionRatio"] = overprovision_ratio
            patched = True
        if size_percent is not None:
            thin_pool["sizePercent"] = size_percent
            patched = True
    return patched


def _patch_lvmcluster_device_selector(
    doc: dict[str, Any],
    *,
    paths: list[str] | None = None,
    force_wipe: bool | None = None,
) -> bool:
    if paths is None and force_wipe is None:
        return False
    spec = doc.get("spec", {})
    if not isinstance(spec, dict):
        return False
    storage = spec.get("storage", {})
    if not isinstance(storage, dict):
        return False
    device_classes = storage.get("deviceClasses", [])
    if not isinstance(device_classes, list):
        return False
    patched = False
    for dc in device_classes:
        if not isinstance(dc, dict):
            continue
        device_selector = dc.setdefault("deviceSelector", {})
        if not isinstance(device_selector, dict):
            continue
        if paths is not None:
            device_selector["paths"] = paths
            patched = True
        if force_wipe is not None:
            device_selector["forceWipeDevicesAndDestroyAllData"] = force_wipe
            patched = True
    return patched


def _patch_lvmcluster_default(doc: dict[str, Any], default: bool) -> bool:
    spec = doc.get("spec", {})
    if not isinstance(spec, dict):
        return False
    storage = spec.get("storage", {})
    if not isinstance(storage, dict):
        return False
    device_classes = storage.get("deviceClasses", [])
    if not isinstance(device_classes, list):
        return False
    patched = False
    for dc in device_classes:
        if not isinstance(dc, dict):
            continue
        dc["default"] = default
        patched = True
    return patched


def _patch_storageclass_fs_type(doc: dict[str, Any], fs_type: str | None) -> bool:
    if not isinstance(doc, dict) or doc.get("kind") != STORAGECLASS_KIND:
        return False
    parameters = doc.setdefault("parameters", {})
    if not isinstance(parameters, dict):
        return False
    if fs_type is not None:
        parameters["csi.storage.k8s.io/fstype"] = fs_type
        return True
    return False


def patch_documents(
    docs: list[Any],
    *,
    overprovision_ratio: int | None = None,
    size_percent: int | None = None,
    device_paths: list[str] | None = None,
    force_wipe: bool | None = None,
    device_class_default: bool | None = None,
    storage_class_fs_type: str | None = None,
) -> tuple[list[Any], dict[str, int]]:
    report = {
        "lvmcluster_patched": 0,
        "storageclass_patched": 0,
    }
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") == LVMCLUSTER_KIND:
            patched = False
            if _patch_lvmcluster_thin_pool(doc, overprovision_ratio=overprovision_ratio, size_percent=size_percent):
                patched = True
            if _patch_lvmcluster_device_selector(doc, paths=device_paths, force_wipe=force_wipe):
                patched = True
            if device_class_default is not None and _patch_lvmcluster_default(doc, device_class_default):
                patched = True
            if patched:
                report["lvmcluster_patched"] += 1
        elif doc.get("kind") == STORAGECLASS_KIND:
            if _patch_storageclass_fs_type(doc, fs_type=storage_class_fs_type):
                report["storageclass_patched"] += 1
    return docs, report


def load_documents(path: Path) -> list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return list(yaml.safe_load_all(handle))


def dump_documents(docs: list[Any]) -> str:
    chunks = []
    for doc in docs:
        if doc is None:
            chunks.append("")
        else:
            chunks.append(yaml.safe_dump(doc, sort_keys=False).rstrip())
    return "---\n" + "\n---\n".join(chunks).rstrip() + "\n"


def parse_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected integer, got {value!r}")


def parse_size_percent(value: str) -> int:
    # LVMS thinPoolConfig.sizePercent is constrained to 10-90 by the CRD schema.
    parsed = parse_int(value)
    if not 10 <= parsed <= 90:
        raise argparse.ArgumentTypeError(f"size-percent must be between 10 and 90, got {parsed}")
    return parsed


def parse_overprovision_ratio(value: str) -> int:
    # LVMS thinPoolConfig.overprovisionRatio must be a positive integer.
    parsed = parse_int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"overprovision-ratio must be >= 1, got {parsed}")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch LVMS manifests for OpenShift/OKD")
    parser.add_argument("--input", required=True, type=Path, help="Input manifest path")
    parser.add_argument("--output", required=True, type=Path, help="Output manifest path")
    parser.add_argument("--overprovision-ratio", type=parse_overprovision_ratio, help="Thin pool over-provisioning ratio (>= 1)")
    parser.add_argument("--size-percent", type=parse_size_percent, help="Thin pool size percent of VG (10-90)")
    parser.add_argument("--device-paths", nargs="+", help="Disk paths for deviceSelector")
    parser.add_argument("--force-wipe", choices=["true", "false"], help="Enable forceWipeDevicesAndDestroyAllData")
    parser.add_argument("--device-class-default", choices=["true", "false"], help="Set default flag on deviceClasses")
    parser.add_argument("--storage-class-fs-type", choices=["ext4", "xfs"], help="Set StorageClass filesystem type")
    args = parser.parse_args()

    docs = load_documents(args.input)
    force_wipe_bool = {"true": True, "false": False}.get(args.force_wipe) if args.force_wipe else None
    device_class_default_bool = {"true": True, "false": False}.get(args.device_class_default) if args.device_class_default else None

    docs, report = patch_documents(
        docs,
        overprovision_ratio=args.overprovision_ratio,
        size_percent=args.size_percent,
        device_paths=args.device_paths,
        force_wipe=force_wipe_bool,
        device_class_default=device_class_default_bool,
        storage_class_fs_type=args.storage_class_fs_type,
    )

    args.output.write_text(dump_documents(docs), encoding="utf-8")
    print(f"Patched {report['lvmcluster_patched']} LVMCluster(s), {report['storageclass_patched']} StorageClass(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
