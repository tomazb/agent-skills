# Changelog

## 5.3.2
- Fixed `Fix:` → `Recommendation:` in Lens 9, 10, 11 condensed examples to match Lens 8 style (review finding).
- Removed orphaned trigger phrases from `README.md` that no longer appeared in `SKILL.md` frontmatter.
- Added 5.3.0 and 5.3.1 to `README.md` "Recent highlights" section.
- Synced `package.json` description with current trigger-oriented wording.
- Improved scanability of Severity Calibration section (added sub-heading for priority definitions).

## 5.3.1
- Improved skill triggering and applicability guidance:
  - Refactored `SKILL.md` frontmatter description to start with "Use when..." and emphasize trigger conditions.
  - Added explicit "Skip this skill for" exclusions (non-production artifacts, throwaway prototypes, one-off no-SLA scripts).
- Removed calibration ambiguity in `SKILL.md`:
  - Merged `Review Calibration` guidance into `Severity Calibration`.
  - Kept impact/likelihood/blast-radius/detectability method and embedded P0-P3 definitions in one section.
- Tightened consistency and output clarity:
  - Consolidated Lens 11 duplicated `P1-HIGH` wording into a single rule.
  - Aligned Lens 8 condensed example wording with the standard finding style (`Risk`/`Recommendation`).
  - Defined `quick wins` in Output Format as low-effort, high-impact same-session fixes.
- Synced package README usage guidance with SKILL trigger/exclusion semantics.

## 5.3.0
- Validator hardening and maintainability:
  - Refactored validator checks to use consistent list-returning interfaces.
  - Added `validate_root()` orchestration helper for cleaner composition and testing.
  - Prevented duplicate `SKILL.md` markdown checks by excluding it from the generic markdown scan loop.
  - Clarified leaked-TOC scanning variable names and scan flow.
  - Added lens-heading spacing validation (exactly one blank line after each `### Lens N` heading).
  - Added CHANGELOG/version alignment validation (`CHANGELOG.md` must include a heading matching `VERSION`).
- Added automated validator regression tests under `tests/` (line budget, code fences, leaked TOC detection, lens headings, references, version sync, duplicate-check regression).
- Expanded Lenses 9-11 in `SKILL.md` with richer inline guidance while keeping deep-dive reference links.
- Simplified `SKILL.md` frontmatter description wording for easier maintenance.
- Improved wrapper utility:
  - `tools/validate_skill_package.sh` now verifies Python availability/version and runs via deterministic script path.
- Added `tools/bump_version.py` to sync `VERSION`, `package.json`, and README current-version metadata in one command.
- Updated `README.md`:
  - removed hardcoded version number from the package-structure tree
  - documented validator tests and centralized version bump workflow

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
