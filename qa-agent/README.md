# QA Agent

## TLDR

A risk-first QA skill for requirement tracing, test planning, bug reproduction,
regression protection, and evidence-based release recommendations.

---

## Overview

The QA Agent helps coding agents and reviewers answer one question with evidence:
"is this change safe to ship?"

It supports five operating modes:

- review
- test-plan
- execute
- regression
- bug-hunt

When mode is not specified, default is review. Mixed intent uses an explicit
two-phase sequence.

---

## Key Features

- Requirement-to-test traceability and ambiguity reporting
- Risk-based test prioritization
- Structured defect reports with reproducible evidence
- Regression-focused blast radius analysis
- Mode-aware output contracts for multi-agent consistency

---

## Package Structure

```text
qa-agent/
├── SKILL.md
├── README.md
├── VERSION
├── CHANGELOG.md
├── package.json
├── references/
├── tests/
└── tools/
```

---

## References

- references/checklist-requirement-tracing.md
- references/checklist-edge-cases.md
- references/checklist-error-paths.md
- references/regression-test-strategy.md
- references/severity-calibration.md
- references/framework-pytest.md
- references/framework-jest.md
- references/framework-junit.md
- references/api-contract-checklist.md

---

## Validation

Run package validation:

```bash
bash tools/validate_skill_package.sh
```

Run validator tests:

```bash
pytest -q
```

---

## Version Management

```bash
python3 tools/bump_version.py <new-version>
```

This updates VERSION, package.json, and the README version line.

Current version: **0.1.0**
