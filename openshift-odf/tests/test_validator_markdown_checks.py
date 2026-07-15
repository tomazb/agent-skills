from __future__ import annotations

from pathlib import Path


def test_markdown_files_have_trailing_newlines(validator, package_factory):
    root = package_factory()
    for md_file in root.rglob("*.md"):
        assert validator.ends_with_newline(md_file)


def test_markdown_files_have_even_fence_counts(validator, package_factory):
    root = package_factory()
    for md_file in root.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        assert validator.fence_count_ok(text)
