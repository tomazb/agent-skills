# Changelog

## 1.1.0

- Created `README.md` with package overview, usage guidance, and version discovery workflow documentation.
- Added E2E CLI tests: `--all-latest`, `--upgrade-path` with multi-channel, authenticated vs unauthenticated path selection, and JSON decode error handling.
- Added `tests/conftest.py` with validator and package_factory fixtures.
- Added `tests/test_validator_structure.py` with tests for VERSION/package.json sync, CHANGELOG heading, and required files.

## 1.0.0
- Added initial package metadata, version tracking, and local validation tooling.
- Documented the OpenShift version discovery and upgrade-path workflow.
- Added bounded retry behavior for transient `429`, `5xx`, and URL connection errors.
- Added targeted unit tests for version parsing, discovery behavior, argument validation, retry handling, and authenticated request assembly.
