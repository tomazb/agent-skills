# Challenging Decisions

## TLDR

A self-contained skill package for pressure-testing plausible product or
architecture decisions before giving reassurance.

## What this package changes

It is built to correct two baseline failures:

- challenging weak decisions through only one practical lens
- agreeing first on good-looking decisions instead of pressure-testing them

The skill stays concise and repo-native:

- named lenses instead of personas
- challenge before agreement
- strongest counterarguments first
- a forcing question at the end
- explicit follow-up guidance after the user responds

The frozen RED baseline is recorded in `tests/test_skill_baseline.md`.

## Lenses

- Evidence
- Scope
- Timing
- Complexity
- Reversibility
- Opportunity Cost

## Validation

Run these commands from the repository root:

```bash
bash challenging-decisions/tools/validate_skill_package.sh
# or
python3 challenging-decisions/tools/validate_skill_package.py
```

Run local regression tests:

```bash
pytest -q challenging-decisions/tests
```

## Version Management

```bash
python3 challenging-decisions/tools/bump_version.py <new-version>
```

This updates `VERSION`, `package.json`, and the README version line.
Add the matching `## <version>` heading to `CHANGELOG.md` before running validation.

Current version: **1.0.0**
