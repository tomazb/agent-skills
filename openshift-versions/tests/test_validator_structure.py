from __future__ import annotations


def test_version_sync_match(validator, package_factory):
    root = package_factory()
    assert validator.check_version_sync(root) == []


def test_version_sync_mismatch(validator, package_factory):
    root = package_factory(
        package_json_text='{"name":"openshift-versions","version":"9.9.9"}\n',
    )
    issues = validator.check_version_sync(root)
    assert len(issues) == 1
    assert "out of sync" in issues[0]


def test_version_sync_missing_version_file(validator, package_factory):
    root = package_factory(include_version=False, include_package_json=True)
    issues = validator.check_version_sync(root)
    assert issues == ["Missing VERSION file."]


def test_version_sync_missing_package_json(validator, package_factory):
    root = package_factory(include_version=True, include_package_json=False)
    issues = validator.check_version_sync(root)
    assert issues == ["Missing package.json file."]


def test_version_sync_invalid_package_json(validator, package_factory):
    root = package_factory(
        package_json_text='{"name": "openshift-versions", "version": "1.2.3"'
    )
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


def test_changelog_version_missing_version_file_is_noop(validator, package_factory):
    root = package_factory(include_version=False, include_changelog=True)
    assert validator.check_changelog_version(root) == []


def test_changelog_version_missing_changelog(validator, package_factory):
    root = package_factory(include_version=True, include_changelog=False)
    issues = validator.check_changelog_version(root)
    assert issues == ["Missing CHANGELOG.md file."]


def test_changelog_accepts_v_prefix(validator, package_factory):
    root = package_factory(
        changelog_text="# Changelog\n\n## v1.2.3\n- Release.\n",
    )
    assert validator.check_changelog_version(root) == []


def test_validate_root_missing_skill_md(validator, tmp_path):
    root = tmp_path / "empty_pkg"
    root.mkdir()
    issues = validator.validate_root(root)
    assert any("Missing SKILL.md" in i for i in issues)


def test_validate_root_clean_package(validator, package_factory):
    root = package_factory()
    issues = validator.validate_root(root)
    assert issues == [], f"Expected no issues, got: {issues}"


def test_markdown_trailing_newline_missing(validator, tmp_path):
    md = tmp_path / "no_newline.md"
    md.write_bytes(b"# Title")
    issues = validator.check_markdown_file(md, tmp_path)
    assert any("missing trailing newline" in i for i in issues)


def test_markdown_unclosed_fence(validator, tmp_path):
    md = tmp_path / "unclosed.md"
    md.write_text("# Title\n\n```bash\necho hello\n", encoding="utf-8")
    issues = validator.check_markdown_file(md, tmp_path)
    assert any("fences" in i for i in issues)
