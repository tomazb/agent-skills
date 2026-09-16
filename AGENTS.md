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

## Sensitive Data
These skills are written from real cluster work, so evidence is valuable and identity is not. Record the behavior, the versions, and the symptom; never the address of the machine it happened on.

- **Never commit** resolvable FQDNs or hostnames, cluster API URLs (`https://api.<cluster>:6443`), routes and ingress domains, public IP addresses, email addresses, DNS zone names, bucket names, kubeconfig contents, tokens, keys, or certificates.
- **Use reserved placeholders** so examples stay obviously fake: `example.com`, `example.org`, or the `.example` / `.test` / `.invalid` TLDs (RFC 2606) for names, and `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` (RFC 5737) for addresses. Keep the structure that makes the example instructive — a nested-zone example still needs two labels (`ocp1.sno.example.com` vs `example.com`).
- **Prefer a role over a name.** `the cluster API endpoint`, `the target cluster`, `<target-context>` all carry the meaning without the identity. A short internal nickname is acceptable where traceability genuinely helps; a resolvable FQDN never is.
- **Redact pasted command output.** Live `oc whoami --show-server`, `oc config current-context`, `oc get route`, and node listings all print identifying values. Replace them with placeholders before pasting into a document, test fixture, journal, or commit message.
- **This applies to git and GitHub text too**, not just files: commit messages, PR titles and bodies, review replies, and issue comments. Those are the easiest to leak into and the most awkward to clean — a committed message needs `git commit --amend` plus a force-push, which needs the maintainer's explicit approval.
- **Journals and evidence notes are the usual leak.** When recording that something was verified on a real cluster, name the product versions (`ODF 4.22.3`, `OCP 4.22.12`) and the topology (`SNO`), not the cluster.

Scan before committing. Match URLs and `:6443` endpoints rather than bare dotted names — Kubernetes API groups (`cert-manager.io`, `rbd.csi.ceph.com`, `operators.coreos.com`) are dotted names too, and a scan that flags them produces enough noise that nobody runs it:

```bash
git grep -nIoE "https?://[a-zA-Z0-9._-]+|\b[a-z0-9-]+(\.[a-z0-9-]+){1,}:6443\b" -- . \
  | grep -vE "example\.|\.example|\.test\b|\.invalid\b|github\.com|githubusercontent\.com|redhat\.com|openshift\.(com|io)|kubernetes\.io|k8s\.io|quay\.io|ceph\.io|rook\.io|letsencrypt\.org|longhorn\.io|localhost|127\.0\.0\.1|cloudflare|jsdelivr|cdnjs|\.svc"
```

Expect a handful of hits from legitimate external citations; read them rather than assuming. Also check for routable IP literals:

```bash
git grep -nIoE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b" -- . \
  | grep -vE "127\.0\.0\.1|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|255\.|1\.1\.1\.1|8\.8\.8\.8"
```

Check the commit messages too — `git grep` only reads the tree:

```bash
git log --format='%B' <base>..HEAD \
  | grep -nE "https?://[a-zA-Z0-9._-]+|\b[a-z0-9-]+(\.[a-z0-9-]+){1,}:6443\b"
```

## Verification
- Run the relevant local tests for the skill you changed.
- Use `python3 scripts/validate_skill_collection.py` for a broader repository validation pass when a change affects multiple skills or packaging.
- Run the sensitive-data scan above over both the working tree and the commit messages before pushing or opening a PR.
