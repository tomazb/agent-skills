from __future__ import annotations

import json
from pathlib import Path

import pytest

import select_registry_storage as selector


def storage_class(
    name: str,
    provisioner: str,
    *,
    default: bool = False,
    beta_default: bool = False,
    fstype: str | None = None,
    reclaim: str = "Delete",
    binding: str = "WaitForFirstConsumer",
) -> dict:
    annotations = {}
    if default:
        annotations["storageclass.kubernetes.io/is-default-class"] = "true"
    if beta_default:
        annotations["storageclass.beta.kubernetes.io/is-default-class"] = "true"
    item = {
        "metadata": {"name": name, "annotations": annotations},
        "provisioner": provisioner,
        "reclaimPolicy": reclaim,
        "volumeBindingMode": binding,
    }
    if fstype is not None:
        item["parameters"] = {"csi.storage.k8s.io/fstype": fstype}
    return item


def names(decision: dict) -> str:
    return decision["storageClass"]


def test_default_filesystem_class_is_precreated():
    decision = selector.select_registry_storage(
        [storage_class("lvms-vg1", "topolvm.io", default=True, fstype="xfs")]
    )
    assert decision["action"] == "use-class"
    assert names(decision) == "lvms-vg1"
    assert decision["precreatePVC"] is True
    assert any("WaitForFirstConsumer" in warning for warning in decision["warnings"])
    assert any("Delete" in warning for warning in decision["warnings"])


def test_beta_annotation_alone_marks_the_default():
    decision = selector.select_registry_storage(
        [storage_class("lvms-vg1", "topolvm.io", beta_default=True, fstype="ext4")]
    )
    assert decision["action"] == "use-class"
    assert names(decision) == "lvms-vg1"


def test_capital_true_is_not_a_default():
    item = storage_class("lvms-vg1", "topolvm.io", fstype="xfs")
    item["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"] = "True"
    decision = selector.select_registry_storage([item])
    assert decision["action"] == "use-class"
    assert "no default" in decision["reason"]


def test_no_default_uses_the_only_filesystem_class():
    decision = selector.select_registry_storage(
        [storage_class("lvms-vg1", "topolvm.io", fstype="xfs")]
    )
    assert decision["action"] == "use-class"
    assert "no default" in decision["reason"]


def test_known_provisioner_without_fstype_is_usable():
    decision = selector.select_registry_storage(
        [storage_class("cephfs", "cephfs.csi.ceph.com", default=True)]
    )
    assert decision["action"] == "use-class"


def test_unknown_provisioner_with_xfs_is_usable():
    decision = selector.select_registry_storage(
        [storage_class("custom", "example.csi.vendor.io", default=True, fstype="xfs")]
    )
    assert decision["action"] == "use-class"


def test_empty_cluster_requests_lvms():
    decision = selector.select_registry_storage([])
    assert decision["action"] == "install-lvms"
    assert decision["precreatePVC"] is False


def test_only_block_classes_request_lvms():
    decision = selector.select_registry_storage(
        [storage_class("lvms-vg1-block", "topolvm.io", fstype="xfs")]
    )
    assert decision["action"] == "install-lvms"


def test_block_only_default_stops():
    decision = selector.select_registry_storage(
        [
            storage_class("lvms-vg1-block", "topolvm.io", default=True, fstype="xfs"),
            storage_class("lvms-vg1", "topolvm.io", fstype="xfs"),
        ]
    )
    assert decision["action"] == "stop"
    assert "default StorageClass" in decision["reason"]


def test_two_defaults_stop():
    decision = selector.select_registry_storage(
        [
            storage_class("a", "topolvm.io", default=True, fstype="xfs"),
            storage_class("b", "topolvm.io", default=True, fstype="xfs"),
        ]
    )
    assert decision["action"] == "stop"
    assert "more than one default" in decision["reason"]


def test_two_filesystem_classes_without_a_default_stop():
    decision = selector.select_registry_storage(
        [
            storage_class("a", "topolvm.io", fstype="xfs"),
            storage_class("b", "topolvm.io", fstype="ext4"),
        ]
    )
    assert decision["action"] == "stop"


def test_object_and_static_provisioners_are_not_filesystem_classes():
    decision = selector.select_registry_storage(
        [
            storage_class("obc", "openshift-storage.noobaa.io/obc"),
            storage_class("local", "kubernetes.io/no-provisioner"),
        ]
    )
    assert decision["action"] == "install-lvms"


def test_explicit_class_overrides_default_selection():
    decision = selector.select_registry_storage(
        [
            storage_class("default-sc", "topolvm.io", default=True, fstype="xfs"),
            storage_class("other", "topolvm.io", fstype="ext4"),
        ],
        explicit_storage_class="other",
    )
    assert names(decision) == "other"


def test_explicit_class_still_warns_when_multiple_defaults_exist():
    decision = selector.select_registry_storage(
        [
            storage_class("a", "topolvm.io", default=True, fstype="xfs"),
            storage_class("b", "topolvm.io", default=True, fstype="xfs"),
        ],
        explicit_storage_class="a",
    )
    assert decision["action"] == "use-class"
    assert any("more than one" in warning for warning in decision["warnings"])


def test_explicit_missing_or_block_class_stops():
    classes = [storage_class("lvms-vg1-block", "topolvm.io", fstype="xfs")]
    missing = selector.select_registry_storage(classes, explicit_storage_class="missing")
    block = selector.select_registry_storage(classes, explicit_storage_class="lvms-vg1-block")
    assert missing["action"] == "stop"
    assert block["action"] == "stop"


def test_storage_class_list_json_shape():
    payload = {"items": [storage_class("lvms-vg1", "topolvm.io", default=True, fstype="xfs")]}
    classes = selector.load_storage_classes(payload)
    assert selector.select_registry_storage(classes)["action"] == "use-class"


def test_cli_reads_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = tmp_path / "sc.json"
    path.write_text(
        json.dumps(
            {"items": [storage_class("lvms-vg1", "topolvm.io", default=True, fstype="xfs")]}
        ),
        encoding="utf-8",
    )
    assert selector.main(["--input", str(path)]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["storageClass"] == "lvms-vg1"


def test_cli_rejects_malformed_input(tmp_path: Path):
    path = tmp_path / "sc.json"
    path.write_text("{", encoding="utf-8")
    assert selector.main(["--input", str(path)]) == 2
