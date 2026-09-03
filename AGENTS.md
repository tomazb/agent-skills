# AGENTS.md
## Repository Scope
This repository stores reusable agent skills. Each skill should live in its own directory with a `SKILL.md` file and any supporting scripts or tests nearby.

## Skill Inventory

### OpenShift storage
- `openshift-rook` — Use when planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, or troubleshooting Rook Ceph on OpenShift/OKD for SNO or multi-node clusters, including CDI/KubeVirt VM storage defaults and StorageProfile configuration.
- `openshift-odf` — Use when planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, or troubleshooting OpenShift Data Foundation (ODF) on OpenShift/OKD for SNO or multi-node clusters.
- `openshift-longhorn` — Use when discovering, planning, installing, validating, hardening, upgrading, migrating, backing up, restoring, maintaining, uninstalling, or troubleshooting Longhorn on OpenShift/OKD.
- `openshift-lvm-storage` — Use when planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, or troubleshooting LVM Storage (LVMS) on OpenShift/OKD for SNO or multi-node clusters.

### OpenShift platform
- `openshift-cert-manager` — Use when installing, configuring, validating, renewing, replacing OpenShift default ingress or API certificates, or troubleshooting cert-manager / Let's Encrypt / ACME HTTP-01 or DNS-01 on OpenShift/OKD.
- `openshift-cluster-health-check` — Use when assessing OpenShift cluster health, explaining degraded status, troubleshooting control-plane issues, or producing a health report.
- `openshift-versions` — Use when asking about available OpenShift versions, latest patches, upgrade paths, ROSA/OSD versions, channels, or end-of-life dates.

### Quality and review
- `qa-agent` — Use when the request involves quality review, risk-based test planning, bug reproduction, regression analysis, API/contract verification, or exploratory testing strategy.
- `production-resilience-reviewer` — Use when reviewing production readiness, resilience, failure modes, or reliability of code, services, or system designs.
- `code-simplifier` — Use when asked to simplify, clean up, refactor, tidy, reduce complexity, improve readability, or review code quality while preserving behavior.
- `pr-comments` — Use when displaying GitHub PR review comments in the code review UI, or inspecting review feedback on the current branch before responding.

### Communication and decisions
- `challenging-decisions` — Use when a decision sounds reasonable but still needs pressure-testing before agreement, especially for scope, architecture, sequencing, or irreversible trade-offs.
- `how-to-speak-winston-framework` — Use when crafting, auditing, or coaching presentations, slide decks, pitches, talk structure, or memorable teaching props and stories.

### Repository maintenance
- `skill-authoring` — Use when creating a new skill in this collection, or modifying an existing skill's SKILL.md, package layout, version, changelog, tests, or validation tooling.

## Skill Authoring Conventions
- Write skill descriptions in `Use when...` form so they describe triggering conditions, not workflow summaries.
- Do not use the legacy frontmatter field `tools`; `allowed-tools` is opt-in — use it only when a tool restriction is genuinely needed, and state the reason in the skill (see `qa-agent`).
- Keep skill instructions concise and move heavy operational detail into scripts or tests when possible.
- When changing a skill's behavior, update the skill document and its adjacent validation/tests together.

## Python Script Conventions
- Prefer Python 3.9+ compatible code.
- Add focused unit tests for command-level behavior when changing helper scripts that call external CLIs.

## Verification
- Run the relevant local tests for the skill you changed.
- Use `python3 scripts/validate_skill_collection.py` for a broader repository validation pass when a change affects multiple skills or packaging.
