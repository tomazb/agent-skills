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


def test_indented_fence_hides_an_unindented_heading():
    text = "  ```\n## Routing\n  ```\n## Preconditions\n"
    headings = validator.heading_lines(text)
    assert headings == ["## Preconditions"]
    issues = validator.check_required_sections(text)
    assert any("## Routing" in issue for issue in issues)


def test_four_space_backticks_do_not_hide_a_heading():
    text = "    ```\n## Routing\n    ```\n"
    assert "## Routing" in validator.heading_lines(text)


def test_frontmatter_rejects_invalid_yaml_and_non_strings():
    invalid = "---\nname: openshift-sno-registry\ndescription: Use when: deploying\n---\n"
    assert validator.parse_frontmatter(invalid) is None
    assert any("invalid" in issue for issue in validator.frontmatter_issues(invalid))

    boolean_description = "---\nname: openshift-sno-registry\ndescription: true\n---\n"
    assert any("strings" in issue for issue in validator.frontmatter_issues(boolean_description))

    numeric_name = "---\nname: 1\ndescription: Use when deploying\n---\n"
    assert any("strings" in issue for issue in validator.frontmatter_issues(numeric_name))

    quoted = '---\nname: openshift-sno-registry\ndescription: "Use when: deploying"\n---\n'
    assert validator.frontmatter_issues(quoted) == []

    legacy_tools = "---\nname: openshift-sno-registry\ndescription: Use when deploying\ntools: bash\n---\n"
    assert any("tools" in issue for issue in validator.frontmatter_issues(legacy_tools))
