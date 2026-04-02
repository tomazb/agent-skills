from __future__ import annotations


def test_required_sections_present(validator, package_factory):
    root = package_factory()
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert validator.check_required_sections(skill_text) == []


def test_required_sections_missing_one(validator, package_factory):
    root = package_factory(
        skill_text=package_factory.__globals__["make_skill_text"](
            missing_sections=["## Verification"]
        )
    )
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    issues = validator.check_required_sections(skill_text)
    assert len(issues) == 1
    assert "## Verification" in issues[0]


def test_expected_references_present(validator, package_factory):
    root = package_factory()
    assert validator.check_expected_references(root) == []


def test_expected_references_include_php(validator):
    assert "references/php.md" in validator.EXPECTED_REFERENCES


def test_expected_references_missing_one(validator, package_factory):
    root = package_factory()
    missing_ref = root / validator.EXPECTED_REFERENCES[0]
    missing_ref.unlink()
    issues = validator.check_expected_references(root)
    assert issues == [f"Missing expected reference: {validator.EXPECTED_REFERENCES[0]}"]


def test_validate_root_clean_package(validator, package_factory):
    root = package_factory()
    assert validator.validate_root(root) == []
