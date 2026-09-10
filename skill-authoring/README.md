# Skill Authoring

## TLDR

A self-contained meta-skill package for creating and maintaining skills in
this collection with in-sync packaging, versioning, and validation.

## What this package changes

It is built to correct two baseline failures:

- adding or changing a skill without updating the adjacent tests and the
  repo indexes (`README.md` and `AGENTS.md`) alongside it
- bumping versions in one place while `VERSION`, `package.json`,
  `CHANGELOG.md`, and the per-skill README drift apart

The skill stays concise and repo-native:

- required vs optional package layout
- `Use when...` frontmatter without the legacy `tools` field
- semantic version sync across four files
- collection validator, isolated test runner, and per-skill package check

The frozen RED baseline is recorded in `tests/test_skill_baseline.md`.

## Validation

Run these commands from the repository root:

```bash
bash skill-authoring/tools/validate_skill_package.sh
# or
python3 skill-authoring/tools/validate_skill_package.py
```

Run local regression tests:

```bash
pytest -q skill-authoring/tests
```

## Version Management

```bash
python3 skill-authoring/tools/bump_version.py <new-version>
```

This updates `VERSION`, `package.json`, and the README version line.
Add the matching `## <version>` heading to `CHANGELOG.md` before running validation.

Current version: **0.1.0**
