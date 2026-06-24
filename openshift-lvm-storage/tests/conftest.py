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

Never run or recommend `pvcreate`, `vgcreate`, `vgremove`, `lvremove`, or `wipefs` before explicit destructive confirmation.

Use `readlink -f`, `lsblk -f`, `pvs`, `vgs`, `lvs`, and `wipefs -n` evidence.

Use stable `/dev/disk/by-id/*` paths.

For SNO, document the single-node constraint and keep exactly one default StorageClass.

Also keep one default StorageClass.

LVMCluster, thinPoolConfig, overprovisionRatio, sizePercent, deviceSelector, and forceWipeDevicesAndDestroyAllData are LVMS-specific.

Use `volumeBindingMode: WaitForFirstConsumer` and `topolvm.io` provisioner.

LogicalVolume CRs must be healthy.

On OpenShift, use MachineConfig, SCC, and reboot. Wait for MCP.

OLM and Subscription are used for install. CSV for upgrade.

Do not downgrade. Read release notes.

For upgrade, verify release notes.
"""

SKILL_TEMPLATE = """\
---
name: openshift-lvm-storage
description: Use when planning, installing, or troubleshooting LVMS on OpenShift.
---

# OpenShift LVM Storage Lifecycle

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

DEFAULT_SKILL_DESCRIPTION = (
    "Use when planning, installing, or troubleshooting LVMS on OpenShift."
)


def _make_skill_text(
    name: str = vsp.EXPECTED_NAME,
    description: str | None = DEFAULT_SKILL_DESCRIPTION,
    missing_sections: list[str] | None = None,
) -> str:
    text = SKILL_TEMPLATE
    if name != vsp.EXPECTED_NAME:
        text = text.replace("name: openshift-lvm-storage", f"name: {name}")
    if description is None:
        text = text.replace(
            "description: Use when planning, installing, or troubleshooting LVMS on OpenShift.\n",
            "",
        )
    else:
        text = text.replace(
            "description: Use when planning, installing, or troubleshooting LVMS on OpenShift.",
            f"description: {description}",
        )
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
        root = tmp_path / "openshift-lvm-storage"
        root.mkdir()

        refs = root / "references"
        refs.mkdir()

        (root / "SKILL.md").write_text(
            skill_text or make_skill_text(), encoding="utf-8"
        )
        (root / "README.md").write_text(
            "# OpenShift LVM Storage\n\nCurrent version: **1.0.0**\n", encoding="utf-8"
        )
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 1.0.0\n\n- Initial.\n", encoding="utf-8"
        )
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "openshift-lvm-storage",
                    "version": "1.0.0",
                    "description": "LVMS lifecycle",
                }
            ),
            encoding="utf-8",
        )
        (root / "assets").mkdir()
        (root / "assets" / "smoke-pvc-writer.yaml").write_text("", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "patch_lvms_manifest.py").write_text("", encoding="utf-8")
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
