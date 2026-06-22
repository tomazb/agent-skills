#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc

LONGHORN_NAMESPACE = "longhorn-system"
STORAGECLASS_CONFIGMAP = "longhorn-storageclass"
STORAGECLASS_KEY = "storageclass.yaml"
DEFAULT_SETTING_CONFIGMAP = "longhorn-default-setting"
DEFAULT_SETTING_KEY = "default-setting.yaml"


@dataclass(frozen=True)
class PatchOptions:
    mode: str
    oauth_proxy_image: Optional[str] = None
    longhorn_default: bool = False
    replicas: int = 1
    v1_data_path: str = "/var/lib/longhorn/"
    keep_v1_engine: bool = False
    v2_disk_selector: str = "v2"
    v2_memory_size: str = "2048"


def _metadata(doc: dict[str, Any]) -> dict[str, Any]:
    value = doc.setdefault("metadata", {})
    if not isinstance(value, dict):
        raise ValueError(f"{doc.get('kind', '<unknown>')}: metadata is not a mapping")
    return value


def _data(doc: dict[str, Any]) -> dict[str, Any]:
    value = doc.setdefault("data", {})
    if not isinstance(value, dict):
        raise ValueError(f"{doc.get('kind', '<unknown>')}: data is not a mapping")
    return value


def _matches(doc: Any, *, kind: str, name: str) -> bool:
    if not isinstance(doc, dict) or doc.get("kind") != kind:
        return False
    metadata = doc.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("name") != name:
        return False
    namespace = metadata.get("namespace")
    return namespace in (None, LONGHORN_NAMESPACE)


def _embedded_mapping(configmap: dict[str, Any], key: str) -> dict[str, Any]:
    data = _data(configmap)
    text = data.get(key)
    if not isinstance(text, str) or not text.strip():
        name = _metadata(configmap).get("name", "<unknown>")
        raise ValueError(f"ConfigMap/{name} is missing non-empty data.{key}")
    parsed = yaml.safe_load(text) or {}
    if not isinstance(parsed, dict):
        name = _metadata(configmap).get("name", "<unknown>")
        raise ValueError(f"ConfigMap/{name} data.{key} must contain a YAML mapping")
    return parsed


def _store_embedded_mapping(configmap: dict[str, Any], key: str, value: dict[str, Any]) -> None:
    _data(configmap)[key] = yaml.safe_dump(value, sort_keys=False)


def _json_setting(value: dict[str, str]) -> str:
    return json.dumps(value, separators=(",", ":"))


def _patch_oauth_proxy(docs: list[Any], image: str) -> int:
    patched = 0
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "Deployment":
            continue
        spec = doc.get("spec", {})
        template = spec.get("template", {}) if isinstance(spec, dict) else {}
        pod_spec = template.get("spec", {}) if isinstance(template, dict) else {}
        containers = pod_spec.get("containers", []) if isinstance(pod_spec, dict) else []
        if not isinstance(containers, list):
            continue
        for container in containers:
            if isinstance(container, dict) and container.get("name") == "oauth-proxy":
                container["image"] = image
                patched += 1
    return patched


