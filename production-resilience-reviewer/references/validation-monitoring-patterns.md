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
- Integration test with dependency phase timeout, total deadline, selected transient failure,
  malformed response, and ambiguous post-send outcome
- Retry classification test (safe operation, retryable error, backoff/jitter, deadline, and budget)
- Circuit breaker open/half-open/close transitions based on aggregated dependency evidence
- Deadline propagation test across service boundaries
- Fallback behavior test (cache/default/degraded/queued mode)

### Load / Concurrency Validation
- Test expected peak, planned growth, stress, and failure-amplified scenarios derived from the
  demand model; do not rely on a universal traffic multiplier
- Soak test for resource leaks (memory, file handles, connections)
- Contention test for locks/pools
- Queue depth growth test and backpressure behavior
- Replay/duplicate-delivery test for async consumers

### Change / Rollout / Migration Validation
- Mixed-version deploy compatibility test
- Migration dry-run / backfill rehearsal (idempotent reruns)
- Rollback rehearsal after partial rollout and new-format writes
- Feature-flag on/off behavior test
- Canary success and stop criteria verification before wider rollout

## Monitoring Patterns (What to Ask For)

Monitoring should prove the change is safe in production and make failures debuggable.

### Core Technical Signals
- Request rate / error rate / latency (RED) on impacted endpoints
- Resource utilization / saturation / errors (USE): CPU, memory, pools, queue depth
- Dependency-specific metrics (deadlines, classified failures, rate limits, circuit state)
- Bounded-cardinality dimensions only; keep request/trace IDs in logs and traces

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
- Error classification fields (`deadline_exceeded`, `upstream_503`, `validation_error`, etc.)
- Trace propagation verified end-to-end on changed path
- Metric exemplars linked to traces where supported
- Actionable runbook links from alerts

## Practical Rule of Thumb

For every **P0/P1** recommendation, include:
1. **How to recreate the failure and prove the fix before deploy** (validation)
2. **How to detect user/business regression after deploy** (monitoring)

Tailor the choices to the failure chain instead of attaching a generic checklist to every finding.
Do not prescribe a numeric timeout, retry count, pool limit, headroom target, alert threshold, or
drill cadence without stating the objective, measurement, provider constraint, or assumption used
to derive it. Values in examples are illustrative only.

## Before / After: Common Fixes

Concrete examples of transforming fragile patterns into resilient ones.

### Cardinality explosion → bounded dimensions

**Before:**
```
http_requests_total{user_id="u-38291", endpoint="/api/search"}
```
Unbounded `user_id` creates a new time series per label combination and can make ingestion,
retention, and queries prohibitively expensive.

**After:**
```
http_requests_total{user_tier="free", route="/api/search"}
```
The bounded tier and normalized route preserve aggregate capacity insight. Put a specific user or
request identifier in logs/traces, and use an exemplar to link a representative measurement to a
trace when supported.

---

### Raw latency metric → good-event SLI and burn-rate alert

**Before:**
```
histogram: http_request_duration_seconds
# No definition of a good request, no SLO, no actionable alert.
```
A histogram alone does not define the user promise or distinguish acceptable from unacceptable
outcomes.

**After (conceptual configuration):**
```text
SLI = good checkout requests / valid checkout requests
Good = correct response completed within the agreed latency objective
SLO = target and window approved for this customer workflow

Alert policy:
- Page only when both a short window and a longer confirmation window show a burn rate
  that would exhaust the error budget too quickly.
- Create a ticket for sustained low burn that threatens the SLO window without requiring
  immediate response.
- Add minimum-event or synthetic-signal handling for low-traffic services.
```
The objective, burn-rate thresholds, and windows must be derived from the SLO and response policy,
not copied from this example.

---

### Unbounded retry → classified, deadline-aware, budgeted retry

**Before:**
```python
while True:
    try:
        response = call_service()
        break
    except Exception:
        time.sleep(1)  # fixed delay, infinite retries
```
Infinite retries with a fixed delay can hammer a failing service, outlive the caller's deadline,
and repeat mutations whose first outcome is unknown.

**After (conceptual pseudocode — adapt to the concrete client/runtime):**
```python
operation_id = payment.operation_id  # stable across all attempts for this business operation

for attempt in range(policy.max_attempts):
    remaining = request_deadline.remaining()
    if remaining <= policy.minimum_attempt_budget:
        raise DeadlineExceeded()

    try:
        return client.charge(
            payment,
            idempotency_key=operation_id,
            total_timeout=remaining,
        )
    except ProviderError as error:
        final_attempt = attempt + 1 == policy.max_attempts
        if final_attempt or not retry_classifier.is_transient(error):
            raise
        if not retry_budget.try_consume():
            raise RetryBudgetExhausted() from error

        sleep(
            policy.backoff.next_delay(
                attempt=attempt,
                retry_after=error.retry_after,
                remaining_budget=request_deadline.remaining(),
            )
        )
```
The retrying layer must own operation semantics, failure classification, and the remaining deadline.
Circuit state should be driven by aggregated dependency health, not opened merely because one
request exhausted its attempts.

## Common Monitoring Anti-Patterns

Patterns that create a false sense of observability or actively harm incident response.

- **Cardinality bombs** — Raw user IDs, request IDs, UUIDs, arbitrary paths, or error strings as metric dimensions.
- **Alert-on-everything** — Paging on individual errors instead of material impact or budget burn.
- **Dashboard-only monitoring** — Metrics exist but no actionable detection path is configured.
- **Missing business metrics** — Technical health cannot show whether the workflow users care about succeeds.
- **Log-based alerting as the primary signal** — Brittle pattern matching replaces stable metrics/SLIs.
- **Percentage-only thresholds** — A percentage alert ignores sample size and behaves badly at low volume.
- **No baseline or objective** — A value cannot be judged without expected behavior, capacity, or an SLO.
