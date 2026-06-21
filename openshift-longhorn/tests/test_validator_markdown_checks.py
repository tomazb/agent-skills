from __future__ import annotations


def test_fence_count_ok_balanced(validator):
    assert validator.fence_count_ok("```bash\noc get nodes\n```\n")


def test_fence_count_ok_unclosed(validator):
    assert not validator.fence_count_ok("```bash\noc get nodes\n")


def test_check_markdown_file_trailing_newline_missing(validator, tmp_path):
    md = tmp_path / "no_newline.md"
    md.write_bytes(b"# Title\nSome content")
    issues = validator.check_markdown_file(md, tmp_path)
    assert any("missing trailing newline" in issue for issue in issues)


def test_check_markdown_file_unclosed_fence(validator, tmp_path):
    md = tmp_path / "unclosed.md"
    md.write_text("# Title\n\n```bash\noc get nodes\n", encoding="utf-8")
    issues = validator.check_markdown_file(md, tmp_path)
    assert any("fences" in issue for issue in issues)
