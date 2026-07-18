from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import validate_skill_package as vsp


@pytest.fixture
def validator():
    return vsp


REFERENCE_TEXT = """\
# Sample Reference

Never run or recommend `wipefs` before explicit destructive confirmation.

Use `readlink -f`, `lsblk -f`, `wipefs -n`, and `ceph-volume lvm list` evidence.

Use stable `/dev/disk/by-id/*` paths.

For SNO, use `replicated.size: 1` and `requireSafeReplicaSize: false`.

Keep exactly one default StorageClass.

Also keep one default StorageClass.

ceph-rbd and CephFS and RGW and MCG are supported via the StorageCluster.

Default classes: `ocs-storagecluster-ceph-rbd`, `ocs-storagecluster-cephfs`.

Everything lives in the `openshift-storage` namespace.

On OpenShift, use MachineConfig and reboot. Wait for MCP.

ODF binds its own SecurityContextConstraints; do not add the built-in privileged SCC by hand.

Do not downgrade. Read release notes. Check HEALTH_OK and active+clean.

Leave the PG autoscaler on; check `ceph osd pool autoscale-status`.

ODF is installed through the odf-operator via OLM Subscription.

Enable the toolbox with enableCephTools on OCSInitialization.

Label storage nodes with `cluster.ocs.openshift.io/openshift-storage`.

## OLM install ordering
kind: Namespace
labels:
  openshift.io/cluster-monitoring: "true"
kind: OperatorGroup
`oc get packagemanifest odf-operator -n openshift-marketplace`
kind: Subscription
name: odf-operator
kind: StorageCluster
monDataDirHostPath: /var/lib/rook

## Local Storage Operator
Install the local-storage-operator, create a LocalVolumeDiscovery, then a
LocalVolumeSet named localblock with a deviceInclusionSpec.

## Upgrade
Use installPlanApproval and approve the pending installplan. Confirm
`ceph versions` and check the interoperability matrix.

## Object storage
Use the `openshift-storage.noobaa.io` ObjectBucketClaim StorageClass. Verify the
ObjectBucket, use `ocs-storagecluster-ceph-rgw`, and manage RGW through
`managedResources.cephObjectStores`.

## Capacity
Use the ocs-osd-removal job with FAILED_OSD_IDS and scale the storageDeviceSets
count.

## BlueStore cleanup
For a disk that previously held a Ceph BlueStore OSD, use full-disk zeroing.

## Uninstall
Annotate `uninstall.ocs.openshift.io/cleanup-policy` and
`uninstall.ocs.openshift.io/mode`, then `oc delete storagecluster`. Run
`post_uninstall_audit.sh`.

## Validation
Use the OpenShift console Data Foundation dashboards. Smoke pods are named
rbd-smoke-writer and cephfs-smoke-writer.

## Validated SNO
Evidence includes `ocs-storagecluster-ceph-rbd`, `openshift-storage.noobaa.io`,
`localblock`, and `HEALTH_OK`.

Use `python3 scripts/render_storagecluster.py` when generating a StorageCluster.

Use `python3 scripts/render_smoke_manifest.py` for smoke PVC writers.
"""

SKILL_TEMPLATE = """\
---
name: openshift-odf
description: Use when planning, installing, or troubleshooting ODF on OpenShift.
---

# OpenShift Data Foundation Lifecycle

Use this skill as a lifecycle router.

## Product Ownership Gate

Before routing, run read-only ownership discovery. Inspect `StorageCluster`, ODF/OCS
`Subscription` or CSV evidence, and `CephCluster`. Namespace presence alone is
insufficient. Classify ODF, upstream Rook, mixed/conflicting, or unknown. Stop and
report evidence when ownership is mixed, conflicting, unknown, or access is
insufficient. Do not recommend mutation until ownership is classified. If upstream
Rook owns the cluster, hand off to `openshift-rook`.

## Routing

Use `references/validated-odf-sno.md` for version-scoped SNO evidence.

## Core Safety Rules

Safety guidance.

## Required Source Checks

Source guidance. For OpenShift channel or upgrade-path questions, use
`openshift-versions`. Release availability is not cluster upgrade readiness.

## Inputs To Collect

Input guidance.

## Output Expectations

Output guidance.
"""


def _make_skill_text(name: str = vsp.EXPECTED_NAME, missing_sections: list[str] | None = None) -> str:
    text = SKILL_TEMPLATE
    if name != vsp.EXPECTED_NAME:
        text = text.replace("name: openshift-odf", f"name: {name}")
    if missing_sections:
        for section in missing_sections:
            text = text.replace(f"## {section.lstrip('# ').strip()}", "")
    return text


@pytest.fixture
def make_skill_text():
    return _make_skill_text


@pytest.fixture
def reference_text():
    return lambda: REFERENCE_TEXT


@pytest.fixture
def package_factory(tmp_path, make_skill_text, reference_text):
    def _factory(
        skill_text: str | None = None,
        reference_content: str | None = None,
    ) -> Path:
        root = tmp_path / "openshift-odf"
        root.mkdir()

        refs = root / "references"
        refs.mkdir()

        (root / "SKILL.md").write_text(skill_text or make_skill_text(), encoding="utf-8")
        (root / "README.md").write_text(
            "# OpenShift Data Foundation\n\nCurrent version: **1.0.0**\n", encoding="utf-8"
        )
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0\n\n- Initial.\n", encoding="utf-8")
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "openshift-odf",
                    "version": "1.0.0",
                    "description": "ODF lifecycle",
                }
            ),
            encoding="utf-8",
        )
        (root / "assets").mkdir()
        (root / "assets" / "smoke-pvc-writer.yaml").write_text("", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "render_storagecluster.py").write_text("", encoding="utf-8")
        (root / "scripts" / "post_uninstall_audit.sh").write_text("", encoding="utf-8")
        (root / "scripts" / "render_smoke_manifest.py").write_text("", encoding="utf-8")
        (root / "tools").mkdir()
        (root / "tools" / "validate_skill_package.py").write_text("", encoding="utf-8")
        (root / "tools" / "validate_skill_package.sh").write_text("", encoding="utf-8")

        ref_content = reference_content or REFERENCE_TEXT
        for ref in vsp.EXPECTED_REFERENCES:
            (root / ref).write_text(ref_content + "\n", encoding="utf-8")

        return root

    return _factory
