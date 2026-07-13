# Quota & Limit Exhaustion Patterns (Lens 11 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-dependency.md` — retry/timeout/backoff guidance for external APIs
> - `references/checklist-change-management.md` — rollout/guardrail controls for risky throughput changes

## Table of Contents
1. Quota and Limit Inventory
2. Capacity Budgets and Headroom Policy
3. Exhaustion Behavior and Graceful Degradation
4. Cost Guardrails and Runaway Spend Prevention
5. External API Quotas and Third-Party Contracts
6. Operational Runbooks and Escalation
7. Validation & Monitoring Add-Ons
8. Finding Snippet Templates

---

## 1. Quota and Limit Inventory

You cannot protect what you have not inventoried.

### Inventory Checklist
- [ ] Cloud provider quotas documented (API calls, KMS decrypts, queue ops, IAM/STS, etc.)
- [ ] Compute/resource limits documented (CPU, memory, file descriptors, sockets, IOPS)
- [ ] Database limits documented (connections, TPS/QPS, storage, lock contention constraints)
- [ ] Third-party API limits documented (rate, burst, daily/monthly caps)
- [ ] Internal per-tenant/per-feature budgets documented
- [ ] Ownership and escalation paths defined for each critical limit

### Common Blind Spots
- Global quotas shared across staging/prod
- "Soft" limits that become hard under retry storms
- Background jobs consuming the same quota budget as user traffic
- Limit-increase lead time that exceeds the time-to-exhaust forecast

---

## 2. Capacity Budgets and Headroom Policy

Capacity planning should include normal growth and failure-mode amplification.

### Budgeting Checklist
- [ ] Quota budgets are allocated by criticality (interactive traffic first)
- [ ] Headroom targets are derived from peak forecast, burst shape, retry/failover
  amplification, scaling or quota-increase lead time, and desired recovery margin
- [ ] Retry amplification is accounted for in quota models
- [ ] Burst policy exists (what traffic can be delayed/dropped first)
- [ ] Automated or manual limit-increase process is documented and tested
- [ ] Planned launches/migrations include quota impact review
- [ ] Headroom assumptions are revalidated after architecture, traffic, or provider-limit changes

Do not use one universal headroom percentage. State the demand model and operational lead time
that justify the selected target.

### Severity Guidance
- No headroom policy on a critical dependency: usually **P1-HIGH** when exhaustion is credible
- Exhaustion likely to hard-fail a core path without fallback: often **P0/P1** based on blast radius

---

## 3. Exhaustion Behavior and Graceful Degradation

When limits are hit, the system needs predictable behavior, not cascading failure.

### Exhaustion Checklist
- [ ] Quota nearing-hard-limit is visible via telemetry and forecast alerts
- [ ] Backpressure/admission control activates before saturation collapse
- [ ] Responses communicate retryability clearly (429/503 + retry guidance when safe)
- [ ] Mutating paths have bounded, deadline-aware retry budgets
- [ ] Non-critical work can be queued, delayed, or dropped first
- [ ] Recovery behavior after quota reset is controlled (no thundering herd)
- [ ] First attempts retain capacity when retry traffic rises

### Anti-Patterns
- Infinite retries on quota/limit errors
- Shared queue growth with no depth cap
- Treating quota errors as generic 500s
- Honoring `Retry-After` beyond the caller's deadline or local capacity budget

---

## 4. Cost Guardrails and Runaway Spend Prevention

Cost incidents are reliability incidents when they force emergency shutdowns or quota lockouts.

### Cost Guardrail Checklist
- [ ] Per-tenant or per-feature spend budgets exist where applicable
- [ ] High-cost operations have volume caps or approvals
- [ ] A bounded emergency control exists for runaway high-cost loops
- [ ] "Safe mode" can disable non-essential expensive features quickly
- [ ] Cost anomaly detection alerts route to operators with clear actions
- [ ] Cost controls cannot silently corrupt or abandon mutating work

---

## 5. External API Quotas and Third-Party Contracts

External quota behavior must be first-class in client design.

### Third-Party Quota Checklist
- [ ] Client distinguishes 429/limit errors from specific transient server failures
- [ ] Retry strategy honors provider guidance within hard attempt, deadline, and capacity ceilings
- [ ] Idempotency and deduplication are enforced on retried mutations
- [ ] Fallback/degraded behavior is documented for sustained quota pressure
- [ ] Contract limits, increase paths, and provider response times are known
- [ ] Quota exhaustion does not silently corrupt business state

---

## 6. Operational Runbooks and Escalation

### Runbook Checklist
- [ ] Quota-exhaustion playbook includes detect, contain, recover steps
- [ ] Immediate mitigations are scripted (throttle, queue pause, feature disablement)
- [ ] Escalation contacts and limit-increase process are current
- [ ] Post-incident reconciliation process is defined for dropped/deferred work
- [ ] SLO/SLA communications plan exists for sustained limit events
- [ ] Recovery removes temporary throttles gradually to avoid rebound overload

---

## 7. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Quota-Focused)
- [ ] Fault-inject quota responses (429, resource exhausted, ENOSPC, too many connections)
- [ ] Load tests approach the derived quota boundary under normal, burst, retry, and failover demand
- [ ] Retry-budget exhaustion tests on mutating flows
- [ ] Graceful-degradation drill (disable non-critical paths under pressure)
- [ ] Recovery test after quota reset to verify no retry-storm rebound
- [ ] Limit-increase or emergency-capacity procedure rehearsal where business-critical

### Monitoring Ideas (Quota-Focused)
- [ ] Quota utilization and projected time-to-exhaust with forecast assumptions
- [ ] Resource saturation (connections, IOPS, disk, FD, queue depth)
- [ ] Quota/error reason counters by dependency and normalized endpoint
- [ ] Retry amplification counters, first-attempt capacity, and budget consumption
- [ ] Cost anomaly indicators and emergency guardrail activations
- [ ] Time from limit-increase request to usable capacity

---

## 8. Finding Snippet Templates

### Finding Snippet Template (Quota/Limit Exhaustion)
```markdown
[QUOTA]
Finding: <quota or hard-limit exhaustion risk>
Evidence: <dependency/resource limits, demand model, retry behavior, missing guardrails>
Why it matters: <service collapse, cascading retries, cost spike, user-facing outage>
Recommendation: <inventory + alerts + backpressure + degradation + budget controls>
Validation: <quota fault injection + load-to-limit test + recovery drill>
Monitoring: <utilization, time-to-exhaust, saturation, retry budget, cost guardrails>
Priority: <P0/P1/P2/P3>
```
