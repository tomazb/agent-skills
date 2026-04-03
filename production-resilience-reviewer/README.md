# Production Resilience Reviewer

## TLDR

A senior-level AI skill that reviews code, services, and system designs for production resilience through **eleven failure lenses** (dependency, load, network, data, retry, debuggability, observability, change management, disaster recovery, security-abuse reliability, quota exhaustion). It finds every way your code can fail in production and provides actionable fixes with priority rankings—especially valuable for catching AI-generated code blind spots.

---

## Overview

The **Production Resilience Reviewer** acts as a hybrid Staff SRE, Principal Engineer, and Incident Commander. Its core philosophy: production resilience isn't about preventing all failures—it's about **controlling the blast radius** when failures inevitably happen.

Every external call will eventually fail. Every dependency will eventually be slow. Every assumption about data shape will eventually be violated. The question is never "will this fail?" but "when this fails, what happens to the user, the system, and the on-call engineer—and how quickly can we recover?"

This skill systematically analyzes code to answer that question across eleven critical failure domains.

---

## Key Features

### Eleven Failure Lenses

The skill applies a comprehensive framework to every review:

1. **Dependency Failure** - What happens when external services are down?
2. **Load & Concurrency** - What happens at 1,000× traffic?
3. **Network & Latency** - What happens when the network is slow?
4. **Data Freshness & Consistency** - What happens when data is stale?
5. **Retry & Backpressure** - What happens when systems retry aggressively?
6. **Debuggability** - What error messages help at 3 AM?
7. **Observability & Alerting** - What metrics show health in production?
8. **Change Management & Rollback Safety** - What happens during deployments?
9. **Fault Domains & Disaster Recovery** - What happens if an AZ/region/control plane fails?
10. **Security & Abuse as Reliability** - What happens under hostile traffic and auth failures?
11. **Quota & Limit Exhaustion** - What happens when quotas, pools, or budgets run out?

### Severity Calibration

Findings are calibrated using **impact × likelihood × blast radius × detectability**, with context-aware adjustments for:
- User impact (internal vs customer-facing)
- Operation type (read-only vs mutating)
- Data sensitivity (metadata vs money/auth)
- Blast radius (single user vs system-wide)
- Frequency (rare vs hot path)

### Two Review Modes

- **Quick Mode** - Fast senior-level pass for snippets/functions; focuses on top 3-5 risks
- **Full Mode** - Deep production-readiness review for services/handlers; includes validation and monitoring plans

### AI-Generated Code Detection

Specialized awareness of common AI code blind spots:
- Happy-path bias (missing error handling)
- Placeholder try/catch blocks
- Missing timeouts
- Hardcoded configuration
- Unbounded operations
- Missing idempotency
- Zero observability
- Unsafe rollout assumptions

---

## Review Output

Each finding includes:
- **Evidence** - Specific code path or behavior
- **Why it matters** - User impact, blast radius, incident risk
- **Recommendation** - Concrete fix with implementation guidance
- **Validation** - Tests/simulations to prove the fix works
- **Monitoring** - Metrics/alerts/dashboards for production visibility
- **Priority** - P0 (critical) through P3 (low)

---

## Package Structure

```
production-resilience-reviewer/
├── SKILL.md                # Core skill definition and instructions
├── README.md               # This file
├── package.json            # Package metadata
├── VERSION                 # Current version
├── CHANGELOG.md            # Version history
├── references/             # Deep-dive reference materials
│   ├── checklist-dependency.md
│   ├── checklist-data.md
│   ├── checklist-observability.md
│   ├── checklist-change-management.md
│   ├── checklist-disaster-recovery.md
│   ├── checklist-security-abuse-reliability.md
│   ├── checklist-quota-limit-exhaustion.md
│   ├── severity-calibration.md
│   └── validation-monitoring-patterns.md
└── tools/                  # Validation and utilities
    ├── bump_version.py
    ├── validate_skill_package.py
    └── validate_skill_package.sh
```

---

## Reference Materials

The `references/` directory contains deep-dive checklists and patterns:

