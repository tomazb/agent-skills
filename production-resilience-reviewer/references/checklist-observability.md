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
Every unique metric-attribute combination creates a time series. Cardinality risk depends on
the **product** of all dimensions, event volume, retention, aggregation, and the telemetry
backend's budget—not on one universal per-label threshold.

**Usually safe dimensions** are deliberately bounded and operationally useful:
- HTTP method or status class
- Service, normalized route, region, environment, dependency, version, or bounded error class
- Product tiers or feature states with a known finite set

**Usually dangerous dimensions** are unbounded or attacker/user controlled:
- User, account, session, request, or trace identifiers
- Raw URL paths containing IDs or arbitrary query values
- Error message text, stack traces, IP addresses, or payload values

For each proposed dimension:
- Estimate the Cartesian product with existing dimensions under peak traffic.
- Confirm the backend's ingestion, query, and retention budget.
- Normalize routes and error classes before recording them.
- Put request/trace IDs in logs and traces, not metric labels.
- Use metric exemplars to link representative measurements to traces when supported.

---

## 3. Logging Standards

### Structured Logging
Prefer machine-parseable records with consistent fields when the platform supports structured
logging. Preserve the project's established format when changing it would add more risk than value.

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
  "action": "Retry deferred according to provider guidance; investigate if the rate-limit condition persists."
}
```

### Log Level Guide
- **FATAL**: Process is about to crash. Page someone immediately.
- **ERROR**: Operation failed, needs investigation. This request/user is affected.
- **WARN**: Something unexpected happened but was handled. May indicate a developing problem.
- **INFO**: Significant business events (order placed, user signed up, deployment started).
- **DEBUG**: Detailed technical information for troubleshooting. OFF in production by default.

### What to Log (Minimum)
- [ ] Inbound request outcome, normalized route, correlation ID, status, and latency where appropriate
- [ ] Outbound dependency call outcome, target, operation, classification, and latency
- [ ] Errors with sanitized operation context and preserved cause
- [ ] Significant state changes and business events
- [ ] Security-relevant events such as auth failures, denials, and throttling

### What NOT to Log
- [ ] Passwords, API keys, tokens, secrets (even in debug mode)
- [ ] Full credit card numbers, SSNs, or other sensitive identifiers
- [ ] Request/response bodies containing sensitive data unless explicitly approved and redacted
- [ ] High-volume per-item logs in batch operations when a bounded summary is sufficient

### Sensitive Data Handling
- Mask or tokenize sensitive values according to the organization's policy
- Hash identifiers only when the threat model and correlation need justify it
- Strip sensitive fields from error context before logging
- Test log redaction and review sampled production output for accidental leakage

---

## 4. Alerting Strategy

### Alert Design Principles
1. **Page primarily on user-impacting symptoms**; retain cause signals for diagnosis and automation.
2. **Every page must have an action**: if there is nothing useful to do, redesign or remove it.
3. **Tune for meaningful, sustained conditions** so operators trust the signal.
4. **Route lower-urgency trends to tickets or asynchronous channels**, not the pager.

### Alert Severity Tiers
- **Critical/page**: Material active or imminent user/business impact requiring immediate action
- **High/asynchronous alert**: Degradation or capacity risk that needs timely investigation
- **Informational/ticket**: Trend, debt, or approaching limit without immediate impact

### SLO-Based Alerting (Preferred)
Define the SLI as a ratio of good events to valid total events and alert on error-budget burn.
For example:

```text
SLI: good checkout requests / valid checkout requests
Good: completed successfully within the agreed latency objective
SLO: target and window derived from the user promise and business requirement

Page when both a short window and a longer confirmation window show a burn rate that would
exhaust the budget too quickly. Create a ticket for sustained low burn that threatens the
window without requiring immediate response.
```

Choose burn-rate thresholds and windows from the SLO, page policy, traffic volume, and desired
detection/reset behavior. Low-traffic services may need minimum-event guards, longer windows,
or synthetic signals to avoid unstable percentage alerts.

### Alert Anti-Patterns
- **Too many alerts**: On-call fatigue causes important alerts to be ignored
- **No runbook linked**: The responder has no clear first action
- **Threshold too sensitive**: Transient or low-volume noise repeatedly pages
- **Missing impact signal**: Operators learn about user impact from support rather than telemetry
- **Duplicate alerts**: One incident fans out into many independent pages

---

## 5. Dashboard Design for 3 AM

### The 60-Second Goal
An on-call engineer looking at the dashboard for the first time should quickly answer:

1. **Is the system healthy right now?**
2. **What changed recently?**
3. **Where is the problem?**
4. **How bad is the user or business impact?**

### Dashboard Layout Pattern
```
Row 1: Health summary
  - Overall status / SLO burn
  - Key business outcomes

