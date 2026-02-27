from __future__ import annotations

from conftest import make_skill_text


def test_lens_headings_validation_match(validator):
    assert validator.check_lens_headings(make_skill_text()) == []


def test_lens_headings_validation_missing_lens(validator):
    skill_text = make_skill_text().replace("### Lens 11: Example\n\nLens 11 guidance.\n\n---\n", "")
    issues = validator.check_lens_headings(skill_text)
    assert len(issues) == 1
    assert "expected [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]" in issues[0]


def test_expected_references_check(validator, package_factory):
    root = package_factory(include_references=False)
    issues = validator.check_expected_references(root)
    assert len(issues) == len(validator.EXPECTED_REFERENCES)
