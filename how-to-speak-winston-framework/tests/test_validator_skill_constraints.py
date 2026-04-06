from __future__ import annotations

from conftest import make_skill_text


def test_required_sections_all_present(validator, package_factory):
    root = package_factory()
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert validator.check_required_sections(skill_text) == []


def test_required_sections_missing_one(validator):
    skill_text = make_skill_text(missing_sections=["## Operating Modes"])
    issues = validator.check_required_sections(skill_text)
    assert len(issues) == 1
    assert "## Operating Modes" in issues[0]


def test_skill_line_count_enforcement(validator, package_factory):
    long_skill = make_skill_text() + ("extra line\n" * validator.MAX_SKILL_LINES)
    root = package_factory(skill_text=long_skill)
    issues = validator.check_skill_file(root)
    assert any("SKILL.md is" in i for i in issues)


def test_validate_root_clean_package(validator, package_factory):
    root = package_factory()
    assert validator.validate_root(root) == []


def test_validate_root_no_duplicate_skill_issues(validator, package_factory):
    no_trailing_newline = make_skill_text().rstrip("\n")
    root = package_factory(skill_text=no_trailing_newline)
    issues = validator.validate_root(root)
    newline_issues = [i for i in issues if i == "SKILL.md: missing trailing newline"]
    assert len(newline_issues) == 1
