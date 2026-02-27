from __future__ import annotations

from conftest import make_skill_text


def test_skill_line_count_enforcement(validator, package_factory):
    long_skill = make_skill_text() + ("extra line\n" * validator.MAX_SKILL_LINES)
    root = package_factory(skill_text=long_skill)

    issues = validator.check_skill_file(root)
    assert any("SKILL.md is" in issue for issue in issues)


def test_lens_spacing_detects_double_blank_line(validator, package_factory):
    root = package_factory(skill_text=make_skill_text(double_blank_after_lens=3))

    issues = validator.check_skill_file(root)
    assert any("must be followed by exactly 1 blank line" in issue for issue in issues)


def test_validate_root_does_not_duplicate_skill_markdown_issues(validator, package_factory):
    no_trailing_newline = make_skill_text().rstrip("\n")
    root = package_factory(skill_text=no_trailing_newline)

    issues = validator.validate_root(root)
    newline_issues = [issue for issue in issues if issue == "SKILL.md: missing trailing newline"]
    assert len(newline_issues) == 1
