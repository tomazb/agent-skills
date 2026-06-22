from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sample_longhorn_okd_docs() -> list[object]:
    storageclass = {
        "apiVersion": "storage.k8s.io/v1",
        "kind": "StorageClass",
        "metadata": {
            "name": "longhorn",
            "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
        },
        "provisioner": "driver.longhorn.io",
        "parameters": {
            "numberOfReplicas": "3",
            "dataEngine": "v2",
            "diskSelector": "old",
        },
    }
    default_settings = {
        "default-replica-count": "3",
        "default-data-path": "/var/lib/longhorn/",
        "create-default-disk-labeled-nodes": "true",
        "v2-data-engine": "true",
        "data-engine-hugepage-enabled": '{"v2":"true"}',
        "data-engine-memory-size": '{"v2":"2048"}',
    }
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "longhorn-ui", "namespace": "longhorn-system"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "longhorn-ui", "image": "longhorn-ui:old"},
                            {"name": "oauth-proxy", "image": "oauth-proxy:old"},
                        ]
                    }
                }
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "longhorn-storageclass", "namespace": "longhorn-system"},
            "data": {"storageclass.yaml": yaml.safe_dump(storageclass, sort_keys=False)},
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "longhorn-default-setting", "namespace": "longhorn-system"},
            "data": {"default-setting.yaml": yaml.safe_dump(default_settings, sort_keys=False)},
        },
    ]


def embedded_yaml(docs: list[object], configmap_name: str, key: str) -> dict[str, object]:
    for doc in docs:
        if (
            isinstance(doc, dict)
            and doc.get("kind") == "ConfigMap"
            and doc.get("metadata", {}).get("name") == configmap_name
        ):
            return yaml.safe_load(doc["data"][key])
    raise AssertionError(f"missing ConfigMap/{configmap_name}")


def test_patch_longhorn_okd_manifest_for_v2_sets_engine_defaults_and_oauth_proxy():
    patcher = load_module("patch_longhorn_okd_manifest", "scripts/patch_longhorn_okd_manifest.py")
    docs = deepcopy(sample_longhorn_okd_docs())

    patched, report = patcher.patch_documents(
        docs,
        patcher.PatchOptions(
            mode="v2",
            oauth_proxy_image="quay.io/openshift/origin-oauth-proxy:4.22",
            longhorn_default=False,
            replicas=1,
            v2_disk_selector="v2",
        ),
    )

    assert report == {
        "oauth_proxy_containers": 1,
        "storageclass_configmaps": 1,
        "default_setting_configmaps": 1,
    }
    containers = patched[0]["spec"]["template"]["spec"]["containers"]
    assert containers[1]["image"] == "quay.io/openshift/origin-oauth-proxy:4.22"

    storageclass = embedded_yaml(patched, "longhorn-storageclass", "storageclass.yaml")
    assert storageclass["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"] == "false"
    assert storageclass["parameters"]["numberOfReplicas"] == "1"
    assert storageclass["parameters"]["dataEngine"] == "v2"
    assert storageclass["parameters"]["diskSelector"] == "v2"

    settings = embedded_yaml(patched, "longhorn-default-setting", "default-setting.yaml")
    assert settings["default-replica-count"] == '{"v1":"1","v2":"1"}'
    assert settings["create-default-disk-labeled-nodes"] == "false"
    assert settings["v1-data-engine"] == "false"
    assert settings["v2-data-engine"] == "true"
    assert settings["data-engine-hugepage-enabled"] == '{"v2":"true"}'
    assert settings["data-engine-memory-size"] == '{"v2":"2048"}'


def test_patch_longhorn_okd_manifest_for_v1_removes_v2_storageclass_selector():
    patcher = load_module("patch_longhorn_okd_manifest", "scripts/patch_longhorn_okd_manifest.py")
    docs = deepcopy(sample_longhorn_okd_docs())

    patched, _ = patcher.patch_documents(
        docs,
        patcher.PatchOptions(mode="v1", longhorn_default=False, replicas=1),
    )

    storageclass = embedded_yaml(patched, "longhorn-storageclass", "storageclass.yaml")
    assert storageclass["parameters"]["numberOfReplicas"] == "1"
    assert storageclass["parameters"]["dataEngine"] == "v1"
    assert "diskSelector" not in storageclass["parameters"]

    settings = embedded_yaml(patched, "longhorn-default-setting", "default-setting.yaml")
    assert settings["v1-data-engine"] == "true"
    assert settings["v2-data-engine"] == "false"
    assert settings["data-engine-hugepage-enabled"] == '{"v2":"false"}'
    assert "data-engine-memory-size" not in settings


def test_patch_longhorn_okd_manifest_can_keep_v1_engine_for_v2_migration():
    patcher = load_module("patch_longhorn_okd_manifest", "scripts/patch_longhorn_okd_manifest.py")
    docs = deepcopy(sample_longhorn_okd_docs())

    patched, _ = patcher.patch_documents(
        docs,
        patcher.PatchOptions(mode="v2", keep_v1_engine=True),
    )

    settings = embedded_yaml(patched, "longhorn-default-setting", "default-setting.yaml")
    assert settings["v1-data-engine"] == "true"
    assert settings["v2-data-engine"] == "true"


def test_render_smoke_manifest_uses_restricted_podsecurity_settings():
    renderer = load_module("render_smoke_manifest", "scripts/render_smoke_manifest.py")

    docs = renderer.render_smoke_documents(
        renderer.SmokeOptions(mode="v2", storage_class="longhorn", size="2Gi")
    )
    namespace = next(doc for doc in docs if doc["kind"] == "Namespace")
    pvc = next(doc for doc in docs if doc["kind"] == "PersistentVolumeClaim")
    pod = next(doc for doc in docs if doc["kind"] == "Pod")

    assert namespace["metadata"]["name"] == "longhorn-v2-smoke"
    assert pvc["spec"]["storageClassName"] == "longhorn"
    assert pvc["spec"]["resources"]["requests"]["storage"] == "2Gi"
    assert pod["spec"]["securityContext"]["runAsNonRoot"] is True
    assert pod["spec"]["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"

    container = pod["spec"]["containers"][0]
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["volumeMounts"][0]["mountPath"] == "/data"


def test_smoke_template_keeps_restricted_podsecurity_settings():
    docs = list(yaml.safe_load_all((REPO_ROOT / "assets" / "smoke-pvc-writer.yaml").read_text()))
    pod = next(doc for doc in docs if doc["kind"] == "Pod")

    assert pod["spec"]["securityContext"]["runAsNonRoot"] is True
    assert pod["spec"]["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    container = pod["spec"]["containers"][0]
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_post_uninstall_audit_covers_cluster_scoped_longhorn_leftovers():
    text = (REPO_ROOT / "scripts" / "post_uninstall_audit.sh").read_text(encoding="utf-8")

    expected_checks = [
        "oc get namespace",
        "oc api-resources --api-group=longhorn.io",
        "validatingwebhookconfiguration longhorn-webhook-validator",
        "mutatingwebhookconfiguration longhorn-webhook-mutator",
        "oc get csidriver driver.longhorn.io",
        "oc get clusterrole,clusterrolebinding -o name | grep -i longhorn",
        "oc get priorityclass longhorn-critical",
        "oc get storageclass -o wide",
        "oc get pv,pvc -A -o wide",
    ]
    for check in expected_checks:
        assert check in text
