from __future__ import annotations

from pathlib import Path


def test_version_sync_matches(validator, package_factory):
    root = package_factory()
    assert validator.check_version_sync(root) == []


def test_version_sync_mismatch_fails(validator, package_factory):
    root = package_factory()
    (root / "package.json").write_text(
        '{"name": "openshift-odf", "version": "9.9.9"}', encoding="utf-8"
    )
    issues = validator.check_version_sync(root)
    assert any("out of sync" in issue for issue in issues)


def test_changelog_version_found(validator, package_factory):
    root = package_factory()
    assert validator.check_changelog_version(root) == []


def test_changelog_version_missing_fails(validator, package_factory):
    root = package_factory()
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    issues = validator.check_changelog_version(root)
    assert any("does not contain a heading" in issue for issue in issues)
