# OpenShift Cluster Health Check

Current version: **1.0.0**

## TLDR

A read-only, platform-aware diagnostic skill for assessing OpenShift cluster health across 17 phases. It classifies every finding as **Healthy**, **Warning**, or **Critical**, distinguishes platform failures from application issues, and produces a structured findings table with prioritised next actions.

---

## When to Use

- Cluster health assessment or degraded-operator triage.
- Pre-maintenance or post-maintenance validation.
- Upgrade readiness or post-upgrade sanity checks.
- Control-plane, node, MCP, ingress, monitoring, etcd, auth, storage, networking, or certificate health review.
- Bare-metal-specific diagnostics (BMH, Ironic, provisioning).
- Platform-specific diagnostics (vSphere, AWS, Azure, GCP).
- CrashLoopBackOff, Pending pods, OOMKilled, or scheduling failures anywhere in the cluster.

---

## Key Features

- **17-phase workflow** (Phase 0–16): platform detection → cluster operators → nodes → MCPs → etcd → auth → ingress → DNS → networking → storage → monitoring → registry → console → certificates → platform-specific → pod health → cluster-wide events.
- **Platform-aware**: bare metal (IPI/UPI, Metal3/Ironic), vSphere, AWS, Azure, GCP, and SNO.
- **Health classification**: Healthy / Warning / Critical with consistent reasoning rules.
- **Pod classification**: distinguishes quota-blocked vs platform-blocked pending pods; platform vs application CrashLoopBackOff.
- **Safety-first**: read-only by default; no drain, patch, delete, or restart unless explicitly instructed.
- **Deep-dive references**: verbose diagnostics are in `references/` so `SKILL.md` stays scannable.

---

## Condensed Output Format

Use this six-section response structure for every health-check report:

1. **Status** — overall `Healthy`, `Warning`, or `Critical`.
2. **Summary** — 2-4 sentences describing the dominant risk and blast radius.
3. **Platform context** — one line with platform/topology assumptions.
4. **Findings table** — subsystem-by-subsystem evidence with impact and next check.
5. **Priority actions** — up to 5 next actions ordered by urgency.
6. **Uncertainty** — explicit constraints, missing access, or confidence limits.

Findings table format:

| Area | Status | Evidence | Impact | Next check |
|---|---|---|---|---|
| etcd | Critical | `etcd` operator `Degraded=True`; one member missing from quorum | API availability and control-plane writes are at risk | Run endpoint health/member checks and confirm leader stability |

See `references/output-contract.md` for the full output specification and response style.

---

## Package Structure

```
openshift-cluster-health-check/
├── SKILL.md                          # Orchestration workflow (17 phases)
├── README.md                         # This file
├── package.json                      # Package metadata
├── VERSION                           # Semantic version
├── CHANGELOG.md                      # Release history
├── references/
│   ├── checklist-etcd.md             # etcd member/endpoint diagnostics
│   ├── checklist-authentication.md   # OAuth server and IdP diagnostics
│   ├── checklist-networking.md       # OVN-K and SDN deep-dive checks
│   ├── checklist-storage.md          # PV/PVC triage and CSI driver checks
│   ├── checklist-platform-specific.md # Bare metal, vSphere, AWS, Azure, GCP
│   ├── checklist-pods-analysis.md    # Pending/crash classification and matrix
│   ├── severity-calibration.md       # Health tier definitions and modifiers
│   └── output-contract.md            # Output format and response style
├── tools/
│   ├── validate_skill_package.py     # Skill package validator
│   ├── validate_skill_package.sh     # Shell wrapper for CI
│   └── bump_version.py               # Version synchronisation tool
└── tests/
    ├── conftest.py
    ├── test_validator_markdown_checks.py
    ├── test_validator_versions.py
    └── test_validator_skill_constraints.py
```

---

## Validation and Testing

```bash
# Validate package structure and content
npm run validate

# Run test suite
npm test

# Bump to a new version (updates VERSION, package.json, README)
python3 tools/bump_version.py 1.1.0
```

---

## Validation Contract

The package validator (`tools/validate_skill_package.py`) enforces these rules:

- **Required files**: VERSION, package.json, CHANGELOG.md, SKILL.md, README.md — missing any raises an explicit error.
- **VERSION ↔ package.json sync**: The `version` field in `package.json` must exactly match the content of `VERSION`.
- **VERSION ↔ CHANGELOG.md heading**: `CHANGELOG.md` must contain a `## {version}` or `## v{version}` heading matching the current `VERSION`.
- **SKILL.md structure**: Must contain Phase 0–16 headings; line count must stay under the configured limit.
- **Reference files**: All expected reference files in `references/` must exist.
- **Markdown hygiene**: Every `.md` file must end with a newline and have balanced code fences.
