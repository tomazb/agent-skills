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
        make_skill_text_fn(description="Pressure-test product and architecture decisions.")
    )
    assert issues == ["SKILL.md: description must start with 'Use when'."]


def test_quoted_frontmatter_description_is_accepted(validator, make_skill_text_fn):
    skill_text = make_skill_text_fn().replace(
        "description: >\n  Use when a decision sounds reasonable but still needs pressure-testing before agreement, especially for scope, architecture, sequencing, or irreversible product trade-offs.",
        'description: "Use when a decision sounds reasonable but still needs pressure-testing before agreement."',
    )

    assert validator.check_skill_frontmatter(skill_text) == []


def test_folded_frontmatter_description_keeps_later_paragraphs(validator, make_skill_text_fn):
    skill_text = make_skill_text_fn().replace(
        "description: >\n  Use when a decision sounds reasonable but still needs pressure-testing before agreement, especially for scope, architecture, sequencing, or irreversible product trade-offs.",
        "description: >\n  Use when a decision sounds reasonable.\n\n  Second paragraph still belongs to the folded description.",
    )

    fields = validator.extract_frontmatter_fields(skill_text)

    assert fields["description"].startswith("Use when a decision sounds reasonable.")
    assert "Second paragraph still belongs" in fields["description"]


def test_literal_frontmatter_description_is_accepted(validator, make_skill_text_fn):
    skill_text = make_skill_text_fn().replace(
        "description: >\n  Use when a decision sounds reasonable but still needs pressure-testing before agreement, especially for scope, architecture, sequencing, or irreversible product trade-offs.",
        "description: |\n  Use when a decision sounds reasonable.\n  Keep challenging before agreement.",
    )

    assert validator.check_skill_frontmatter(skill_text) == []


def test_headings_inside_frontmatter_are_not_counted(validator, make_skill_text_fn):
    # A heading-like line living inside the folded `description: >` block must not
    # be mistaken for a real body heading; otherwise the validator would pass even
    # after the actual section was deleted.
    skill_text = make_skill_text_fn().replace(
        "  Use when a decision sounds reasonable but still needs pressure-testing before agreement, "
        "especially for scope, architecture, sequencing, or irreversible product trade-offs.",
        "  Use when a decision sounds reasonable.\n  ## Response pattern",
    ).replace("\n## Response pattern\n", "\n")

    assert "## Response pattern" not in validator.markdown_headings(skill_text)
    assert validator.check_required_sections(skill_text) == [
        "SKILL.md is missing required sections: ## Response pattern"
    ]


def test_guidance_guards_require_challenge_first_and_followup(
    validator, make_skill_text_fn
):
    issues = validator.check_guidance_guards(
        make_skill_text_fn(
            include_challenge_first=False,
            include_agreement_guard=False,
            include_counterarguments=False,
            include_forcing_question=False,
            include_followup=False,
        )
    )

    assert "SKILL.md: default stance must require challenge before agreement." in issues
    assert "SKILL.md: default stance must forbid agree-first language." in issues
    assert "SKILL.md: response pattern must surface the strongest counterarguments." in issues
    assert "SKILL.md: response pattern must end with a forcing question." in issues
    assert "SKILL.md: follow-up guidance must tell the model what to do after the user responds." in issues


def test_guidance_guards_allow_wrapped_followup_text(validator, make_skill_text_fn):
    skill_text = make_skill_text_fn().replace(
        "either endorse with conditions or propose the smaller move instead.",
        "either endorse\nwith conditions or propose the smaller move instead.",
    )

    assert validator.check_guidance_guards(skill_text) == []


def test_guidance_guards_allow_equivalent_followup_wording(
    validator, make_skill_text_fn
):
    skill_text = make_skill_text_fn().replace(
        "Re-evaluate with the new evidence, state the remaining risk, and either endorse with conditions or propose the smaller move instead.",
        "Reassess with the new evidence, state the remaining risk, and either endorse with conditions or propose the smaller move instead.",
    )

    assert validator.check_guidance_guards(skill_text) == []


def test_guidance_guards_allow_wrapped_response_pattern_steps(
    validator, make_skill_text_fn
):
    skill_text = make_skill_text_fn().replace(
        "2. Surface the strongest counterarguments first.",
        "2. Surface the strongest\ncounterarguments first.",
    ).replace(
        "4. End with a forcing question that makes the decision earn the next step.",
        "4. End with a forcing\nquestion that makes the decision earn the next step.",
    )

    assert validator.check_guidance_guards(skill_text) == []


def test_guidance_guards_do_not_accept_keywords_outside_the_actual_steps(
    validator, make_skill_text_fn
):
    skill_text = make_skill_text_fn().replace(
        "2. Surface the strongest counterarguments first.",
        "2. Surface counterarguments.",
    ).replace(
        "4. End with a forcing question that makes the decision earn the next step.",
        "4. End with a question.",
    ).replace(
        "Re-evaluate with the new evidence, state the remaining risk, and either endorse with conditions or propose the smaller move instead.",
        "Re-evaluate with the new evidence, state the remaining risk, and make the call.\n"
        "Note: if it survives, endorse with conditions or propose the smaller move instead.",
    )

    issues = validator.check_guidance_guards(skill_text)

    assert "SKILL.md: response pattern must surface the strongest counterarguments." in issues
    assert "SKILL.md: response pattern must end with a forcing question." in issues
    assert "SKILL.md: follow-up guidance must tell the model what to do after the user responds." in issues
