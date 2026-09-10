---
name: skill-authoring
description: Use when creating a new skill in this collection, or modifying an existing skill's SKILL.md, package layout, version, changelog, tests, or validation tooling.
---

# Skill Authoring

Meta-skill for working inside this agent-skills collection. Each skill is a
self-contained top-level directory. Keep the collection validator green and
keep the skill document, its adjacent tests, and the repo indexes in sync.

## When to use

Use this skill when the request involves:

- creating a new skill directory in this collection,
- changing a skill's behavior, instructions, or safety rules,
- adding or changing a skill's scripts, tools, references, or assets,
- bumping a skill version or writing a changelog entry,
- fixing collection validation or per-skill test failures.

Do not use this skill as the primary driver for domain work that happens to
live inside a skill (for example cluster troubleshooting). Use the domain
skill for that; use this skill for the packaging around it.

## Package layout

Required files in every skill directory:

- `SKILL.md` — skill definition (frontmatter + instructions)
- `package.json` — name, version, description, keywords
- `VERSION` — current version, in sync with `package.json`
- `CHANGELOG.md` — version history with a heading per release
- `README.md` — per-skill readme with exactly one
  `Current version: **<version>**` line

Optional directories (create only when needed):

- `references/` — deep-dive reference materials (must contain markdown)
- `tools/` — validation and utility scripts
- `scripts/` — runtime helper scripts shipped with the skill
- `assets/` — static assets
- `tests/` — adjacent validation and contract tests

## Frontmatter rules

- The `description` must start with `Use when` and describe triggering
  conditions, not a workflow summary.
- Do not use the legacy frontmatter field `tools`. Use the Agent Skills
  `allowed-tools` field only when a tool restriction is genuinely needed,
  and document why the restriction exists.
- Keep `SKILL.md` instructions concise. Move heavy operational detail into
  `references/`, `scripts/`, or `tools/`, and point at those files.

## Versioning and changelog

- `VERSION` and the `package.json` version must match exactly and must be
  valid semantic versions.
- `CHANGELOG.md` must contain a `## <version>` heading for the current
  `VERSION`.
- The per-skill `README.md` version line must match `VERSION`.
- Bump with `python3 <skill>/tools/bump_version.py <new-version>`, then add
  the matching `CHANGELOG.md` heading before running validation.

## Validation

Run these from the repository root, in order:

```bash
python3 scripts/validate_skill_collection.py
python3 scripts/run_test_suite.py
```

The collection validator is scripts/validate_skill_collection.py and the
isolated test runner is scripts/run_test_suite.py. Then run the touched
skill's own package check:

```bash
bash <skill>/tools/validate_skill_package.sh
```

When adding, renaming, or removing a skill, update the root `README.md`
Available Skills section and the `AGENTS.md` Skill Inventory together so
the indexes never drift from the directories on disk.
