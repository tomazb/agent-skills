# Changelog

## 5.2.0
- Added Lens 9: **Fault Domains & Disaster Recovery** to `SKILL.md` with RPO/RTO, backup/restore, replay, and failover checks.
- Added Lens 10: **Security & Abuse as Reliability** to `SKILL.md` with auth fail-open and abuse-path resilience checks.
- Added Lens 11: **Quota & Limit Exhaustion** to `SKILL.md` with quota inventory, saturation behavior, and cost/rate guardrails.
- Added deep-dive references:
  - `references/checklist-disaster-recovery.md`
  - `references/checklist-security-abuse-reliability.md`
  - `references/checklist-quota-limit-exhaustion.md`
- Validator updates:
  - lens heading check now enforces Lenses 1..11
  - expected reference list now includes the three new checklist files
  - `SKILL.md` line budget check now uses a configurable `MAX_SKILL_LINES` constant
- Updated README to document the 11-lens framework and new reference material.

## 5.1.0
- Added condensed `[CATEGORY]` examples to Lenses 3 (Network), 4 (Data), 5 (Retry), and 7 (Observability) for consistency with Lenses 1, 2, 6, 8.
- Validator: added reference file existence check (catches renamed/deleted reference files).
- Validator: added VERSION ↔ package.json version sync check.
- Validator: fixed leaked-TOC detector to scan all consecutive leaked lines (was limited to 2).
- Validator: removed redundant `import re` inside `check_lens_headings`; eliminated duplicate `read_text` calls.
- Fixed triple blank line between Lens 6 and Lens 7 in `SKILL.md`.
- Condensed Applicability Guidance, Review Calibration, and AI-Generated Code sections to stay within 500-line budget.
- Populated `package.json` with name, version, description, and keywords.

## 5.0.0
- Restored Lens 2 (Load & Concurrency) as a first-class lens in `SKILL.md`.
- Moved the `[LOAD]` example under Lens 2 and restored a `[DEPENDENCY]` example under Lens 1.
- Restored the concrete BAD/OKAY/GOOD 3 AM error-message progression under Lens 6.
- Enhanced the validation tool to ensure all eight lens headings are present (prevents this regression).

## 4.0.0
- Added `references/checklist-change-management.md` (Lens 8 deep-dive).
- Added cross-links in all reference checklists to:
  - `references/severity-calibration.md`
  - `references/validation-monitoring-patterns.md`
  - `references/checklist-change-management.md`
- Reduced `SKILL.md` to provide line-count headroom (now well under the 500-line guideline).
- Added package metadata files: `VERSION`, `CHANGELOG.md`.
- Added a lightweight validation script: `tools/validate_skill_package.py`.

## 3.x
- Introduced Lens 8 (Change Management & Rollback Safety) and extracted severity + validation/monitoring details into references.
- Fixed markdown formatting issues (stray TOC lines, missing trailing newlines, code fence termination).
