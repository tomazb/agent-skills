from __future__ import annotations


def test_version_sync_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_version_sync(root)
    assert issues == []


def test_changelog_version_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_changelog_version(root)
    assert issues == []


def test_readme_version_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_readme_version(root)
    assert issues == []


def test_frontmatter_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_frontmatter(root)
    assert issues == []


def test_versions_handoff_ok(validator, package_factory):
    root = package_factory()
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    issues = validator.check_versions_handoff(skill_text)
    assert issues == []


def test_versions_handoff_missing_clarification(validator, make_skill_text):
    text = make_skill_text().replace(
        "Release availability is not cluster upgrade readiness.",
        "See release notes.",
    )
    issues = validator.check_versions_handoff(text)
    assert any("not cluster upgrade readiness" in issue for issue in issues)
