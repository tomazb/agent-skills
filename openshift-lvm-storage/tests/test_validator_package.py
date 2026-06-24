from __future__ import annotations

import pytest


def test_frontmatter_name_mismatch(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(name="wrong-name"))
    issues = validator.check_frontmatter(root)
    assert any("wrong-name" in issue for issue in issues)


def test_frontmatter_description_missing(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(description=None))
    issues = validator.check_frontmatter(root)
    assert any("missing frontmatter description" in issue for issue in issues)


def test_frontmatter_description_must_start_with_use_when(
    validator, package_factory, make_skill_text
):
    root = package_factory(skill_text=make_skill_text(description="A description."))
    issues = validator.check_frontmatter(root)
    assert any("Use when" in issue for issue in issues)


def test_check_required_files_missing(validator, package_factory):
    root = package_factory()
    (root / "scripts" / "patch_lvms_manifest.py").unlink()
    issues = validator.check_required_files(root)
    assert any("patch_lvms_manifest.py" in issue for issue in issues)


def test_expected_references_missing(validator, package_factory):
    root = package_factory()
    (root / "references" / "upgrade.md").unlink()
    issues = validator.check_expected_references(root)
    assert any("upgrade.md" in issue for issue in issues)


def test_required_sections_missing(validator, package_factory):
    root = package_factory(
        skill_text="---\nname: openshift-lvm-storage\ndescription: Use when demo.\n---\n\n# Routing\n\n## Routing\n\nr\n"
    )
    issues = validator.check_required_sections(
        (root / "SKILL.md").read_text(encoding="utf-8")
    )
    assert any("Core Safety Rules" in issue for issue in issues)


def test_phrase_group_missing(validator):
    text = "Some unrelated text."
    issues = validator.check_phrase_group(text, ["pvs", "lvs"], "safety")
    assert any("pvs" in issue for issue in issues)


def test_phrase_group_present(validator):
    text = "Use pvs and vgs and lvs."
    issues = validator.check_phrase_group(text, ["pvs", "lvs"], "safety")
    assert issues == []


def test_package_markdown_text_excludes_readme_changelog(validator, package_factory):
    root = package_factory()
    text = validator.package_markdown_text(root)
    assert "Current version" not in text
    assert "Changelog" not in text


def test_check_version_sync_mismatch(validator, package_factory):
    root = package_factory()
    (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    issues = validator.check_version_sync(root)
    assert any("out of sync" in issue for issue in issues)


def test_check_version_sync_name_mismatch(validator, package_factory):
    root = package_factory()
    (root / "package.json").write_text(
        '{"name": "wrong-name", "version": "1.0.0"}', encoding="utf-8"
    )
    issues = validator.check_version_sync(root)
    assert any("wrong-name" in issue for issue in issues)


def test_check_changelog_version_missing(validator, package_factory):
    root = package_factory()
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.9.0\n\n- Old.\n", encoding="utf-8"
    )
    issues = validator.check_changelog_version(root)
    assert any("1.0.0" in issue for issue in issues)


def test_check_readme_version_missing(validator, package_factory):
    root = package_factory()
    (root / "README.md").write_text("# OpenShift LVM Storage\n", encoding="utf-8")
    issues = validator.check_readme_version(root)
    assert any("Current version" in issue for issue in issues)


def test_check_readme_version_mismatch(validator, package_factory):
    root = package_factory()
    (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    issues = validator.check_readme_version(root)
    assert any("out of sync" in issue for issue in issues)


def test_fence_count_odd(validator):
    text = "Some text\n```\ncode\n"
    assert not validator.fence_count_ok(text)


def test_fence_count_even(validator):
    text = "Some text\n```\ncode\n```\n"
    assert validator.fence_count_ok(text)


def test_ends_with_newline(validator, tmp_path):
    path = tmp_path / "test.md"
    path.write_text("no newline", encoding="utf-8")
    assert not validator.ends_with_newline(path)


def test_ends_with_newline_ok(validator, tmp_path):
    path = tmp_path / "test.md"
    path.write_text("has newline\n", encoding="utf-8")
    assert validator.ends_with_newline(path)


def test_validate_root_passes(validator, package_factory):
    root = package_factory()
    issues = validator.validate_root(root)
    assert issues == []
