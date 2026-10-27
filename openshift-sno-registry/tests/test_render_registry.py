from __future__ import annotations

import json
from pathlib import Path

import pytest

import render_registry_config as config
import render_registry_pvc as pvc
import render_registry_push as push
import render_registry_smoke as smoke


def test_managed_patch_pins_one_recreate_replica_and_named_claim():
    payload = json.loads(config.render_registry_config("Managed"))
    spec = payload["spec"]
    assert spec["managementState"] == "Managed"
    assert spec["replicas"] == 1
    assert spec["rolloutStrategy"] == "Recreate"
    assert spec["storage"]["managementState"] == "Managed"
    assert spec["storage"]["pvc"]["claim"] == "image-registry-storage"
    assert "defaultRoute" not in spec
    assert "emptyDir" not in spec["storage"]


def test_clear_emptydir_is_json_null():
    payload = json.loads(config.render_registry_config("Managed", clear_emptydir=True))
    assert payload["spec"]["storage"]["emptyDir"] is None


def test_removed_patch_changes_only_management_state():
    payload = json.loads(config.render_registry_config("Removed"))
    assert payload == {"spec": {"managementState": "Removed"}}


def test_removed_patch_rejects_clear_emptydir():
    with pytest.raises(ValueError):
        config.render_registry_config("Removed", clear_emptydir=True)


def test_pvc_is_filesystem_rwo_on_the_named_class():
    text = pvc.render_registry_pvc("lvms-vg1", "100Gi")
    assert "name: image-registry-storage" in text
    assert "namespace: openshift-image-registry" in text
    assert "ReadWriteOnce" in text
    assert "ReadWriteMany" not in text
    assert "storageClassName: lvms-vg1" in text
    assert "volumeMode: Filesystem" in text
    assert "storage: 100Gi" in text


def test_pvc_rejects_small_or_invalid_requests():
    with pytest.raises(Exception):
        pvc.render_registry_pvc("lvms-vg1", "10Gi")
    with pytest.raises(Exception):
        pvc.render_registry_pvc("LVMS", "100Gi")


def test_smoke_pod_is_restricted_and_pulls_the_given_image():
    text = smoke.render_registry_smoke(
        "registry-smoke",
        "image-registry.openshift-image-registry.svc:5000/registry-smoke/smoke:9.5",
        "registry-smoke-ok",
    )
    assert "namespace: registry-smoke" in text
    assert "image: image-registry.openshift-image-registry.svc:5000/registry-smoke/smoke:9.5" in text
    assert "echo registry-smoke-ok" in text
    assert "runAsNonRoot: true" in text
    assert "allowPrivilegeEscalation: false" in text
    assert "automountServiceAccountToken: false" in text


def test_push_manifest_copies_without_signatures_or_a_baked_token():
    text = push.render_registry_push(
        "registry-smoke",
        "registry.access.redhat.com/ubi9/ubi-micro:9.5",
        "image-registry.openshift-image-registry.svc:5000/registry-smoke/pushed:9.5",
    )
    assert "name: system:image-builder" in text
    assert "serviceAccountName: registry-smoke" in text
    assert "--remove-signatures" in text
    assert "service-ca.crt" in text
    assert "${token}" in text
    assert "echo registry-push-ok" in text
    assert "runAsNonRoot: true" in text


def test_smoke_pod_rejects_a_schemed_image():
    with pytest.raises(Exception):
        smoke.render_registry_smoke(
            "registry-smoke",
            "docker://example.com/smoke:9.5",
            "registry-smoke-ok",
        )


def test_cli_writes_patch(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    output = tmp_path / "patch.json"
    assert config.main(["--management-state", "Managed", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["spec"]["rolloutStrategy"] == "Recreate"
    assert "Rendered" in capsys.readouterr().out