- **`checklist-dependency.md`** - Extended dependency failure patterns and mitigations
- **`checklist-data.md`** - Data consistency, caching, and freshness patterns
- **`checklist-observability.md`** - Metrics, logging, alerting, and dashboarding patterns
- **`checklist-change-management.md`** - Rollout, migration, and rollback safety (Lens 8 deep-dive)
- **`checklist-disaster-recovery.md`** - Fault domains, RPO/RTO, backup/restore, failover, and replay safety (Lens 9 deep-dive)
- **`checklist-security-abuse-reliability.md`** - Auth fail-open, abuse resistance, and secure degradation (Lens 10 deep-dive)
- **`checklist-quota-limit-exhaustion.md`** - Quota/resource exhaustion and cost/rate guardrails (Lens 11 deep-dive)
- **`severity-calibration.md`** - Full severity/context matrix and adjustment rules
- **`validation-monitoring-patterns.md`** - Validation and monitoring patterns by failure type

These references are consulted when deeper analysis is needed for specific failure domains.

---

## Usage

AI coding agents should trigger this skill when users request:
- Production-readiness, resilience, or failure-mode review of code/services/designs
- Reliability analysis for error handling, retries, timeouts, circuit breakers, graceful degradation, or observability
- Operational risk review around deploy/rollback safety, DR (RPO/RTO), abuse resilience, or quota exhaustion
- Extra scrutiny of AI-generated code for common resilience blind spots

Skip this skill for:
- Non-production artifacts
- Throwaway prototypes
- One-off scripts with no SLA or user impact

See `SKILL.md` for complete agent instructions and the full review framework.

---

## Validation

Run the validation tool to check package integrity:

```bash
bash tools/validate_skill_package.sh
# or:
python3 tools/validate_skill_package.py
```

Run validator regression tests:

```bash
pytest -q
```

### Validation Contract

The package validator enforces these rules:

- **Required files**: VERSION, package.json, CHANGELOG.md, SKILL.md, README.md — missing any raises an explicit error.
- **VERSION ↔ package.json sync**: The `version` field in `package.json` must exactly match the content of `VERSION`.
- **VERSION ↔ CHANGELOG.md heading**: `CHANGELOG.md` must contain a `## {version}` or `## v{version}` heading matching the current `VERSION`.
- **SKILL.md structure**: Must contain all eleven Lens headings with proper spacing; line count must stay under the configured limit.
- **Reference files**: All expected reference files in `references/` must exist.
- **Markdown hygiene**: Every `.md` file must end with a newline, have balanced code fences, and no leaked TOC titles.

---

## Version Management

Update all version surfaces in one command:

```bash
python3 tools/bump_version.py <new-version>
```

This updates:
- `VERSION`
- `package.json`
- `README.md` "Current version" line

---

## Version History

Current version: **5.3.2**

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

Recent highlights:
- **5.3.1** - Aligned lens example style (Risk/Recommendation), refined trigger guidance, consolidated severity calibration
- **5.3.0** - Validator refactor with regression tests, version bump tooling, expanded Lenses 9-11 guidance
- **5.2.0** - Added Lenses 9-11 (Disaster Recovery, Security/Abuse Reliability, Quota Exhaustion) and deep-dive references
- **5.1.0** - Added condensed examples across all lenses; enhanced validation
- **5.0.0** - Restored Load & Concurrency as first-class lens
- **4.0.0** - Added Change Management lens and reference materials
- **3.x** - Introduced Lens 8 and severity calibration framework

---

## Example Review Output (Condensed)

```
## Review Summary (Quick Mode)

**Verdict**: NEEDS-WORK
**Risk Level**: HIGH
**Context Assumptions**: User-facing API endpoint, moderate traffic

### Top Findings
[P0-CRITICAL] POST /payments → Stripe: missing timeouts + retry without 
idempotency key → double-charge risk. Add connect=3s/read=10s timeouts; 
use idempotency key; bounded retries with exponential backoff+jitter.

[P1-HIGH] getUserProfile() hot path: 3 sequential DB queries → pool 
saturation at scale. Batch queries; tune pool limits; cache stable data.

[P1-HIGH] Missing RED metrics on checkout endpoint. Add request rate,
error rate, duration histogram; emit order_success_total counter.

### Validation Before Shipping
- Simulate Stripe timeout/429/500; prove no duplicate charges
- Load test at 5× traffic; verify pool saturation <80%
- Synthetic error → verify alert fires

### Monitoring After Deploy
- payment_failures_total{reason}, reconciliation_queue_depth
- db_pool_in_use, request_latency_p95
- checkout_request_duration_seconds, order_success_total
```

---

## Philosophy

> "The question is never 'will this fail?' but 'when this fails, what happens to the user, the system, and the on-call engineer—and how quickly can we recover?'"

This skill embodies the mindset of a senior engineer who has been paged at 3 AM and knows that production resilience comes from controlling blast radius, not preventing all failures.
