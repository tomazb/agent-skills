from __future__ import annotations

import pytest


UNSAFE_PATTERNS_UNDER_TEST = (
    "If 3+ of these 11 signals",
    "├─ 5xx → Retry with backoff",
    "retry only at outermost layer",
    "Logs, metrics, and error payloads include the same primary request identifier",
    "If a label can have more than ~100 unique values",
    "load test at 1×/5×/10×",
    "at least quarterly for critical paths",
    "30-50% on critical dependencies",
    "timeout=5, idempotency_key=request_id",
    "@retry(",
)


def skill_with_required_correctness_guidance(validator) -> str:
    return "\n".join(validator.REQUIRED_CORRECTNESS_GUIDANCE_PHRASES) + "\n"


def test_correctness_guidance_accepts_required_rules(validator):
    skill_text = skill_with_required_correctness_guidance(validator)

    issues = validator.check_correctness_guidance_guards(skill_text, {})

    assert issues == []


def test_correctness_guidance_reports_missing_required_rule(validator):
    missing = validator.REQUIRED_CORRECTNESS_GUIDANCE_PHRASES[0]
    skill_text = "\n".join(validator.REQUIRED_CORRECTNESS_GUIDANCE_PHRASES[1:])

    issues = validator.check_correctness_guidance_guards(skill_text, {})

    assert issues == [f"SKILL.md: missing correctness guidance phrase: {missing}"]


def test_correctness_guidance_unsafe_patterns_stay_in_sync(validator):
    assert tuple(validator.UNSAFE_GUIDANCE_PATTERNS) == UNSAFE_PATTERNS_UNDER_TEST


@pytest.mark.parametrize("unsafe_pattern", UNSAFE_PATTERNS_UNDER_TEST)
def test_correctness_guidance_rejects_unsafe_patterns(validator, unsafe_pattern):
    skill_text = skill_with_required_correctness_guidance(validator)
    reference_texts = {"references/demo.md": f"before {unsafe_pattern} after\n"}

    issues = validator.check_correctness_guidance_guards(
        skill_text, reference_texts
    )

    assert issues == [
        f"references/demo.md: unsafe resilience guidance pattern: {unsafe_pattern}"
    ]
