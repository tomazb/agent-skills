from __future__ import annotations

import json
import sys
import tempfile
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

RBD and CephFS and RGW are supported.

`cephblockpool`, `cephfilesystem`, `cephobjectstore` resources.

Use `mon.count` and `mgr.count`.

On OpenShift, use MachineConfig and reboot. Wait for MCP.

Grant privileged SCC temporarily.

Do not downgrade. Read release notes. Check HEALTH_OK and active+clean.

For upgrade, verify HEALTH_OK and active+clean.

Leave the PG autoscaler on; check `ceph osd pool autoscale-status`.

On OpenShift, install with operator-openshift.yaml for the dedicated rook-ceph SCC.

Apply `csi-operator.yaml` before `operator-openshift.yaml` or `CephConnection` reconciliation can fail.

Use `curl -fsSLo /tmp/rook-ceph-csi-operator.yaml` before `curl -fsSLo /tmp/rook-ceph-operator.yaml`.

Create the namespace first with `oc create ns rook-ceph`.

Run `oc apply --server-side --force-conflicts -f /tmp/rook-ceph-crds.yaml`, then `oc apply -f /tmp/rook-ceph-common.yaml`, then `oc apply -f /tmp/rook-ceph-csi-operator.yaml`, then `oc apply -f /tmp/rook-ceph-operator.yaml`.

Apply `oc apply -f /tmp/rook-ceph-csi-operator.yaml` before `oc apply -f /tmp/rook-ceph-operator.yaml`.

Use `useAllDevices: false` when the SNO install pins a dedicated OSD disk.

Use `/dev/disk/by-id/<stable-disk-id>` together with `osd_pool_default_size` and `mon_warn_on_pool_no_redundancy` on the SNO example.

On SNO with RGW, raise `mon_max_pg_per_osd` when the single OSD needs a higher PG ceiling.

If the OpenShift Prometheus API is auth-protected, point `PROMETHEUS_API_HOST` at an `internal Prometheus`.

Expose the dashboard Route through the `http-dashboard` service port.

Run `ceph mgr module enable rook` and `ceph orch set backend rook`.

Validate RGW with `ObjectBucket` state, a `curl -kI` route check, and an HTTP response from `Ceph Object Gateway` instead of a `TLS or connection failure`.

Validated SNO evidence should include `v1.20.2`, `v20.2.2`, `rook-ceph-rgw-obc`, and `Backend: rook`.

Use `python3 scripts/patch_rook_ceph_manifest.py` when preparing placeholder manifests.

Use `python3 scripts/render_smoke_manifest.py` for smoke PVC writers.

Run `bash scripts/post_uninstall_audit.sh` after uninstall.
"""

SKILL_TEMPLATE = """\
---
name: openshift-rook
description: Use when planning, installing, or troubleshooting Rook Ceph on OpenShift.
---

# OpenShift Rook Ceph Lifecycle

Use this skill as a lifecycle router.

## Product Ownership Gate

Before routing, run read-only ownership discovery. Inspect `StorageCluster`, ODF/OCS
`Subscription` or CSV evidence, and `CephCluster`. Namespace presence alone is
insufficient. Classify ODF, upstream Rook, mixed/conflicting, or unknown. Stop and
report evidence when ownership is mixed, conflicting, unknown, or access is
insufficient. Do not recommend mutation until ownership is classified. If ODF owns
the cluster, hand off to `openshift-odf`.

## Routing

Routing guidance.

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
        text = text.replace("name: openshift-rook", f"name: {name}")
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
        root = tmp_path / "openshift-rook"
        root.mkdir()

        refs = root / "references"
        refs.mkdir()

        (root / "SKILL.md").write_text(skill_text or make_skill_text(), encoding="utf-8")
        (root / "README.md").write_text(
            "# OpenShift Rook Ceph\n\nCurrent version: **1.0.0**\n", encoding="utf-8"
        )
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0\n\n- Initial.\n", encoding="utf-8")
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "openshift-rook",
                    "version": "1.0.0",
                    "description": "Rook Ceph lifecycle",
                }
            ),
            encoding="utf-8",
        )
        (root / "assets").mkdir()
        (root / "assets" / "smoke-pvc-writer.yaml").write_text("", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "patch_rook_ceph_manifest.py").write_text("", encoding="utf-8")
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
