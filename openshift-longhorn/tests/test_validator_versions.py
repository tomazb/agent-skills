from __future__ import annotations

import json


def test_version_sync_passes(validator, package_factory):
    root = package_factory()
    assert validator.check_version_sync(root) == []


def test_version_sync_fails_on_package_mismatch(validator, package_factory):
    package_json = json.dumps({"name": "openshift-longhorn", "version": "9.9.9"}, indent=2) + "\n"
    root = package_factory(package_json_text=package_json)
    issues = validator.check_version_sync(root)
    assert any("out of sync" in issue for issue in issues)


def test_package_name_mismatch_fails(validator, package_factory):
    package_json = json.dumps({"name": "other", "version": "1.2.3"}, indent=2) + "\n"
    root = package_factory(package_json_text=package_json)
    issues = validator.check_version_sync(root)
    assert any("package.json name" in issue for issue in issues)


def test_changelog_version_required(validator, package_factory):
    root = package_factory(changelog_text="# Changelog\n\n## 0.0.1\n\n- Old.\n")
    issues = validator.check_changelog_version(root)
    assert any("CHANGELOG.md" in issue for issue in issues)
