# Skill Authoring RED Baseline

## Purpose

Freeze the observed pre-skill behavior this package must correct.

## Set A — behavior change without adjacent tests

Scenarios:

- editing a skill's safety rules without touching its tests
- adding a helper script without contract coverage

Observed pattern:

- the change looked complete in the diff
- validation passed but the new behavior had no regression guard
- the next edit re-broke the same rule silently

## Set B — version drift across four files

Scenarios:

- bumping `package.json` without updating `VERSION`
- adding a `CHANGELOG.md` entry under the wrong heading
- forgetting the per-skill README `Current version` line

Observed pattern:

- each file looked right in isolation
- the package reported two different versions depending on where you asked
- release tooling picked up a stale version

## Set C — index drift (critical)

Phrases seen in review:

- `docs updated separately`
- `README follows in another PR`

Scenarios:

1. adding a skill directory without listing it in root `README.md` and
   `AGENTS.md`
2. renaming a skill while the old name still appears in the indexes

Observed pattern:

- the skill worked but was undiscoverable from the collection indexes
- new agents planned against a stale inventory

## Design implications

The package should:

- require the skill document, adjacent tests, and version files together
- enforce `VERSION`, `package.json`, `CHANGELOG.md`, and README sync
- name the collection validator, the isolated test runner, and both
  repo indexes in the skill guidance
