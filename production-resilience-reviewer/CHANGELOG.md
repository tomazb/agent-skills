# Changelog

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
