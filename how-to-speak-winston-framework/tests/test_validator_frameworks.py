from __future__ import annotations

from conftest import make_skill_text


def test_framework_headings_all_present(validator):
    assert validator.check_framework_headings(make_skill_text()) == []


def test_framework_headings_missing_one(validator):
    skill_text = make_skill_text(missing_frameworks=[10])
    issues = validator.check_framework_headings(skill_text)
    assert len(issues) == 1
    assert "expected [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]" in issues[0]


def test_framework_headings_missing_multiple(validator):
    skill_text = make_skill_text(missing_frameworks=[4, 7])
    issues = validator.check_framework_headings(skill_text)
    assert len(issues) == 1
    assert "expected [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]" in issues[0]


def test_framework_spacing_correct(validator, package_factory):
    root = package_factory()
    issues = validator.check_skill_file(root)
    spacing_issues = [i for i in issues if "blank line" in i]
    assert spacing_issues == []


def test_framework_spacing_detects_double_blank(validator, package_factory):
    root = package_factory(skill_text=make_skill_text(double_blank_after_framework=3))
    issues = validator.check_skill_file(root)
    assert any("must be followed by exactly 1 blank line" in i for i in issues)


def test_expected_references_all_present(validator, package_factory):
    root = package_factory()
    assert validator.check_expected_references(root) == []


def test_expected_references_missing(validator, package_factory):
    root = package_factory(include_references=False)
    issues = validator.check_expected_references(root)
    assert len(issues) == len(validator.EXPECTED_REFERENCES)
