"""Keep snapshot readiness in every storage lifecycle and health assessment."""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STORAGE_SKILLS = [
    "openshift-rook",
    "openshift-odf",
    "openshift-longhorn",
    "openshift-lvm-storage",
]


def section(path, heading):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^## " + re.escape(heading) + r"\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"{path.relative_to(ROOT)} must include {heading}"
    return match.group(1)


@pytest.mark.parametrize("skill", STORAGE_SKILLS)
def test_snapshot_configuration_is_a_lifecycle_completion_requirement(skill):
    """A setup must not finish with supported drivers lacking snapshot classes."""
    root = ROOT / skill
    policy = section(root / "SKILL.md", "Snapshot readiness")
    assert "configure supported snapshotting by default" in policy
    assert "read-only" in policy
    assert "VolumeSnapshotClass" in policy
    assert "references/backup-restore-dr.md" in policy
    install = (root / "references/install-and-preflight.md").read_text(encoding="utf-8")
    assert "Snapshot readiness" in install and "backup-restore-dr.md" in install
    validation = section(root / "references/validation-hardening.md", "Snapshot readiness")
    assert "backup-restore-dr.md" in validation
    assert "Warning" in validation and "read-only" in validation


@pytest.mark.parametrize("skill", STORAGE_SKILLS)
def test_snapshot_report_separates_support_configuration_and_protection(skill):
    """A class or sidecar alone must not imply scheduling or recoverability."""
    readiness = section(ROOT / skill / "references/backup-restore-dr.md", "Snapshot readiness")
    for field in ["Supported", "Configured", "Scheduled", "Restore-tested"]:
        assert re.search(r"\| " + field + r" \|", readiness)
    for marker in ["VolumeSnapshotContent", "readyToUse", "deletionPolicy", "read-only", "off-cluster", "same driver"]:
        assert marker in readiness
    assert "snapshot.storage.kubernetes.io/is-default-class" in readiness
    assert "at most one" in readiness


def test_cluster_health_checks_missing_snapshot_classes_without_mutation():
    root = ROOT / "openshift-cluster-health-check"
    storage = (root / "references/checklist-storage.md").read_text(encoding="utf-8")
    assert "VolumeSnapshotClass" in storage
    assert "StorageClass.provisioner" in storage
    assert "Warning" in storage and "Not checked" in storage
    assert "Supported" in storage and "Restore-tested" in storage
    assert "read-only" in storage
    output = (root / "references/output-contract.md").read_text(encoding="utf-8")
    assert "Snapshot readiness" in output