def _patch_storageclass_configmap(configmap: dict[str, Any], options: PatchOptions) -> None:
    storageclass = _embedded_mapping(configmap, STORAGECLASS_KEY)
    metadata = storageclass.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("embedded StorageClass metadata must be a mapping")
    annotations = metadata.setdefault("annotations", {})
    if not isinstance(annotations, dict):
        raise ValueError("embedded StorageClass metadata.annotations must be a mapping")
    annotations["storageclass.kubernetes.io/is-default-class"] = (
        "true" if options.longhorn_default else "false"
    )

    parameters = storageclass.setdefault("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("embedded StorageClass parameters must be a mapping")
    parameters["numberOfReplicas"] = str(options.replicas)
    parameters["dataEngine"] = options.mode
    if options.mode == "v2":
        parameters["diskSelector"] = options.v2_disk_selector
    else:
        parameters.pop("diskSelector", None)

    _store_embedded_mapping(configmap, STORAGECLASS_KEY, storageclass)


def _patch_default_setting_configmap(configmap: dict[str, Any], options: PatchOptions) -> None:
    settings = _embedded_mapping(configmap, DEFAULT_SETTING_KEY)
    replicas = str(options.replicas)
    settings["default-replica-count"] = _json_setting({"v1": replicas, "v2": replicas})
    settings["default-data-path"] = options.v1_data_path
    settings["create-default-disk-labeled-nodes"] = "false"

    if options.mode == "v2":
        settings["v1-data-engine"] = "true" if options.keep_v1_engine else "false"
        settings["v2-data-engine"] = "true"
        settings["data-engine-hugepage-enabled"] = _json_setting({"v2": "true"})
        settings["data-engine-memory-size"] = _json_setting({"v2": options.v2_memory_size})
    else:
        settings["v1-data-engine"] = "true"
        settings["v2-data-engine"] = "false"
        settings["data-engine-hugepage-enabled"] = _json_setting({"v2": "false"})
        settings.pop("data-engine-memory-size", None)

    _store_embedded_mapping(configmap, DEFAULT_SETTING_KEY, settings)


def patch_documents(docs: list[Any], options: PatchOptions) -> tuple[list[Any], dict[str, int]]:
    if options.mode not in {"v1", "v2"}:
        raise ValueError("mode must be v1 or v2")
    if options.replicas < 1:
        raise ValueError("replicas must be at least 1")

    report = {
        "oauth_proxy_containers": 0,
        "storageclass_configmaps": 0,
        "default_setting_configmaps": 0,
    }

    if options.oauth_proxy_image:
        report["oauth_proxy_containers"] = _patch_oauth_proxy(docs, options.oauth_proxy_image)

    for doc in docs:
        if _matches(doc, kind="ConfigMap", name=STORAGECLASS_CONFIGMAP):
            _patch_storageclass_configmap(doc, options)
            report["storageclass_configmaps"] += 1
        elif _matches(doc, kind="ConfigMap", name=DEFAULT_SETTING_CONFIGMAP):
            _patch_default_setting_configmap(doc, options)
            report["default_setting_configmaps"] += 1

    if options.oauth_proxy_image and report["oauth_proxy_containers"] == 0:
        raise ValueError("no Deployment container named oauth-proxy was found")
    if report["storageclass_configmaps"] == 0:
        raise ValueError(f"no ConfigMap/{STORAGECLASS_CONFIGMAP} was found")
    if report["default_setting_configmaps"] == 0:
        raise ValueError(f"no ConfigMap/{DEFAULT_SETTING_CONFIGMAP} was found")
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


def parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Patch longhorn-okd.yaml for OpenShift V1 or V2 smoke installs."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input longhorn-okd.yaml path.")
    parser.add_argument("--output", required=True, type=Path, help="Output manifest path.")
    parser.add_argument("--mode", required=True, choices=["v1", "v2"], help="Longhorn data engine.")
    parser.add_argument(
        "--oauth-proxy-image",
        help="Optional full oauth-proxy image, for example quay.io/openshift/origin-oauth-proxy:4.22.",
    )
    parser.add_argument(
        "--longhorn-default",
        default=False,
        type=parse_bool,
        metavar="true|false",
        help="Whether the embedded Longhorn StorageClass should be default.",
    )
    parser.add_argument("--replicas", default=1, type=int, help="StorageClass replica count.")
    parser.add_argument(
        "--v1-data-path",
        default="/var/lib/longhorn/",
        help="Default V1 filesystem data path.",
    )
    parser.add_argument(
        "--keep-v1-engine",
        default=False,
        type=parse_bool,
        metavar="true|false",
        help="For --mode v2, keep V1 Data Engine enabled for migration scenarios.",
    )
    parser.add_argument(
        "--v2-disk-selector",
        default="v2",
        help="StorageClass diskSelector to set for V2 volumes.",
    )
    parser.add_argument(
        "--v2-memory-size",
        default="2048",
        help="V2 SPDK memory size setting in MiB.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    options = PatchOptions(
        mode=args.mode,
        oauth_proxy_image=args.oauth_proxy_image,
        longhorn_default=args.longhorn_default,
        replicas=args.replicas,
        v1_data_path=args.v1_data_path,
        keep_v1_engine=args.keep_v1_engine,
        v2_disk_selector=args.v2_disk_selector,
        v2_memory_size=args.v2_memory_size,
    )

    try:
        docs = load_documents(args.input)
        patched, report = patch_documents(docs, options)
        args.output.write_text(dump_documents(patched), encoding="utf-8")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        "patched "
        f"oauth-proxy={report['oauth_proxy_containers']} "
        f"storageclass={report['storageclass_configmaps']} "
        f"default-settings={report['default_setting_configmaps']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
