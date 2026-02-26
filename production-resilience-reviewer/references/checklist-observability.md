# Observability, Metrics, Logging & Alerting Patterns

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-change-management.md` — rollout/migration/rollback deep-dive (Lens 8)


## Table of Contents
1. The Three Pillars + One
2. Metric Design Patterns
3. Logging Standards
4. Alerting Strategy
5. Dashboard Design for 3 AM
6. Runbook Template
7. Change Management & Rollout Observability
8. Validation & Monitoring Add-Ons

---

## 1. The Three Pillars + One

### Metrics (What is happening?)
- Numeric measurements aggregated over time
- Used for: dashboards, alerts, capacity planning, SLO tracking
- Tools: Prometheus, Datadog, CloudWatch, StatsD

### Logs (Why did it happen?)
- Discrete events with context
- Used for: debugging specific incidents, audit trails, forensics
- Tools: ELK, Splunk, CloudWatch Logs, Loki

### Traces (Where did it happen?)
- Request-scoped context propagated across service boundaries
- Used for: understanding latency, finding bottlenecks, mapping request flow
- Tools: Jaeger, Zipkin, Datadog APM, AWS X-Ray

### + Profiling (How is it happening?)
- Continuous profiling of CPU, memory, allocations
- Used for: finding performance regressions, memory leaks, hot code paths
- Tools: Pyroscope, pprof, async-profiler

---

## 2. Metric Design Patterns

### RED Method (for request-driven services)
For every service endpoint:
- **Rate**: Requests per second
- **Errors**: Failed requests per second (and error rate as %)
- **Duration**: Latency distribution (p50, p90, p95, p99, max)

### USE Method (for resources)
For every resource (CPU, memory, disk, connections, queues):
- **Utilization**: % of resource capacity being used
- **Saturation**: Amount of work queued/waiting (e.g., thread pool queue depth)
- **Errors**: Error count related to the resource (e.g., connection pool exhaustion)

### The Four Golden Signals (Google SRE)
- **Latency**: Time to serve a request (separate success latency from error latency)
- **Traffic**: Demand on the system (requests/sec, transactions/sec)
- **Errors**: Rate of failed requests (explicit like 5xx, implicit like wrong content, policy-based like "too slow")
- **Saturation**: How full the system is (CPU, memory, I/O, queue depth)

### Business Metrics (Often Missing, Always Critical)
Technical metrics tell you the system is broken. Business metrics tell you *users are affected*:
- Orders per minute (is the checkout flow working?)
- Signup completion rate (is the registration flow healthy?)
- Search results returned (is the search backend responding?)
- Payment success rate (is the payment flow working?)
- Active sessions (are users actually using the product?)

### Metric Naming Conventions
```
# Format: <namespace>_<subsystem>_<metric_name>_<unit>
# Examples:
api_http_requests_total              # counter
api_http_request_duration_seconds    # histogram
db_connections_active                # gauge
queue_messages_depth                 # gauge
payment_charges_total                # counter (business metric)
payment_charge_amount_dollars        # histogram (business metric)
```

### Cardinality Management
High-cardinality labels kill metric systems. Every unique label combination creates a new time series.

**Safe labels** (bounded cardinality):
- HTTP method (GET, POST, PUT, DELETE, PATCH — ~5 values)
- HTTP status code class (2xx, 3xx, 4xx, 5xx — 4 values)
- Service name, endpoint name, region, environment

**Dangerous labels** (unbounded cardinality):
- User ID (millions of values)
- Request ID / trace ID (infinite values)
- Full URL path with path parameters (`/users/12345` — infinite values)
- Error message text (infinite variations)
- IP address

**Rule of thumb**: If a label can have more than ~100 unique values, it should NOT be a metric label. Put it in logs instead.

---

## 3. Logging Standards

### Structured Logging (Non-Negotiable)
Every log entry should be machine-parseable JSON with consistent fields:

```json
{
  "timestamp": "2025-01-15T03:42:17.123Z",
  "level": "ERROR",
  "service": "payment-service",
  "environment": "production",
  "correlation_id": "req-abc-123",
  "trace_id": "trace-xyz-789",
  "component": "StripeClient",
  "operation": "charge",
  "message": "Payment charge failed",
  "error_type": "RateLimitError",
  "error_code": "429",
  "context": {
    "customer_id": "cus_abc123",
    "amount_cents": 4999,
    "currency": "usd",
    "idempotency_key": "ik_xyz789",
    "retry_attempt": 2,
    "max_retries": 3
  },
  "action": "Auto-retry scheduled in 60s. If persistent, check Stripe status page."
}
```

### Log Level Guide
- **FATAL**: Process is about to crash. Page someone immediately.
- **ERROR**: Operation failed, needs investigation. This request/user is affected.
- **WARN**: Something unexpected happened but was handled. May indicate a developing problem.
- **INFO**: Significant business events (order placed, user signed up, deployment started).
- **DEBUG**: Detailed technical information for troubleshooting. OFF in production by default.

### What to Log (Minimum)
- [ ] Every inbound request (method, path, correlation ID, response status, latency)
- [ ] Every outbound dependency call (target, method, response status, latency)
- [ ] Every error with full context (what was attempted, with what inputs, what failed, what to do)
- [ ] Every significant state change (user created, order status changed, config reloaded)
- [ ] Every security-relevant event (auth success/failure, permission denied, rate limited)

### What NOT to Log
- [ ] Passwords, API keys, tokens, secrets (even in debug mode)
- [ ] Full credit card numbers, SSNs, or other PII (mask or hash)
- [ ] Request/response bodies containing sensitive data (log metadata only)
- [ ] High-volume per-item logs in batch operations (log summary with count, not each item)

### Sensitive Data Handling
- Mask PII: `email: "j***@example.com"`, `card: "****4242"`
- Hash identifiers if needed for correlation: `user_hash: sha256(userId)`
- Strip sensitive fields from error context before logging
- Review log output regularly for accidental PII exposure

---

## 4. Alerting Strategy

### Alert Design Principles
1. **Alert on symptoms, not causes**: Alert on "error rate > 5%" not "Pod restarted". Users care about symptoms.
2. **Alert on user impact**: If the alert fires and no user is affected, it's noise.
3. **Every alert must have an action**: If there's nothing to do when the alert fires, delete it.
4. **Alerts should be rare and meaningful**: If an alert fires daily and gets ignored, it's worse than no alert.

### Alert Severity Tiers
- **P1/Critical (page)**: Revenue-impacting, data loss, security breach, SLO violation, complete feature outage
- **P2/High (Slack alert)**: Degraded performance, partial outage, elevated error rates, capacity warning
- **P3/Info (ticket)**: Trends worth investigating, approaching thresholds, non-urgent anomalies

### SLO-Based Alerting (Preferred)
Instead of arbitrary thresholds, alert based on error budget consumption:

```
SLO: 99.9% availability (43.8 minutes/month error budget)

