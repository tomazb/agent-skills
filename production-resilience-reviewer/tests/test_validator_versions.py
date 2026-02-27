from __future__ import annotations


def test_version_sync_match(validator, package_factory):
    root = package_factory()
    assert validator.check_version_sync(root) == []


def test_version_sync_mismatch(validator, package_factory):
    root = package_factory(
        package_json_text='{"name":"demo-skill","version":"9.9.9"}\n',
    )
    issues = validator.check_version_sync(root)
    assert len(issues) == 1
    assert "out of sync" in issues[0]


def test_version_sync_missing_files_is_noop(validator, package_factory):
    root = package_factory(include_version=False, include_package_json=True)
    assert validator.check_version_sync(root) == []

    root = package_factory(include_version=True, include_package_json=False)
    assert validator.check_version_sync(root) == []


def test_version_sync_invalid_package_json(validator, package_factory):
    root = package_factory(package_json_text='{"name": "demo-skill", "version": "1.2.3"')
    issues = validator.check_version_sync(root)
    assert issues == ["package.json is not valid JSON."]


def test_changelog_version_match(validator, package_factory):
    root = package_factory()
    assert validator.check_changelog_version(root) == []


def test_changelog_version_mismatch(validator, package_factory):
    root = package_factory(
        changelog_text="# Changelog\n\n## 9.9.9\n- New release.\n",
    )
    issues = validator.check_changelog_version(root)
    assert len(issues) == 1
    assert "does not contain a heading for VERSION '1.2.3'" in issues[0]


def test_changelog_version_missing_files_is_noop(validator, package_factory):
    root = package_factory(include_version=False, include_changelog=True)
    assert validator.check_changelog_version(root) == []

    root = package_factory(include_version=True, include_changelog=False)
    assert validator.check_changelog_version(root) == []
