# Changelog

## 1.0.0

- Initial packaged release of the OpenShift cluster health check skill.
- Restructured from a monolithic SKILL.md into a versioned skill package with references, tooling, and tests.
- SKILL.md is now a lean orchestration document; deep-dive diagnostics live in `references/`.
- Added `references/checklist-etcd.md` – extended etcd member/endpoint diagnostics and performance signals.
- Added `references/checklist-authentication.md` – detailed OAuth server and identity provider diagnostics.
- Added `references/checklist-networking.md` – OVN-Kubernetes and OpenShiftSDN deep-dive checks.
- Added `references/checklist-storage.md` – PV/PVC triage and platform-specific CSI driver checks.
- Added `references/checklist-platform-specific.md` – full bare metal (IPI/UPI/Metal3/Ironic), vSphere, AWS, Azure, and GCP diagnostic commands.
- Added `references/checklist-pods-analysis.md` – pending and crashing pod classification logic, decision matrix, aggregate view commands.
- Added `references/severity-calibration.md` – health tier definitions, SNO and compact topology rules, severity modifiers.
- Added `references/output-contract.md` – full output format specification and response style guidance.
- Added `tools/validate_skill_package.py` – validates frontmatter, markdown hygiene, phase headings, version sync, changelog alignment, and reference file presence.
- Added `tools/validate_skill_package.sh` – CI-friendly shell wrapper for the validator.
- Added `tools/bump_version.py` – synchronises VERSION, package.json, and README version anchor.
- Added `tests/` – pytest suite covering validator logic: markdown checks, version sync, changelog match, phase headings, and reference file checks.
- Diagnostic workflow behavior unchanged: same 17 phases (Phase 0–16), same health model (Healthy / Warning / Critical), same safety rules.
