# Validation & Monitoring Patterns

Use this reference to strengthen findings with **proof plans** (validation) and
**production verification** (monitoring). Pair it with the required finding template in `SKILL.md`.

## Validation Patterns (What to Ask For)

Choose the validation method that best matches the failure mode:

### Unit / Component Validation
- Unit test for edge case / error classification
- State-machine transition tests (including invalid transitions)
- Parser/schema validation tests (bad types, missing fields, large payloads)
- Property-based tests for invariants (idempotency, monotonicity, round-trip correctness)

### Integration / Dependency Validation
- Integration test with dependency timeout / 5xx / malformed response
- Retry behavior test (backoff + jitter + max retries respected)
- Circuit breaker open/half-open/close transitions
- Deadline propagation test across service boundaries
- Fallback behavior test (cache/default/degraded mode)

### Load / Concurrency Validation
- Load test at 1x / 5x / 10x expected traffic
- Soak test for resource leaks (memory, file handles, connections)
- Contention test for locks/pools
- Queue depth growth test and backpressure behavior
- Replay/duplicate-delivery test for async consumers

### Change / Rollout / Migration Validation
- Mixed-version deploy compatibility test
- Migration dry-run / backfill rehearsal (idempotent reruns)
- Rollback rehearsal after partial rollout
- Feature-flag on/off behavior test
- Canary success criteria verification before wider rollout

## Monitoring Patterns (What to Ask For)

Monitoring should prove the change is safe in production and make failures debuggable.

### Core Technical Signals
- Request rate / error rate / latency (RED) on impacted endpoints
- Resource utilization / saturation / errors (USE): CPU, memory, pools, queue depth
- Dependency-specific metrics (timeouts, 4xx/5xx, rate limits, circuit breaker state)
- Bounded-cardinality labels only (no raw user IDs / unbounded inputs)

### Business & Correctness Guardrails
- Business KPI guardrails (orders, payments, signups, fulfillment)
- Data consistency mismatch counters (dual-read compare mismatch, reconciliation failures)
- Duplicate processing counters and dedup hit rate for async consumers
- Stuck workflow/entity counts (e.g., stuck orders/jobs)

### Rollout / Change Safety Monitoring
- Canary vs control comparison metrics (error rate, latency, success rate)
- Deployment markers on dashboards
- Rollout-specific alerts and rollback trigger thresholds
- Feature-flag state visibility in logs/metrics
- Backfill progress / migration error rate / rollback health indicators

### Logs / Traces / Debuggability
- Structured logs with correlation/trace IDs
- Error classification fields (`timeout`, `upstream_5xx`, `validation_error`, etc.)
- Trace propagation verified end-to-end on changed path
- Actionable runbook links from alerts

## Practical Rule of Thumb

For every **P0/P1** recommendation, include:
1. **How to prove the fix works before deploy** (validation)
2. **How to detect regressions after deploy** (monitoring)

Tailor the choices to the lens involved (dependency, data, observability, or change management)
instead of using a generic checklist for every finding.

## Before / After: Common Fixes

Concrete examples of transforming fragile patterns into resilient ones.

### Cardinality explosion → bounded labels

**Before:**
```
http_requests_total{user_id="u-38291", endpoint="/api/search"}
```
Unbounded `user_id` label — 1M users = 1M time series per metric. Prometheus TSDB grows without limit; query performance degrades, memory spikes, compaction stalls.

**After:**
```
http_requests_total{user_tier="free", endpoint="/api/search"}
```
Bounded label with known cardinality (`free|paid|enterprise`). Same operational insight for capacity planning, dramatically reduced storage and query cost.

---

### Missing SLI → actionable SLI-based alert

**Before:**
```
histogram: http_request_duration_seconds
# No SLO target, no error budget, no alert.
# Team checks Grafana manually after incidents.
```
Raw latency metric with no defined good/bad threshold. Team discovers problems from user complaints, not monitoring.

**After:**
```
sli:checkout_latency:p99 < 500ms  # SLO target
alert: SLOBudgetBurn
  expr: sli:checkout_latency:budget_remaining < 0.9  # 10% budget consumed
  for: 5m
  labels: { severity: warning }
```
SLI tied to user-visible outcome. Error budget alert fires before users notice. On-call knows exactly what threshold was breached and how much budget remains.

---

### Unbounded retry → budgeted retry with backoff

**Before:**
```python
while True:
    try:
        response = call_service()
        break
    except Exception:
        time.sleep(1)  # fixed delay, infinite retries
```
Infinite retries with fixed 1s delay. During outage: every caller hammers the failing service, preventing recovery. No jitter = thundering herd on retry.

**After:**
```python
@retry(
    max_attempts=3,
    backoff=exponential(base=1, max=30),
    jitter=True,
    retry_budget=0.2,  # max 20% of requests can be retries
    on_exhausted=circuit_breaker.open
)
def call_service():
    response = client.post(url, timeout=5, idempotency_key=request_id)
    return response
```
Bounded retries with exponential backoff + jitter. Retry budget prevents amplification. Circuit breaker stops retries when downstream is confirmed unhealthy. Idempotency key makes retries safe for mutating operations.

## Common Monitoring Anti-Patterns

Patterns that create a false sense of observability or actively harm incident response.

- **Cardinality bombs** — Using raw user IDs, request paths, or UUIDs as metric labels. TSDB grows unbounded; queries slow to a crawl; memory pressure forces restarts.
- **Alert-on-everything** — Alerting on every individual error instead of error rate or budget burn. On-call fatigue → alerts get ignored → real incidents missed.
- **Dashboard-only monitoring** — Metrics and dashboards exist but no alerts are configured. Requires a human to stare at screens 24/7 to detect problems.
- **Missing business metrics** — Plenty of technical signals (CPU, memory, latency) but no business KPIs (orders, revenue, signups). Cannot determine whether users are actually affected.
- **Log-based alerting as primary signal** — Using log grep or log pattern matching as the main alerting mechanism. Brittle, high-latency, hard to tune, impossible to aggregate.
- **Percentage-only thresholds** — "Alert if error rate > 5%" without considering request volume. 1 error out of 20 requests triggers the same as 5,000 errors out of 100,000.
- **No baseline or historical context** — Metrics without comparison to historical norms. "Is 200ms latency good or bad?" is unanswerable without knowing that yesterday's p99 was 50ms.
