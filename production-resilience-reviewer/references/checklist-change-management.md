# Change Management, Rollouts & Rollback Safety Patterns (Lens 8 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-dependency.md` — dependency-specific change risks (SDKs, certs, endpoints)
> - `references/checklist-data.md` — data/migration-specific change risks

## Table of Contents
1. Deployment Compatibility (Mixed Versions)
2. Contract Changes (APIs, Events, Schemas)
3. Schema & Data Migrations (Expand/Contract)
4. Feature Flags, Kill Switches, and Config Safety
5. Rollout Strategies & Guardrails
6. Rollback Playbooks & Reconciliation
7. Validation & Monitoring Add-Ons
8. Finding Snippet Templates

---

## 1. Deployment Compatibility (Mixed Versions)

Assume a real rollout will run **multiple versions at once** (multiple pods, regions, workers, clients).

### Mixed-Version Checklist
- [ ] New code tolerates old data and old responses
- [ ] Old code tolerates new data and new responses (or rollout prevents old code from seeing it)
- [ ] Changes are backward/forward compatible across:
  - request/response payloads
  - event/message formats
  - database schema and stored data formats
  - caches (key format changes, serialization format changes)
- [ ] No lockstep deployment requirement unless explicitly planned and risk-accepted
- [ ] Partial rollout failure is safe (some nodes updated, some not)

### Common Mixed-Version Failure Modes
- New writer + old reader: old code crashes or misbehaves on new fields/enum values
- Old writer + new reader: new code assumes a field is present or a state exists
- Config skew: new version depends on config that is not yet deployed everywhere
- Cache format change: old nodes read new cached values and fail deserialization

---

## 2. Contract Changes (APIs, Events, Schemas)

Contract changes are a top cause of cascading incidents.

### API Contract Checklist
- [ ] Additive first: adding optional fields is safe; removing/renaming fields is not (without a compatibility window)
- [ ] Unknown fields are ignored (forward-compat)
- [ ] Missing optional fields are tolerated (backward-compat)
- [ ] Enum parsing handles unknown values safely (does not crash; does not default-allow for auth/permissions)
- [ ] Version negotiation strategy exists if using versioned APIs
- [ ] Clear deprecation window and rollout plan for breaking changes

### Event / Queue / Stream Contract Checklist
- [ ] Message schema evolution strategy is documented (schema registry or version fields)
- [ ] Consumers are tolerant: skip/park unknown events rather than crashing the entire consumer
- [ ] DLQ strategy exists for unknown/invalid messages during rollout
- [ ] Ordering and idempotency assumptions are explicit (at-least-once delivery means duplicates)
- [ ] Replay safety: new consumers can handle historical messages

---

## 3. Schema & Data Migrations (Expand/Contract)

Prefer **expand/contract** for production safety: additive changes first, destructive changes later.

### Expand/Contract Pattern
1. **Expand**: add new nullable columns/tables/fields (no breaking reads)
2. **Dual-write** (if needed): write old + new formats
3. **Backfill**: idempotent, resumable, observable, rate-limited
4. **Dual-read**: read new, fall back to old; optionally emit compare metrics
5. **Cutover**: flip reads/writes behind a feature flag
6. **Contract**: remove old fields only after stability window and cleanup

### Migration Checklist
- [ ] Migration is idempotent and resumable (safe to re-run)
- [ ] Backfill is rate-limited and can be paused/stopped
- [ ] Long-running migrations are observable (progress metric, error metric, ETA optional)
- [ ] Rollback plan exists **after** new-format data has been written
- [ ] Mixed-version test is performed (old app + new schema, new app + old schema where applicable)
- [ ] Destructive steps are deferred and separately deployed

### Anti-Patterns
- Shipping app + irreversible migration together with no rollback plan
- Backfill that locks tables or saturates DB without throttling
- Migration that changes semantics silently (e.g., new default values) without audits/metrics

---

## 4. Feature Flags, Kill Switches, and Config Safety

### Feature Flag / Kill Switch Checklist
- [ ] Risky behavior changes are gated behind a feature flag
- [ ] Kill switch is fast to operate (runtime toggle, not redeploy)
- [ ] Flag default state is safe (fails closed for auth/permissions; fails safe for user impact)
- [ ] Flag evaluation is reliable (avoid making flag service a critical dependency without fallback)
- [ ] Rollout plan includes staged ramp and clear stop/rollback thresholds

### Config Safety Checklist
- [ ] Config is validated at startup (fail fast with actionable error)
- [ ] Config changes are tracked/audited (who changed what, when)
- [ ] Safe defaults exist (timeouts, pool sizes, retry limits)
- [ ] Secret rotation supports overlap windows (old + new valid during rotation)

---

## 5. Rollout Strategies & Guardrails

### Rollout Options (in increasing risk)
- [ ] Dark launch (deploy but off)
- [ ] Canary (small %)
- [ ] Progressive ramp (5% → 25% → 50% → 100%)
- [ ] One region/zone first
- [ ] Full rollout (avoid for risky changes)

### Guardrails Checklist
- [ ] Rollout has explicit success metrics (technical + business)
- [ ] Rollout has rollback thresholds (error rate, latency, business KPI regressions)
- [ ] Deploy markers exist on dashboards
- [ ] Monitoring is segmented by version/cohort/region/flag state
- [ ] Operator playbook for pause/rollback exists and is tested

---

## 6. Rollback Playbooks & Reconciliation

Rollback is not just “deploy previous version” — data and side effects persist.

### Rollback Checklist
- [ ] Rollback criteria defined (what triggers rollback)
- [ ] Rollback procedure documented (commands, toggles, dependencies)
- [ ] Compatibility after rollback is verified (old app reading data written by new app)
- [ ] Reconciliation plan exists for partial side effects (double-writes, partial payments, stuck workflows)
- [ ] Customer support / ops workflow exists for manual remediation when needed

---

## 7. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Change-Focused)
- [ ] Mixed-version deploy test in staging (old + new instances together)
- [ ] Rollback rehearsal (deploy new, generate traffic, rollback, verify correctness)
- [ ] Migration dry-run and re-run (idempotency) with throttling enabled
- [ ] Backfill pause/resume test; ensure it can be stopped safely
- [ ] Contract fuzz tests (unknown fields, unknown enums, missing fields)
- [ ] Replay test for event consumers (historical messages + new schema)

### Monitoring Ideas (Change-Focused)
- [ ] Rollout dashboards with version/cohort/flag segmentation
- [ ] Compare metrics for dual-read paths (mismatch rate)
- [ ] Stuck workflow metrics (e.g., orders stuck in intermediate state)
- [ ] Migration progress + error counters + DLQ depth
- [ ] Business guardrails (conversion, checkout/payment success, auth success)
- [ ] Rollback health dashboard (post-rollback error/latency/business recovery)

---

## 8. Finding Snippet Templates

### Finding Snippet Template (Change Management)
```markdown
[CHANGE]
Finding: <specific deploy/migration/rollback risk>
Evidence: <code path / migration plan / config / rollout plan>
Why it matters: <mixed-version failure mode, blast radius, recovery risk>
Recommendation: <expand/contract, flag/kill switch, rollout plan, rollback playbook>
Validation: <mixed-version test + rollback rehearsal + migration tests>
Monitoring: <segmented dashboards + compare metrics + guardrails>
Priority: <P0/P1/P2/P3>
```
