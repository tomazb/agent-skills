from __future__ import annotations


def test_required_sections_present(validator, package_factory):
    root = package_factory()
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert validator.check_required_sections(skill_text) == []


def test_required_sections_missing_one(validator, package_factory):
    root = package_factory(
        skill_text=package_factory.__globals__["make_skill_text"](
            missing_sections=["## Output Contract"]
        )
    )
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    issues = validator.check_required_sections(skill_text)
    assert len(issues) == 1
    assert "## Output Contract" in issues[0]


def test_mode_default_rule_present(validator, package_factory):
    root = package_factory()
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert validator.check_mode_default_rule(skill_text) == []


def test_expected_references_present(validator, package_factory):
    root = package_factory()
    assert validator.check_expected_references(root) == []


def test_validate_root_clean_package(validator, package_factory):
    root = package_factory()
    assert validator.validate_root(root) == []
