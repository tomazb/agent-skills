from __future__ import annotations


def test_fence_count_even(validator):
    assert validator.fence_count_ok("```txt\nhello\n```\n")


def test_fence_count_odd(validator):
    assert not validator.fence_count_ok("```txt\nhello\n")


def test_check_markdown_file_trailing_newline(tmp_path, validator):
    path = tmp_path / "README.md"
    path.write_text("# README", encoding="utf-8")
    issues = validator.check_markdown_file(path, tmp_path)
    assert issues == ["README.md: missing trailing newline"]


def test_check_markdown_file_clean(tmp_path, validator):
    path = tmp_path / "README.md"
    path.write_text("# README\n", encoding="utf-8")
    issues = validator.check_markdown_file(path, tmp_path)
    assert issues == []
