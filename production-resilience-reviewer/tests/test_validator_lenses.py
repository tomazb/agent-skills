from __future__ import annotations

def test_lens_headings_validation_match(validator, make_skill_text):
    assert validator.check_lens_headings(make_skill_text()) == []


def test_lens_headings_validation_missing_lens(validator, make_skill_text):
    skill_text = make_skill_text().replace(
        "### Lens 12: Example\n\nLens 12 guidance.\n\n---\n", ""
    )
    issues = validator.check_lens_headings(skill_text)
    assert len(issues) == 1
    assert "expected [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]" in issues[0]


def test_expected_references_check(validator, package_factory):
    root = package_factory(include_references=False)
    issues = validator.check_expected_references(root)
    assert len(issues) == len(validator.EXPECTED_REFERENCES)


def test_resilience_guidance_guards_require_architecture_fit_calibration(
    validator, make_skill_text
):
    skill_text = make_skill_text()
    reference_text = "# ref\n"

    issues = validator.check_resilience_guidance_guards(skill_text, reference_text)

    assert "SKILL.md: description must target production architecture trade-offs affecting resilience, operability, cost, or failure modes." in issues
    assert any("Minimum evidence before judging" in issue for issue in issues)
    assert any("Right-Sized Resilience" in issue for issue in issues)
    assert any("fail-fast or queue-and-reconcile" in issue for issue in issues)


def test_resilience_guidance_guards_reject_weak_complexity_claims(validator):
    skill_text = (
        "production architecture trade-offs affecting resilience, operability, cost, or failure modes\n"
        "Minimum evidence before judging\n"
        "team size\nservice count\nownership model\ndeploy coupling\nshared data ownership\n"
        "request path depth\ntraffic/cost profile\nplatform/SRE support\nrecent incident/on-call pain\n"
        "Right-Sized Resilience\n"
        "Would fail-fast or queue-and-reconcile be safer than retrying?\n"
        "Are metrics/logs useful without creating cardinality or cost blowups?\n"
        "Does the RPO/RTO match business impact?\n"
        "Does the rollout mechanism reduce net risk?\n"
        "Can the expensive path be bounded, simplified, or removed?\n"
    )
    reference_text = "DZone 2024 says 35%; CNCF 2025 Survey says 42%; costs 3.75x-6x.\n"

    issues = validator.check_resilience_guidance_guards(skill_text, reference_text)

    assert any("unsupported complexity-tax claim" in issue for issue in issues)
