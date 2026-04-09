from __future__ import annotations


def test_version_sync_match(validator, package_factory):
    root = package_factory()
    assert validator.check_version_sync(root) == []


def test_version_sync_mismatch(validator, package_factory):
    root = package_factory(
        package_json_text='{"name":"qa-agent","version":"9.9.9"}\n',
    )
    issues = validator.check_version_sync(root)
    assert len(issues) == 1
    assert "out of sync" in issues[0]


def test_version_sync_missing_files(validator, package_factory):
    root = package_factory(include_version=False)
    issues = validator.check_version_sync(root)
    assert issues == ["Missing VERSION file."]

    root = package_factory(include_package_json=False)
    issues = validator.check_version_sync(root)
    assert issues == ["Missing package.json file."]


def test_version_sync_invalid_package_json(validator, package_factory):
    root = package_factory(package_json_text='{"name": "qa-agent", "version": "1.2.3"')
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


def test_changelog_version_missing_file(validator, package_factory):
    root = package_factory(include_changelog=False)
    issues = validator.check_changelog_version(root)
    assert issues == ["Missing CHANGELOG.md file."]