Alert if: 
  - 5% of monthly error budget consumed in 1 hour → P2 (Slack)
  - 10% of monthly error budget consumed in 6 hours → P1 (Page)
  - 50% of monthly error budget remaining → P3 (Ticket: investigate trend)
```

### Alert Anti-Patterns
- **Too many alerts**: On-call fatigue → alerts get ignored → real incidents missed
- **No runbook linked**: Alert fires, on-call engineer has no idea what to do
- **Threshold too sensitive**: Alert fires on transient spikes (use sustained thresholds or rate-of-change)
- **Missing alert**: The thing that pages you at 3 AM should have been alerting before it became critical
- **Duplicate alerts**: Same incident triggers 15 alerts from different monitors

---

## 5. Dashboard Design for 3 AM

### The 60-Second Rule
An on-call engineer looking at your dashboard for the first time, at 3 AM, half awake,
should be able to answer these questions in under 60 seconds:

1. **Is the system healthy right now?** (Big green/red/yellow indicator at the top)
2. **What changed recently?** (Deployment markers, config changes, traffic spikes on timeline)
3. **Where is the problem?** (Error rates broken down by service/endpoint/dependency)
4. **How bad is it?** (Impact metrics: users affected, requests failing, revenue at risk)

### Dashboard Layout Pattern
```
Row 1: Health summary
  - Overall status indicator (green/yellow/red)
  - Key business metrics (orders/min, active users, revenue/hour)
  - SLO burn rate

Row 2: Traffic and errors
  - Request rate (total and by endpoint)
  - Error rate (total and by error type)
  - Recent deployments / config changes (overlay markers)

Row 3: Latency
  - p50, p90, p99 latency by endpoint
  - Latency by dependency (which downstream is slow?)

Row 4: Resources
  - CPU, memory, disk utilization
  - Connection pool usage
  - Queue depth
  - Cache hit rate

Row 5: Dependencies
  - Per-dependency error rate and latency
  - Circuit breaker states
  - Health check status
```

### Dashboard Anti-Patterns
- Dashboards with 50+ panels that require scrolling → nobody looks at them
- Metrics without context (what is "normal"? show historical baseline)
- Missing time range selector (default to last 1 hour for incident response)
- No deployment markers (impossible to correlate changes with issues)

---

## 6. Runbook Template

Every alert should link to a runbook. Minimum viable runbook:

```markdown
# [Alert Name] Runbook

## What This Alert Means
[One sentence: what user-facing impact is happening or imminent]

