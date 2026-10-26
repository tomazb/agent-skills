# Rook lifecycle fixes for issue 38

Goal: turn the live reinstall findings into safe, repeatable skill behavior.
Architecture: preserve the existing ownership and exact-disk gates. Correct the
uninstall runbook in place; add small read-only planning/health helpers and a
scoped RGW smoke helper. No live cluster changes are part of this implementation.
Python helpers remain compatible with Python 3.9 and require no new local packages.

- [x] Reproduce the ClientProfile/CephConnection finalization dependency using
  `tests/rook_cluster_fake.py` and a focused `test_csi_teardown_order.py`; change
  `references/maintenance-uninstall.md` to delete and wait in dependency order.
- [x] Add `scripts/plan_osd_disk_prep.py` and command-level tests. Default to
  metadata reset for reuse; delegate to the existing erase selector only with
  explicit sanitization intent. Update SKILL.md and disk-preparation references.
- [x] Gate optional manager enablement in install/validation references with a
  version compatibility helper and tests; document the affected-version workaround.
- [x] Add explicit expected default policy and a target/UID-bound retained shared
  API inventory to `scripts/post_uninstall_audit.sh`, with positive and refusal
  tests in a separate audit-expectations test module. Keep the default audit strict.
- [x] Add a dependency-free S3 client and scoped OBC/pod orchestration helper.
  Test signing, actual byte comparison, watch-scope selection, ownership checks,
  and cleanup after failures. Retain the existing documented TLS trust checks.
- [x] Add bounded health observation with tests for health changes, crash records,
  malformed output, access failures, and interval/timeout validation.
- [x] Wire helpers into SKILL.md, references, and package validation; bump the
  skill version and changelog. Run targeted regressions, the full Rook suite,
  collection validation, isolated collection suites, package check, and identity
  scans. Review the final diff. Do not publish a PR unless requested.

The existing snapshot tests remain mandatory. NFS snapshot support remains Alpha;
no feature gates, backup schedules, or performance settings are changed.

Verification: all 14 isolated collection suites passed, including the Rook suite.
Collection validation, Rook package validation, diff checks, and identity scans passed.
Independent review blockers were fixed with failing-then-passing regressions.
The updated helpers were not rerun against a live cluster.

## ODF follow-up

- [x] Apply dependency-ordered CSI finalization to `openshift-odf/references/maintenance-uninstall.md`, retaining OLM and restoring temporarily stopped CSI reconciliation before finalization.
- [x] Apply intent planning, non-ODF-owned shared API protection, explicit audit expectations, scoped RGW/MCG testing, and read-only Ceph observation. Keep product-specific preflight and namespace policies; parity-test the shared signing and observation engines.
- [x] Document the manager regression as a vendor-build diagnostic. Do not copy upstream Rook CephCluster patches into ODF. Keep StorageCluster/OLM and SNO readiness requirements.
- [x] Validate both updated packages, run the collection suites, review, and scan identities before committing. No live cluster mutation is part of this follow-up.

ODF follow-up verification: all 14 collection suites passed. A fresh final ODF
run passed all 543 tests after ownership review fixes; both package validators
and collection validation passed. Independent review found no remaining blockers.
