from __future__ import annotations


def test_fence_count_even_odd(validator):
    assert validator.fence_count_ok("```text\nhello\n```\n")
    assert not validator.fence_count_ok("```text\nhello\n")


def test_check_markdown_file_reports_missing_trailing_newline(tmp_path, validator):
    path = tmp_path / "README.md"
    path.write_text("# README", encoding="utf-8")
    issues = validator.check_markdown_file(path, tmp_path)
    assert issues == ["README.md: missing trailing newline"]


def test_description_must_start_with_use_when(validator, make_skill_text_fn):
    issues = validator.check_skill_frontmatter(
        make_skill_text_fn(description="Create and maintain skills in this collection.")
    )
    assert issues == ["SKILL.md: description must start with 'Use when'."]


def test_frontmatter_name_must_match_skill(validator, make_skill_text_fn):
    skill_text = make_skill_text_fn().replace(
        "name: skill-authoring", "name: other-skill"
    )
    issues = validator.check_skill_frontmatter(skill_text)
    assert issues == ["SKILL.md: frontmatter name must be 'skill-authoring'."]


def test_headings_inside_frontmatter_are_not_counted(validator, make_skill_text_fn):
    skill_text = make_skill_text_fn().replace(
        "Use when creating a new skill in this collection, or modifying an existing "
        "skill's SKILL.md, package layout, version, changelog, tests, or validation tooling.",
        "Use when creating a new skill.\n  ## Validation",
    ).replace("\n## Validation\n", "\n", 1)

    assert "## Validation" not in validator.markdown_headings(skill_text)
    assert validator.check_required_sections(skill_text) == [
        "SKILL.md is missing required sections: ## Validation"
    ]