Row 2: Traffic and errors
  - Request rate by normalized endpoint
  - Error rate by bounded class
  - Deployment and configuration markers

Row 3: Latency
  - Relevant latency distributions by endpoint
  - Latency by dependency

Row 4: Resources
  - CPU, memory, disk, pool saturation, queue depth, cache behavior

Row 5: Dependencies
  - Per-dependency error/latency and circuit state
```

### Dashboard Anti-Patterns
- Too many panels to establish system state quickly
- Metrics without a baseline, objective, or capacity context
- Missing time-range controls or deployment/configuration markers
- Raw high-cardinality dimensions that make the dashboard slow or costly

---

## 6. Runbook Template

Every actionable alert should link to a runbook appropriate to its urgency:

```markdown
# [Alert Name] Runbook

## What This Alert Means
[What user-facing impact is happening or imminent]

## Severity and Ownership
[Urgency, owning team, escalation path, and decision authority]

## First Response
1. Check [impact/SLO dashboard] — confirm scope and severity.
2. Check [dependency and infrastructure signals] — identify correlated failures.
3. Check [deployment/configuration history] — identify recent changes.

## Diagnosis Steps
### If error rate is elevated:
1. [Specific trace/log/metric query]
2. [Expected classifications and next branch]

### If latency is elevated:
1. [Dependency and pool-wait panels]
2. [Relevant profiling/query diagnostics]

### If saturation is high:
1. [Admission-control and queue state]
2. [Leak/contention checks]

## Mitigation Actions
- [Feature or traffic control with authorization and stop conditions]
- [Rollback procedure and compatibility checks]
- [Scale or failover action only when it addresses the measured bottleneck]

## Recovery Verification
- [User/business outcome recovered]
- [Backlog or reconciliation state healthy]
- [Temporary controls can be safely removed]

## Post-Incident
- [ ] Capture timeline and contributing controls
- [ ] Update this runbook with verified learning
- [ ] Assign preventive work with owner and due date
```

---

## 7. Change Management & Rollout Observability (Lens 8 Alignment)

For broader rollout and rollback patterns, see `references/checklist-change-management.md`.

Observability must support **deployment decisions**, not just incident diagnosis. A risky change without rollout telemetry is guesswork.

### Rollout Telemetry Checklist
- [ ] Deployment markers appear on key dashboards (version, time, region, operator)
- [ ] Metrics can be segmented by version / cohort / region / feature flag state with bounded cardinality
- [ ] Canary and baseline are directly comparable
- [ ] Rollout has explicit success metrics and rollback thresholds
- [ ] Feature-flag and config changes are audited with timestamps
- [ ] Business and correctness guardrails accompany technical signals

### Canary / Progressive Delivery Guardrails
- [ ] Compare error rate and latency between canary and control
- [ ] Compare business metrics between canary and control
- [ ] Monitor dependency-specific regressions introduced by the new version
- [ ] Track new error classes and unknown outcomes during the rollout
- [ ] Auto-pause or manual halt criteria are documented and operable

### Rollback Observability
- [ ] Rollback events are marked on dashboards
- [ ] Rollback completion is verified by version distribution
- [ ] Post-rollback health checks confirm user/business recovery
- [ ] Data/migration compatibility and stuck workflows are monitored after rollback
- [ ] Alert noise is managed without hiding real impact

### Observability Anti-Patterns During Changes
- "Watch the logs" as the only rollout strategy
- No version/cohort signal for comparison
- Rollback triggered without checking whether the issue is independent of the change
- Thresholds tuned only for steady state and blind to canary differences
- No shared rollout view for on-call and release owner

---

## 8. Validation & Monitoring Add-Ons (Lens 8 + Required Finding Template Alignment)

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation: Prove Observability Works Before You Need It
- [ ] Synthetic test generates a known error and verifies alert routing
- [ ] Trace propagation test across service and async boundaries
- [ ] Dashboard smoke test confirms key panels populate in pre-production
- [ ] Cardinality review estimates the complete dimension product and backend cost
- [ ] Log redaction test confirms secrets/PII are not emitted
- [ ] Canary rehearsal verifies version-segmented dashboards and stop criteria
- [ ] Another engineer can follow the runbook for a seeded failure

### Monitoring: Core + Rollout-Specific Signals
- [ ] RED + USE + business/correctness metrics for impacted paths
- [ ] Multi-window SLO burn-rate alerts where appropriate
- [ ] Queue/DLQ/lag and dependency health signals for changed workflows
- [ ] Version/canary comparison panels and diff metrics
- [ ] New error-class / anomaly views during rollout
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
