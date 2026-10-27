from __future__ import annotations

from pathlib import Path

import validate_skill_package as validator


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_package_validates():
    assert validator.validate_root(PACKAGE_ROOT) == []


def test_section_check_ignores_fenced_headings():
    text = "```\n## Routing\n```\n"
    issues = validator.check_required_sections(text)
    assert any("## Routing" in issue for issue in issues)
