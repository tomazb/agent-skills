from __future__ import annotations

import argparse
import subprocess
import textwrap

import pytest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import patch_lvms_manifest as plm
import render_smoke_manifest as rsm


def test_patch_lvmcluster_thin_pool():
    doc = {
        "kind": "LVMCluster",
        "spec": {
            "storage": {
                "deviceClasses": [
                    {
                        "name": "vg1",
                        "thinPoolConfig": {
                            "name": "thin-pool-1",
                        },
                    }
                ]
            }
        },
    }
    assert plm._patch_lvmcluster_thin_pool(doc, overprovision_ratio=20, size_percent=80)
    assert (
        doc["spec"]["storage"]["deviceClasses"][0]["thinPoolConfig"][
            "overprovisionRatio"
        ]
        == 20
    )
    assert (
        doc["spec"]["storage"]["deviceClasses"][0]["thinPoolConfig"]["sizePercent"]
        == 80
    )


def test_patch_lvmcluster_device_selector():
    doc = {
        "kind": "LVMCluster",
        "spec": {"storage": {"deviceClasses": [{"name": "vg1"}]}},
    }
    paths = ["/dev/disk/by-id/disk-1", "/dev/disk/by-id/disk-2"]
    assert plm._patch_lvmcluster_device_selector(doc, paths=paths, force_wipe=True)
    ds = doc["spec"]["storage"]["deviceClasses"][0]["deviceSelector"]
    assert ds["paths"] == paths
    assert ds["forceWipeDevicesAndDestroyAllData"] is True


def test_patch_lvmcluster_default():
    doc = {
        "kind": "LVMCluster",
        "spec": {"storage": {"deviceClasses": [{"name": "vg1"}]}},
    }
    assert plm._patch_lvmcluster_default(doc, True)
    assert doc["spec"]["storage"]["deviceClasses"][0]["default"] is True


def test_patch_thin_pool_noop_does_not_inject_empty_config():
    # Patching only device paths must not create a spurious empty thinPoolConfig,
    # which would be rejected by the LVMCluster schema (name/sizePercent required).
    doc = {
        "kind": "LVMCluster",
        "spec": {"storage": {"deviceClasses": [{"name": "vg1"}]}},
    }
    assert not plm._patch_lvmcluster_thin_pool(doc)
    assert "thinPoolConfig" not in doc["spec"]["storage"]["deviceClasses"][0]


def test_patch_device_selector_noop_does_not_inject_empty_selector():
    # Patching only the thin pool must not create a spurious empty deviceSelector,
    # which would change disk-selection semantics.
    doc = {
        "kind": "LVMCluster",
        "spec": {"storage": {"deviceClasses": [{"name": "vg1"}]}},
    }
    assert not plm._patch_lvmcluster_device_selector(doc)
    assert "deviceSelector" not in doc["spec"]["storage"]["deviceClasses"][0]


def test_patch_documents_thin_pool_only_leaves_selector_untouched():
    doc = {
        "kind": "LVMCluster",
        "spec": {"storage": {"deviceClasses": [{"name": "vg1"}]}},
    }
    with pytest.raises(ValueError, match="thinPoolConfig"):
        plm.patch_documents([doc], overprovision_ratio=10)


def test_patch_thin_pool_rejects_incomplete_existing_config():
    doc = {
        "kind": "LVMCluster",
        "spec": {"storage": {"deviceClasses": [{"name": "vg1", "thinPoolConfig": {}}]}},
    }
    with pytest.raises(ValueError, match="name.*overprovisionRatio"):
        plm.patch_documents([doc], size_percent=80)


def test_parse_stable_device_path_accepts_by_id_and_by_path():
    assert (
        plm.parse_stable_device_path("/dev/disk/by-id/disk-1")
        == "/dev/disk/by-id/disk-1"
    )
    assert (
        plm.parse_stable_device_path("/dev/disk/by-path/pci-1")
        == "/dev/disk/by-path/pci-1"
    )


def test_parse_stable_device_path_rejects_volatile_paths():
    with pytest.raises(argparse.ArgumentTypeError, match="/dev/disk/by-id"):
        plm.parse_stable_device_path("/dev/sda")


def test_patch_lvmcluster_default_rejects_multiple_classes():
    doc = {
        "kind": "LVMCluster",
        "spec": {"storage": {"deviceClasses": [{"name": "vg1"}, {"name": "vg2"}]}},
    }
    with pytest.raises(ValueError, match="multiple deviceClasses"):
        plm.patch_documents([doc], device_class_default=True)


def test_patch_storageclass_fs_type():
    doc = {"kind": "StorageClass", "metadata": {"name": "lvms-vg1"}}
    assert plm._patch_storageclass_fs_type(doc, "xfs")
    assert doc["parameters"]["csi.storage.k8s.io/fstype"] == "xfs"


def test_patch_storageclass_no_fs_type():
    doc = {"kind": "StorageClass", "metadata": {"name": "lvms-vg1-block"}}
    assert not plm._patch_storageclass_fs_type(doc, None)


def test_patch_documents_empty():
    docs, report = plm.patch_documents([])
    assert docs == []
    assert report["lvmcluster_patched"] == 0
    assert report["storageclass_patched"] == 0


def test_load_and_dump_documents(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(
        "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: test\n",
        encoding="utf-8",
    )
    docs = plm.load_documents(path)
    assert len(docs) == 1
    assert docs[0]["kind"] == "ConfigMap"
    output = plm.dump_documents(docs)
    assert "ConfigMap" in output


def test_render_smoke_fs():
    manifest = rsm.render("fs", "lvms-smoke", "lvms-vg1")
    assert "lvms-smoke" in manifest
    assert "lvms-vg1" in manifest
    assert "volumeMounts" in manifest
    assert "volumeMode: Block" not in manifest


def test_render_smoke_block():
    manifest = rsm.render("block", "lvms-block-smoke", "lvms-vg1-block")
    assert "lvms-block-smoke" in manifest
    assert "lvms-vg1-block" in manifest
    assert "volumeDevices" in manifest
    assert "volumeMode: Block" in manifest


def test_render_invalid_mode():
    with pytest.raises(ValueError):
        rsm.render("invalid", "ns", "sc")


def test_render_smoke_manifest_cli_does_not_require_pyyaml(tmp_path):
    output = tmp_path / "smoke.yaml"
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "render_smoke_manifest.py"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(script),
            "--mode",
            "fs",
            "--namespace",
            "lvms-smoke",
            "--storage-class",
            "lvms-vg1",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ubi-minimal:latest" not in output.read_text(encoding="utf-8")
