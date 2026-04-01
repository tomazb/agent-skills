from __future__ import annotations


def test_fence_count_ok_balanced(validator):
    assert validator.fence_count_ok("```bash\noc get nodes\n```\n")


def test_fence_count_ok_unclosed(validator):
    assert not validator.fence_count_ok("```bash\noc get nodes\n")


def test_fence_count_ok_empty(validator):
    assert validator.fence_count_ok("")


def test_check_markdown_file_trailing_newline_missing(validator, package_factory, tmp_path):
    md = tmp_path / "no_newline.md"
    md.write_bytes(b"# Title\nSome content")
    issues = validator.check_markdown_file(md, tmp_path)
    assert any("missing trailing newline" in issue for issue in issues)


def test_check_markdown_file_trailing_newline_present(validator, tmp_path):
    md = tmp_path / "ok.md"
    md.write_text("# Title\nSome content\n", encoding="utf-8")
    issues = validator.check_markdown_file(md, tmp_path)
    assert not any("missing trailing newline" in issue for issue in issues)


def test_check_markdown_file_unclosed_fence(validator, tmp_path):
    md = tmp_path / "unclosed.md"
    md.write_text("# Title\n\n```bash\noc get nodes\n", encoding="utf-8")
    issues = validator.check_markdown_file(md, tmp_path)
    assert any("odd number" in issue or "fences" in issue for issue in issues)


def test_validate_root_does_not_duplicate_skill_markdown_issues(validator, package_factory):
    no_trailing_newline = "# OC Health\n### Phase 0 \u2014 Test\n".rstrip("\n")
    root = package_factory(skill_text=no_trailing_newline)

    issues = validator.validate_root(root)
    newline_issues = [issue for issue in issues if "SKILL.md: missing trailing newline" == issue]
    assert len(newline_issues) == 1
