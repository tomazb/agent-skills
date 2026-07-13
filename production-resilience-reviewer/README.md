# Production Resilience Reviewer

## TLDR

A senior-level AI skill that reviews code, services, workflows, deployments, and system designs
for production resilience through **twelve failure lenses**. It identifies material,
evidence-backed failure modes and provides actionable fixes with calibrated priorities,
validation plans, and production verification.

---

## Overview

The **Production Resilience Reviewer** acts as a hybrid Staff SRE, Principal Engineer, and
Incident Commander. Its core philosophy: production resilience is not about preventing every
failure—it is about **controlling blast radius and recovery** when failures occur.

Every external call will eventually fail. Every dependency will eventually be slow. Every
assumption about data shape will eventually be violated. The question is not only "will this
fail?" but "when this fails, what happens to the user, the system, and the on-call engineer—and
how quickly can we recover?"

The reviewer distinguishes confirmed defects from assumptions and evidence gaps. A control that
is not visible in a pasted snippet is not automatically absent from the production system.

---

## Key Features

### Twelve Failure Lenses

1. **Dependency Failure** — What happens when external services are unavailable or return bad outcomes?
2. **Load & Concurrency** — What fails under expected peak, planned growth, and failure-amplified demand?
3. **Network & Latency** — Are remote operations bounded by propagated deadlines and appropriate phase limits?
4. **Data Freshness & Consistency** — What happens when data is stale, duplicated, reordered, or concurrently changed?
5. **Retry & Backpressure** — Are retries safe, classified, deadline-aware, and bounded across all layers?
6. **Debuggability** — Can an on-call engineer reconstruct the failure quickly and safely?
7. **Observability & Alerting** — Do signals show user impact, correctness, saturation, and actionable SLO burn?
8. **Change Management & Rollback Safety** — What happens during mixed-version rollout, migration, and rollback?
9. **Fault Domains & Disaster Recovery** — Can the workflow meet approved RPO/RTO under realistic recovery conditions?
10. **Security & Abuse as Reliability** — Can hostile traffic, auth failure, or a noisy tenant take down shared paths?
11. **Quota & Limit Exhaustion** — What happens when provider, resource, or cost budgets are exhausted?
12. **Complexity Tax & Architecture Fit** — Is the architecture reducing risk or adding unsupported failure surface?

### Evidence-Calibrated Severity

Findings are calibrated using **impact × likelihood × blast radius × detectability**, adjusted for:

- User and business impact
- Read-only versus mutating or irreversible behavior
- Money, authorization, compliance, and other sensitive data
- Frequency and traffic exposure
- Recoverability and reconciliation difficulty
- Existing controls and the strength of available evidence

Missing retries are not automatically a defect. Missing deadlines, error handling, or other
controls are reported as confirmed only when the reviewed evidence establishes their absence.

### Two Review Modes

- **Quick Mode** — A concise senior pass for snippets and small functions, focused on the top 3–5 risks.
- **Full Mode** — A deeper review for services, workflows, migrations, and designs, including fix sequencing, rollout gates, validation, and monitoring.

### AI-Generated Code Review

When the user identifies code as AI-generated, the skill applies heightened scrutiny to common
incomplete production boundaries: error and cancellation paths, implicit client defaults,
unbounded work, unsafe mutation retries, missing operational signals, and rollout assumptions.
It applies the same checks to all code and does **not** infer authorship from names, TODOs, or code smells.

---

## Review Output

High-priority findings include:

- **Finding** — The concrete production weakness
- **Evidence** — The code path, configuration, design fact, or explicit condition supporting it
- **Why it matters** — The causal failure chain and user/business impact
- **Recommendation** — The smallest effective and operable control
- **Validation** — A test or drill that recreates the failure and proves the fix
- **Monitoring** — Signals that detect regression and show production impact
- **Priority** — P0 through P3, calibrated to context

The reviewer states material assumptions and evidence gaps rather than converting missing context
into confirmed defects.

---

## Package Structure

```text
production-resilience-reviewer/
├── SKILL.md
├── README.md
├── package.json
├── VERSION
├── CHANGELOG.md
├── references/
│   ├── checklist-dependency.md
│   ├── checklist-data.md
│   ├── checklist-debuggability.md
│   ├── checklist-load-concurrency.md
│   ├── checklist-network-latency.md
│   ├── checklist-observability.md
│   ├── checklist-change-management.md
│   ├── checklist-disaster-recovery.md
│   ├── checklist-security-abuse-reliability.md
│   ├── checklist-quota-limit-exhaustion.md
│   ├── checklist-complexity-tax.md
│   ├── severity-calibration.md
│   └── validation-monitoring-patterns.md
├── tests/
└── tools/
    ├── bump_version.py
    ├── validate_skill_package.py
    └── validate_skill_package.sh
```

---

## Reference Materials

The `references/` directory provides focused deep dives:

- **Dependency and network** — Failure classification, end-to-end deadlines, phase limits, retries, circuits, and fallbacks
- **Load and data** — Queue bounds, pool saturation, fan-out, concurrency, caching, consistency, races, and migrations
- **Operability** — Error context, trace correlation, metrics, cardinality, SLOs, alerting, dashboards, and runbooks
- **Change and recovery** — Mixed versions, expand/contract, rollback, RPO/RTO, restore, replay, failover, and failback
- **Abuse and exhaustion** — Auth fail-open, tenant isolation, quotas, headroom, admission control, and cost protection
- **Architecture fit** — Evidence-first evaluation of service boundaries, orchestration, platform maturity, and complexity cost
- **Shared calibration** — Severity rules plus validation and monitoring patterns

Numeric timeouts, retry counts, pool thresholds, headroom targets, alert thresholds, and drill
cadences are treated as contextual decisions. Examples are starting points, not universal policy.

---

## Usage

AI coding agents should trigger this skill for:

- Production-readiness, resilience, or failure-mode reviews
- Error handling, remote deadlines, retries, backpressure, degradation, or observability analysis
- Deployment, migration, rollback, DR, abuse, quota, or cost-resilience review
- Architecture trade-offs that materially affect resilience, operability, cost, or failure amplification
- Extra resilience scrutiny when the user identifies code as AI-generated

Skip this skill for non-production artifacts, throwaway prototypes, and one-off scripts with no
SLA or meaningful user impact.

See `SKILL.md` for the complete agent instructions.

---

## Validation

From the repository root, install the development dependencies and run all checks:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_skill_collection.py
python3 production-resilience-reviewer/tools/validate_skill_package.py
pytest -q
```

From inside this package, the self-contained package validator can also run directly:

```bash
bash tools/validate_skill_package.sh
# or:
python3 tools/validate_skill_package.py
```

### Validation Contract

The package validator enforces:

- **Required files** — `VERSION`, `package.json`, `CHANGELOG.md`, `SKILL.md`, and `README.md`
- **Version synchronization** — `VERSION`, `package.json`, the current changelog heading, and the README current-version marker agree
- **SKILL.md structure** — All twelve lens headings exist with valid spacing and the configured line budget
- **Reference inventory** — Every expected deep-dive reference exists
- **Correctness guards** — Unsafe blanket retry, metric-label, hard-coded-threshold, SLO, and AI-provenance rules cannot silently return
- **Markdown hygiene** — Trailing newlines, balanced fences, and leaked-TOC checks

The repository-level validator uses the official `skills-ref` library for Agent Skills
frontmatter and naming validation.

---

## Version Management

Update all version surfaces with:

```bash
python3 tools/bump_version.py <new-version>
```

This updates `VERSION`, `package.json`, and the README current-version marker. Add the matching
`CHANGELOG.md` heading before validation.

---

## Version History

Current version: **5.5.1**

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

Recent highlights:

- **5.5.1** — Corrected retry/deadline, telemetry-cardinality, SLO, severity, AI-provenance, and numeric-default guidance; hardened validation and CI
- **5.5.0** — Added Lens 12, Complexity Tax & Architecture Fit
- **5.4.0** — Expanded AI-code review areas and added Lens 2/3/6 deep-dive references
- **5.3.0** — Refactored package validation and added regression tests
- **5.2.0** — Added disaster recovery, security/abuse, and quota-exhaustion lenses

---

## Example Review Output (Condensed)

```markdown
## Review Summary (Quick Mode)

**Verdict**: NEEDS-WORK
**Risk Level**: HIGH
**Material assumption**: The shared payment client has no additional idempotency or reconciliation layer.

### Top Findings

[P0-CRITICAL] Payment mutation is retried after an ambiguous post-send deadline without a
stable payment-operation idempotency key. A provider commit followed by caller timeout can lead
to a second charge. Bound the total operation, classify transient failures, preserve one
operation key across attempts, and reconcile unknown outcomes before resubmission.

[P1-HIGH] Three sequential database calls and an unbounded response create a credible pool-wait
and memory-growth path. Batch queries, cap result size, and align concurrency with measured
downstream capacity.

[P1-HIGH] Checkout has no good-event SLI or order-success guardrail. Define the user-visible good
outcome, add bounded RED/business signals, and route volume-aware burn alerts to an actionable runbook.

### Validation Before Shipping

- Inject a deadline after the provider commits; prove repeated attempts cannot create another charge.
- Test expected peak, planned growth, and dependency-slowdown demand; verify the approved latency objective and pool-wait headroom.
- Seed a checkout failure; verify trace continuity, dashboard impact, alert routing, and runbook action.

### Production Verification

- Ambiguous payment outcomes, deduplication hits, and reconciliation failures
- Pool wait, pool use, bounded result-size rejection, and request latency distributions
- Good checkout events / valid checkout events, order success, and dependency deadline classification
```

---

## Philosophy

> "The question is never 'will this fail?' but 'when this fails, what happens to the user, the system, and the on-call engineer—and how quickly can we recover?'"

The skill embodies the mindset of a senior engineer who has been paged at 3 AM and knows that
resilience comes from bounded blast radius, observable recovery, and controls the operating team
can safely use during an incident.
