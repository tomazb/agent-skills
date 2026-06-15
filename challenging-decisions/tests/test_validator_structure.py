from __future__ import annotations

import shutil
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_required_files_present(validator, package_factory):
    root = package_factory()
    assert validator.check_required_files(root) == []


def test_required_files_missing_baseline_fixture(validator, package_factory):
    root = package_factory(include_baseline=False)
    issues = validator.check_required_files(root)
    assert "Missing required file: tests/test_skill_baseline.md" in issues


def test_required_sections_present(validator, package_factory):
    root = package_factory()
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert validator.check_required_sections(skill_text) == []


def test_required_sections_missing_one(validator, package_factory, make_skill_text_fn):
    root = package_factory(
        skill_text=make_skill_text_fn(missing_sections=["## Response pattern"])
    )
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    issues = validator.check_required_sections(skill_text)
    assert len(issues) == 1
    assert "## Response pattern" in issues[0]


def test_required_sections_do_not_accept_heading_text_in_prose(
    validator, package_factory, make_skill_text_fn
):
    skill_text = (
        make_skill_text_fn(missing_sections=["## Response pattern"])
        + "\nThis prose mentions ## Response pattern but never defines it as a heading.\n"
    )
    root = package_factory(skill_text=skill_text)

    issues = validator.check_required_sections((root / "SKILL.md").read_text(encoding="utf-8"))

    assert len(issues) == 1
    assert "## Response pattern" in issues[0]


def test_lens_headings_validation_missing_lens(
    validator, package_factory, make_skill_text_fn
):
    root = package_factory(
        skill_text=make_skill_text_fn(missing_lenses=["### Reversibility Lens"])
    )
    issues = validator.check_lens_headings((root / "SKILL.md").read_text(encoding="utf-8"))
    assert len(issues) == 1
    assert "### Reversibility Lens" in issues[0]


def test_lens_headings_do_not_accept_heading_text_in_prose(
    validator, package_factory, make_skill_text_fn
):
    skill_text = (
        make_skill_text_fn(missing_lenses=["### Reversibility Lens"])
        + "\nThis prose mentions ### Reversibility Lens but never defines it as a heading.\n"
    )
    root = package_factory(skill_text=skill_text)

    issues = validator.check_lens_headings((root / "SKILL.md").read_text(encoding="utf-8"))

    assert len(issues) == 1
    assert "### Reversibility Lens" in issues[0]


def test_required_sections_do_not_accept_headings_inside_fenced_code_blocks(
    validator, package_factory, make_skill_text_fn
):
    skill_text = (
        make_skill_text_fn(missing_sections=["## Response pattern"])
        + "\n```md\n## Response pattern\n1. Not real structure.\n```\n"
    )
    root = package_factory(skill_text=skill_text)

    issues = validator.check_required_sections((root / "SKILL.md").read_text(encoding="utf-8"))

    assert len(issues) == 1
    assert "## Response pattern" in issues[0]


def test_lens_headings_do_not_accept_headings_inside_fenced_code_blocks(
    validator, package_factory, make_skill_text_fn
):
    skill_text = (
        make_skill_text_fn(missing_lenses=["### Reversibility Lens"])
        + "\n```md\n### Reversibility Lens\nNot a real lens section.\n```\n"
    )
    root = package_factory(skill_text=skill_text)

    issues = validator.check_lens_headings((root / "SKILL.md").read_text(encoding="utf-8"))

    assert len(issues) == 1
    assert "### Reversibility Lens" in issues[0]


def test_validate_root_clean_package(validator, package_factory):
    root = package_factory()
    assert validator.validate_root(root) == []


def test_validate_root_reports_invalid_python_tool(validator, package_factory):
    root = package_factory(tool_python_text="def broken(:\n")
    issues = validator.validate_root(root)
    assert any("tools/bump_version.py" in issue for issue in issues)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not found")
def test_validate_root_reports_invalid_shell_tool(validator, package_factory):
    root = package_factory(tool_shell_text="if [ -n \"$BROKEN\"; then\n")
    issues = validator.validate_root(root)
    assert any("tools/validate_skill_package.sh" in issue for issue in issues)


def test_validate_real_package(validator):
    assert validator.validate_root(PACKAGE_ROOT) == []
