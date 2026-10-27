from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import check_api_readiness
import check_registry_smoke
import decide_registry_pvc
import registry_pv_audit


def claim(storage: str, **overrides: object) -> dict:
    body: dict = {
        "metadata": {
            "name": "image-registry-storage",
            "namespace": "openshift-image-registry",
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "lvms-vg1",
            "volumeMode": "Filesystem",
            "resources": {"requests": {"storage": storage}},
        },
        "status": {"phase": "Bound"},
    }
    body.update(overrides)
    return body


def test_missing_claim_is_created_and_a_larger_claim_is_kept():
    assert decide_registry_pvc.decide_registry_pvc(None, "lvms-vg1")["action"] == "create"
    kept = decide_registry_pvc.decide_registry_pvc(claim("200Gi"), "lvms-vg1")
    assert kept["action"] == "reuse"
    exact = decide_registry_pvc.decide_registry_pvc(claim("100Gi"), "lvms-vg1")
    assert exact["action"] == "reuse"
    pending = claim("150Gi")
    pending["status"] = {"phase": "Pending"}
    assert decide_registry_pvc.decide_registry_pvc(pending, "lvms-vg1")["action"] == "reuse"
    larger = claim("1.5Ti")
    del larger["spec"]["volumeMode"]
    assert decide_registry_pvc.decide_registry_pvc(larger, "lvms-vg1")["action"] == "reuse"


def test_incompatible_claims_stop_without_a_shrink_or_replace():
    cases = [
        claim("50Gi"),
        claim("99.9Gi"),
        claim("100G"),
        claim("200Gi", spec={
            "accessModes": ["ReadWriteMany"],
            "storageClassName": "lvms-vg1",
            "volumeMode": "Filesystem",
            "resources": {"requests": {"storage": "200Gi"}},
        }),
        claim("200Gi", spec={
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "lvms-vg1",
            "volumeMode": "Block",
            "resources": {"requests": {"storage": "200Gi"}},
        }),
        claim("200Gi", spec={
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "other-class",
            "volumeMode": "Filesystem",
            "resources": {"requests": {"storage": "200Gi"}},
        }),
    ]
    for pvc in cases:
        decision = decide_registry_pvc.decide_registry_pvc(pvc, "lvms-vg1")
        assert decision["action"] == "stop"
        assert "200Gi" not in decision["reason"]
        assert "other-class" not in decision["reason"]


def test_malformed_claim_stops_instead_of_raising():
    lost = claim("200Gi")
    lost["status"] = {"phase": "Lost"}
    assert decide_registry_pvc.decide_registry_pvc(lost, "lvms-vg1")["action"] == "stop"

    broken = claim("200Gi")
    broken["spec"]["resources"] = "200Gi"
    assert decide_registry_pvc.decide_registry_pvc(broken, "lvms-vg1")["action"] == "stop"
    weird_status = claim("200Gi")
    weird_status["status"] = "Bound"
    assert decide_registry_pvc.decide_registry_pvc(weird_status, "lvms-vg1")["action"] == "stop"
    assert decide_registry_pvc.decide_registry_pvc({"metadata": "nope"}, "lvms-vg1")["action"] == "stop"


def test_deleting_claim_is_not_reused():
    deleting = claim("200Gi")
    deleting["metadata"]["deletionTimestamp"] = "2026-10-27T00:00:00Z"
    decision = decide_registry_pvc.decide_registry_pvc(deleting, "lvms-vg1")
    assert decision["action"] == "stop"
    assert decision["reason"] == "claim is being deleted"


def test_claim_identity_must_match_name_and_namespace():
    renamed = claim("200Gi")
    renamed["metadata"]["namespace"] = "other-namespace"
    assert decide_registry_pvc.decide_registry_pvc(renamed, "lvms-vg1")["action"] == "stop"


def test_decide_cli_exits_nonzero_for_a_smaller_claim(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = tmp_path / "pvc.json"
    path.write_text(json.dumps(claim("50Gi")), encoding="utf-8")
    assert decide_registry_pvc.main(["--storage-class", "lvms-vg1", "--input", str(path)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "stop"

    assert decide_registry_pvc.main(["--storage-class", "lvms-vg1", "--missing"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "create"


def operator(available: str, progressing: str, degraded: str, message: str = "") -> dict:
    return {
        "status": {
            "conditions": [
                {"type": "Available", "status": available, "message": message},
                {"type": "Progressing", "status": progressing, "message": message},
                {"type": "Degraded", "status": degraded, "message": message},
            ]
        }
    }


def test_api_gate_requires_available_and_idle_and_hides_messages():
    ready, detail = check_api_readiness.api_ready(operator("True", "False", "False"))
    assert ready is True
    assert "True" in detail

    secret = "dial secret-marker.example super-secret-token-value"
    for state in (
        operator("False", "False", "False", secret),
        operator("True", "True", "False", secret),
        operator("True", "False", "True", secret),
        {"status": {}},
    ):
        ready, detail = check_api_readiness.api_ready(state)
        assert ready is False
        assert "secret-marker.example" not in detail
        assert "super-secret-token-value" not in detail


def test_api_cli_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = tmp_path / "kas.json"
    path.write_text(json.dumps(operator("True", "True", "False")), encoding="utf-8")
    assert check_api_readiness.main(["--input", str(path)]) == 1
    captured = capsys.readouterr()
    assert "Progressing=True" in captured.err
    assert captured.out == ""


def pv(name: str, claim_name: str, namespace: str) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"claimRef": {"name": claim_name, "namespace": namespace}},
    }


def test_leftover_pvs_require_name_and_namespace():
    document = {
        "items": [
            pv("registry-disk", "image-registry-storage", "openshift-image-registry"),
            pv("other-disk", "image-registry-storage", "other-namespace"),
            pv("unrelated", "other-claim", "openshift-image-registry"),
        ]
    }
    assert registry_pv_audit.leftover_registry_pvs(document) == ["registry-disk"]


def test_pv_audit_cli_fails_when_a_matching_disk_remains(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    document = {"items": [pv("registry-disk", "image-registry-storage", "openshift-image-registry")]}
    path = tmp_path / "pvs.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert registry_pv_audit.main(["--input", str(path)]) == 1
    assert capsys.readouterr().out.strip() == "registry-disk"

    empty = {"items": [pv("other-disk", "image-registry-storage", "other-namespace")]}
    sys.stdin = io.StringIO(json.dumps(empty))
    try:
        assert registry_pv_audit.main([]) == 0
    finally:
        sys.stdin = sys.__stdin__
    assert capsys.readouterr().out == ""


def test_smoke_passes_when_the_same_blob_does_not_grow_the_filesystem():
    assert check_registry_smoke.smoke_passed(
        "copying blob\nregistry-push-ok\n",
        "registry-smoke-ok\n",
    )


def test_metadata_import_is_not_treated_as_a_registry_push():
    assert check_registry_smoke.smoke_passed("imported image\n", "registry-smoke-ok\n") is False
    assert check_registry_smoke.smoke_passed("registry-push-ok\n", "pull failed\n") is False


def test_smoke_checker_does_not_echo_log_contents(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    secret = "super-secret-token-value"
    push_log = tmp_path / "push.log"
    pull_log = tmp_path / "pull.log"
    push_log.write_text(secret + "\n", encoding="utf-8")
    pull_log.write_text(secret + "\n", encoding="utf-8")
    assert check_registry_smoke.main(["--push-log", str(push_log), "--pull-log", str(pull_log)]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
