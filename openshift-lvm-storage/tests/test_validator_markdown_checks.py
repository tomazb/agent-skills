from __future__ import annotations

import pytest


def test_markdown_no_trailing_newline(validator, tmp_path):
    path = tmp_path / "test.md"
    path.write_text("no newline", encoding="utf-8")
    issues = validator.check_markdown_file(path, tmp_path)
    assert any("missing trailing newline" in issue for issue in issues)


def test_markdown_trailing_newline_ok(validator, tmp_path):
    path = tmp_path / "test.md"
    path.write_text("has newline\n", encoding="utf-8")
    issues = validator.check_markdown_file(path, tmp_path)
    assert issues == []


def test_markdown_odd_fences(validator, tmp_path):
    path = tmp_path / "test.md"
    path.write_text("```\ncode\n", encoding="utf-8")
    issues = validator.check_markdown_file(path, tmp_path)
    assert any("odd number" in issue for issue in issues)


def test_markdown_even_fences(validator, tmp_path):
    path = tmp_path / "test.md"
    path.write_text("```\ncode\n```\n", encoding="utf-8")
    issues = validator.check_markdown_file(path, tmp_path)
    assert issues == []
