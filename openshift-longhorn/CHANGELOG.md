# Changelog

## 1.1.0

- Fixed the OpenShift uninstall runbook to delete the `longhorn-okd.yaml` manifest that install applies, and added a Helm uninstall path.
- Hardened the package validator: phrase checks run in a single pass, scan only runbooks (not README/CHANGELOG), and a new check keeps the README version in sync with `VERSION`.
- Excluded the development `tests/` suite from the packaged `.skill` archive so it stays self-contained.
- Repaired validator tests that passed for the wrong reason (no-op `replace` calls) and added positive/negative phrase-detection coverage.
- Tightened the `SKILL.md` description and removed an empty heading from the validated SNO evidence journal.

## 1.0.0

- Refactored `SKILL.md` into a concise lifecycle router.
- Added focused OpenShift/OKD Longhorn lifecycle reference runbooks.
- Moved the validated OpenShift 4.22 SNO V2 journal into `references/`.
- Added package metadata and validation tests for lifecycle references, safety gates, SNO defaults, V2 prerequisites, and markdown hygiene.
