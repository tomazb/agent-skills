# OpenShift Versions

Current version: **1.0.0**

## TLDR

A version-agnostic OpenShift release discovery skill that answers version, patch,
and upgrade-path questions using `scripts/query_versions.py` against Red Hat's
public and authenticated APIs.

---

## When To Use

- Discover which OpenShift minors are currently active.
- Find the latest patch in one or more channels.
- Check valid one-hop upgrades from a running version.
- Confirm ROSA/HCP eligibility and lifecycle metadata with authenticated queries.
- Answer support/readiness questions like "what OCP versions exist right now?"

---

## When To Skip

- Cluster health diagnosis, degraded operator triage, or incident troubleshooting.
- Executing upgrades or making cluster configuration changes.
- Questions unrelated to OpenShift release/version availability.

---

## Version-Agnostic Workflow (Mandatory)

**Always discover first. Never hardcode versions.**

1. Run `--discover` or `--all-latest` first to detect active minors.
2. Use discovered minors for `--channel` and `--upgrade-path` follow-up queries.
3. Keep examples placeholder-based (`{MAJOR}.{MINOR}`) until discovery confirms
   what is currently published.

---

## Quick Start Examples

Executable entry point: `scripts/query_versions.py`

```bash
python3 scripts/query_versions.py --discover
python3 scripts/query_versions.py --all-latest
python3 scripts/query_versions.py --upgrade-path 4.15.10
python3 scripts/query_versions.py --channel stable-4.18 --latest
python3 scripts/query_versions.py --token "$OCM_TOKEN" --enabled --rosa-enabled
```

## Script Modes

- `--discover`: Probes channels and lists active minor versions for the selected
  channel type and architecture.
- `--all-latest`: Returns the latest patch for every discovered active minor.
- `--upgrade-path`: Resolves valid one-hop upgrade targets from a supplied
  version.
- `--channel`: Queries a specific channel and lists versions (or latest when
  paired with `--latest`).
- `--token`: Uses the authenticated endpoint for lifecycle metadata, ROSA/HCP
  flags, and filtered inventories.

---

## Troubleshooting Quick Reference

- **Token expiry (`401`)**: Generate a fresh token from
  `https://console.redhat.com/openshift/token` and retry.
- **Rate limiting (`429`)**: Retry after delay; tune `--retry-count` and
  `--retry-base-delay` for automation.
- **No versions found**: Run `--discover` first, verify channel format, and
  confirm the selected architecture has published payloads.

---

## Package Structure

```text
openshift-versions/
├── SKILL.md
├── README.md
├── package.json
├── VERSION
├── CHANGELOG.md
├── scripts/
│   └── query_versions.py
├── references/
│   └── api_reference.md
├── tools/
│   ├── validate_skill_package.py
│   ├── validate_skill_package.sh
│   └── bump_version.py
└── tests/
    └── test_query_versions.py
```

---

## Validation Commands

Requires Python 3.9+.

```bash
npm run validate
npm test
# or:
python3 tools/validate_skill_package.py
pytest -q
```

---

## References

- Executable entry point: `scripts/query_versions.py`
- API schema and endpoint details: `references/api_reference.md`
- Full behavior and decision workflow: `SKILL.md`
