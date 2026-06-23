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
"""

SKILL_TEMPLATE = """\
---
name: openshift-rook
description: Use when planning, installing, or troubleshooting Rook Ceph on OpenShift.
---

# OpenShift Rook Ceph Lifecycle

Use this skill as a lifecycle router.

## Routing

Routing guidance.

## Core Safety Rules

Safety guidance.

## Required Source Checks

Source guidance.

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