## Severity
[P1/P2/P3 and who to escalate to if you can't resolve in X minutes]

## First Response (< 5 minutes)
1. Check [dashboard link] — is the system actually unhealthy?
2. Check [dependency status page links] — is an external service down?
3. Check [deployment history link] — was anything deployed recently?

## Diagnosis Steps
### If error rate is elevated:
1. [Specific log query to run]
2. [What to look for in the results]

### If latency is elevated:
1. [Check this dependency dashboard]
2. [Check this database query performance panel]

### If resource utilization is high:
1. [Check for memory leaks: what to look for]
2. [Check for connection pool exhaustion: how]

## Mitigation Actions
### Quick mitigations (buy time):
- Scale up: `kubectl scale deployment X --replicas=N`
- Feature flag: Disable [feature] in [feature flag system]
- Rollback: `deploy rollback [service] to [last known good version]`

### Root cause fixes:
- [Common root cause 1]: [How to fix]
- [Common root cause 2]: [How to fix]

## Post-Incident
- [ ] Write incident report
- [ ] Update this runbook with anything you learned
- [ ] File tickets for preventive measures
```


---

## 7. Change Management & Rollout Observability (Lens 8 Alignment)

For broader rollout and rollback patterns, see `references/checklist-change-management.md`.

Observability must support **deployment decisions**, not just incident diagnosis. A risky change without rollout telemetry is guesswork.

### Rollout Telemetry Checklist
- [ ] Deployment markers appear on key dashboards (version, time, region, operator)
- [ ] Metrics can be segmented by version / cohort / region / feature flag state
- [ ] Canary and baseline are directly comparable on the same dashboard
- [ ] Rollout has explicit success metrics and rollback thresholds
- [ ] Feature-flag state changes are logged/audited with timestamps
- [ ] Config changes are tracked and correlated with incidents

### Canary / Progressive Delivery Guardrails
- [ ] Compare error rate and latency between canary and control
- [ ] Compare business metrics (conversion, checkout success, auth success) between canary and control
- [ ] Monitor dependency-specific regressions introduced by the new version
- [ ] Track "unknown unknowns" with top error/new log signature panels
- [ ] Auto-pause or manual halt criteria are documented

### Rollback Observability
- [ ] Rollback events are marked on dashboards
- [ ] Rollback completion is verified by version distribution metrics
- [ ] Post-rollback health checks confirm recovery (not just deployment success)
- [ ] Data/migration compatibility metrics are monitored after rollback (mismatches, stuck workflows)
- [ ] Alert noise is managed during rollout/rollback (inhibition/silence policy)

### Observability Anti-Patterns During Changes
- "Watch the logs" as the only rollout strategy
- No version labels in metrics, making canary comparison impossible
- Rollback triggered without verifying whether issue is dependency-related
- Alert thresholds tuned for steady state but not rollout sensitivity
- No single rollout dashboard for on-call and release owner

---

## 8. Validation & Monitoring Add-Ons (Lens 8 + Required Finding Template Alignment)

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

This section helps convert observability recommendations into concrete validation and ongoing monitoring steps.

### Validation: Prove Observability Works Before You Need It
- [ ] Synthetic test generates a known error and verifies alert fires + routes correctly
- [ ] Trace propagation test across service boundaries (correlation/trace IDs preserved)
- [ ] Dashboard smoke test: key panels populate in staging/pre-prod
- [ ] Cardinality review for new metric labels (bounded values only)
- [ ] Log redaction test confirms secrets/PII are not emitted
- [ ] Canary rehearsal (or simulated rollout) verifies version-segmented dashboards
- [ ] Runbook drill: another engineer can follow steps and diagnose a seeded failure

### Monitoring: Core + Rollout-Specific Signals
- [ ] RED + USE + business metrics for impacted paths
- [ ] SLO burn-rate alerts (multi-window where critical)
- [ ] Queue/DLQ/lag and dependency health signals for changed workflows
- [ ] Version/canary comparison panels and diff metrics
- [ ] New error signature / anomaly views during rollout window
- [ ] Rollout timeline markers (deploy, config, flag changes, rollback)
- [ ] Alert routing, ownership, and escalation path verified

### Finding Snippet Template (Observability)
```markdown
[OBSERVABILITY]
Finding: <missing metric/log/alert/dashboard/runbook/rollout telemetry>
Evidence: <current instrumentation gap>
Why it matters: <slow detection, hard triage, unsafe rollout, hidden user impact>
Recommendation: <what to instrument and where>
Validation: <synthetic alert test / dashboard smoke test / trace propagation check>
Monitoring: <alerts, dashboards, burn rate, rollout guardrails>
Priority: <P0/P1/P2/P3>
```
