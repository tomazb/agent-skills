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
