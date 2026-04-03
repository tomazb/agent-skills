# Code Simplifier

## TLDR

A language-agnostic skill for simplifying code without changing behavior. It focuses
on readability, local consistency, and maintainability, with language-specific
references for TypeScript/JavaScript, PHP, Python, Go, Rust, and shell scripting.

---

## Overview

The **Code Simplifier** exists for the common case where code works but is harder to
read than it needs to be. Its job is not to invent abstractions or chase stylistic
purity. Its job is to reduce cognitive load while respecting the conventions that
already exist in the codebase.

The skill supports two working modes:

- **Review-Only Mode** for critique, rewrite suggestions, and risk-aware guidance
- **Apply-Changes Mode** for direct workspace edits with validation

This separation keeps the skill useful both for pasted snippets and for real
repository cleanup work.

---

## Operating Modes

### Review-Only Mode

Use this mode when the user wants critique, options, or simplification guidance
without direct file edits. This is usually the right default for pasted snippets,
design discussion, and risk-first analysis.

### Apply-Changes Mode

Use this mode when the user explicitly asks for workspace edits. Keep diffs small,
preserve behavior, and run the best available validation commands after changes.

### Choosing Between Modes

If intent is ambiguous, start in Review-Only Mode and provide a concrete rewrite
proposal. Switch to Apply-Changes Mode only after explicit approval to edit files.

---

## Key Features

- Preserves behavior by default and treats functional changes as out of scope unless
  explicitly requested
- Prioritizes high-value readability wins such as reducing nesting, removing dead
  code, clarifying naming, and collapsing needless indirection
- Loads language-specific references from `references/` for TypeScript/JavaScript,
  PHP, Python, Go, Rust, and shell
- Distinguishes review-only work from direct code edits so the agent can choose the
  right interaction style
- Requires explicit validation status in the final output, even when no tests could
  be run

---

## When To Use

Use this skill when the user asks for:

- code simplification
- cleanup or readability improvement
- refactoring without behavior change
- review of messy or overly complex code
- targeted cleanup before a PR

---

## When To Skip

Skip this skill when the primary task is:

- adding a new feature
- fixing a behavioral bug
- performance tuning on a hot path where current structure may be intentional
- a simplification where behavior-preservation confidence is low
- broad architectural redesign
- unrelated cleanup that breaks scope discipline by expanding beyond requested code

See `SKILL.md` for the full operating contract.

---

## Example Simplification Summary Output

Simplified the target function by flattening nested conditionals and removing a
duplicated fallback branch. Behavior is preserved: input handling, error paths, and
logging side effects are unchanged.

- Replaced two nested `if` blocks with guard clauses for earlier exits.
- Removed an unused temporary variable and inlined a one-use alias.
- Left one branch untouched because it is part of a known hot path.

---

## References

Language-specific guidance lives in:

- `references/typescript.md`
- `references/php.md`
- `references/python.md`
- `references/go.md`
- `references/rust.md`
- `references/shell.md`

Each reference focuses on common simplification patterns, anti-patterns, and
language-specific traps to avoid.

---

## Validation

Run the package validator:

```bash
bash tools/validate_skill_package.sh
# or:
python3 tools/validate_skill_package.py
```

Run validator regression tests:

```bash
pytest -q
```

The validator checks:

- required package files
- required references
- version synchronization
- changelog coverage for the current version
- required `SKILL.md` sections
- markdown fence and trailing-newline sanity

---

## Version Management

Update version surfaces in one command:

```bash
python3 tools/bump_version.py <new-version>
```

This updates:

- `VERSION`
- `package.json`
- `README.md` current-version line

---

## Version History

Current version: **1.0.1**

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.
