from __future__ import annotations


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
    (root / "scripts" / "discover_tls.py").unlink()
    issues = validator.check_required_files(root)
    assert any("discover_tls.py" in issue for issue in issues)


def test_expected_references_missing(validator, package_factory):
    root = package_factory()
    (root / "references" / "acme-dns01.md").unlink()
    issues = validator.check_expected_references(root)
    assert any("acme-dns01.md" in issue for issue in issues)


def test_required_sections_missing(validator, package_factory):
    root = package_factory(
        skill_text=(
            "---\nname: openshift-cert-manager\n"
            "description: Use when demo.\n---\n\n# Routing\n\n## Routing\n\nr\n"
        )
    )
    issues = validator.check_required_sections(
        (root / "SKILL.md").read_text(encoding="utf-8")
    )
    assert any("Core Safety Rules" in issue for issue in issues)


def test_phrase_group_missing(validator):
    text = "Some unrelated text."
    issues = validator.check_phrase_group(text, ["DNS-01", "HTTP-01"], "acme")
    assert any("DNS-01" in issue for issue in issues)


def test_phrase_group_present(validator):
    text = "Use HTTP-01 and DNS-01."
    issues = validator.check_phrase_group(text, ["HTTP-01", "DNS-01"], "acme")
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


def test_helper_invocations_missing(validator, package_factory):
    root = package_factory(reference_content="# empty\n")
    issues = validator.check_helper_invocations(root)
    assert issues
    assert any("discover_tls.py" in issue for issue in issues)


def test_validate_root_passes_on_factory(validator, package_factory):
    root = package_factory()
    issues = validator.validate_root(root)
    assert issues == []
