# Changelog

## 1.1.0

- Added `references/java.md` — Java language reference guide for code simplification patterns.
- Added `references/sql.md` — SQL language reference guide for query simplification patterns.
- Updated `SKILL.md` with cross-links to the new Java and SQL reference guides.
- Expanded `README.md` with additional mode/output guidance.
- Updated validator expected-reference list to include the two new reference files.

## 1.0.1

- Added first-class PHP support to `code-simplifier`, including load guidance for
  `.php` files, Composer projects, and common ecosystems such as Laravel,
  Symfony, and WordPress.
- Added `references/php.md` and updated package documentation to advertise PHP
  alongside the existing supported languages.
- Updated validator expectations and regression tests so PHP reference support is
  treated as part of the package contract.

## 1.0.0

- Packaged `code-simplifier` as a first-class repo skill with metadata, validator,
  tests, and package documentation.
- Reworked `SKILL.md` into explicit operating modes, scope rules, verification
  guidance, and output contract.
- Standardized language references under `references/`.
