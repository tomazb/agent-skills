# Dependency Failure Patterns & Mitigations

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-change-management.md` — rollout/migration/rollback deep-dive (Lens 8)


## Table of Contents
1. Failure Mode Taxonomy
2. Circuit Breaker Patterns
3. Fallback Strategies
4. Timeout Strategy Guide
5. Retry Strategy Guide
6. Dependency Health Checking
7. Dependency Change Management & Rollback Safety
8. Validation & Monitoring Add-Ons

---

## 1. Failure Mode Taxonomy

Every external dependency can fail in several ways. Check the classes applicable to the
protocol, client, and operation under review.

### Connection-Level Failures
- **Connection refused**: Service is down or port is wrong
- **DNS resolution failure**: DNS server down, name doesn't exist, TTL cache expired
- **TLS handshake failure**: Certificate expired, CA not trusted, protocol mismatch
- **Connection timeout**: Service is unreachable (firewall, network partition)
- **Connection reset**: Service crashed mid-request, load balancer killed connection

### Request-Level Failures
- **Read timeout**: Service accepted connection but response is too slow
- **HTTP 4xx**: Client error (bad request, unauthorized, forbidden, not found, rate limited)
- **HTTP 5xx**: Server-side failure whose retry semantics depend on the specific status,
  operation, and provider contract
- **Malformed response**: Valid HTTP but body is not valid JSON/XML/protobuf
- **Partial response**: Connection dropped mid-transfer, truncated body
- **Unexpected response shape**: Valid JSON but schema has changed (field renamed, type changed, field removed)

### Semantic Failures
- **Stale data**: Response is technically valid but information is outdated
- **Incorrect data**: Response looks right but contains wrong values (upstream bug)
- **Inconsistent data**: Response contradicts other data sources
- **Rate limiting**: 429 responses, often with Retry-After headers
- **Quota exhaustion**: API key or account has hit its usage limit

### Infrastructure Failures
- **DNS propagation lag**: Recently changed DNS records haven't propagated
- **Certificate rotation**: New cert deployed but some nodes still serve old cert
- **Deployment in progress**: Dependency is mid-deploy, some instances are new version, some old
- **Region failover**: Dependency failed over to secondary region with higher latency

---

## 2. Circuit Breaker Patterns

### When to Use
- A dependency can become slow or unavailable and repeated calls would consume scarce caller
  resources or impede recovery
- The caller has a useful fast-fail or degraded behavior while the dependency is unhealthy
- Failure classification and sampling volume are sufficient to distinguish dependency health
  from isolated caller errors

A circuit breaker is not automatically useful for every remote call. Do not add one when it
would merely duplicate platform behavior, mask actionable errors, or create more state than the
operating team can safely tune and observe.

### Implementation Checklist
- [ ] Three states: CLOSED (normal), OPEN (failing, fast-fail), HALF-OPEN (testing recovery)
- [ ] Failure threshold derived from request volume, tolerated error rate, and user impact
- [ ] Recovery interval derived from dependency recovery behavior and caller SLO
- [ ] Bounded probe concurrency and success criteria in HALF-OPEN state
- [ ] Metric emission on state transitions (critical for dashboards)
- [ ] Breakers scoped so one failing dependency/operation does not block unrelated work
- [ ] Caller explicitly handles the open-circuit result

Numeric breaker thresholds shown in examples are illustrative starting points only. Validate them
against production traffic and failure distributions before treating them as policy.

### Common Mistakes
- Setting the failure threshold so high that the circuit never opens, or so low that normal noise opens it
- Setting recovery intervals so short that the circuit flaps open/closed rapidly
- Opening dependency-wide state from one caller's exhausted retry loop instead of aggregated health evidence
- Using a single global circuit breaker for unrelated dependencies
- Not emitting metrics on circuit state changes
- Forgetting to handle the "circuit is open" case in the caller

---

## 3. Fallback Strategies

Choose the smallest fallback that is safe for the business operation:

1. **Cached value**: Serve the last known good response when bounded staleness is acceptable
2. **Degraded response**: Return partial data with an explicit incompleteness indicator
3. **Default value**: Return a safe static default only when business semantics allow it
4. **Queue for later**: Accept and durably defer work when acknowledgement semantics are clear
5. **Graceful error**: Return a clear, actionable error to the user or caller
6. **Feature disablement**: Disable the affected feature when that reduces net risk

### Fallback Anti-Patterns
- Falling back to a dependency that shares the same failure domain
- Falling back to a cache without checking whether the value is valid for the operation
- Returning a default value for a financial or access-control decision
- Silently serving stale or incomplete data
- Acknowledging queued work before it is durably accepted or without a reconciliation path

---

## 4. Timeout Strategy Guide

### Bound the Whole Remote Operation

Every remote operation needs a finite end-to-end deadline. Add protocol-appropriate phase limits
where the client exposes them, which may include:

- connection-pool acquisition
- DNS resolution
- TCP connect and TLS handshake
- request write
- time to first byte
- response read or stream idle time
- total operation time, including retries and backoff

A streaming operation may need a generous total lifetime and a bounded **idle** timeout rather
than a short fixed read timeout. Database work may need both client cancellation and a
server-side statement timeout.

### Timeout Sizing Rules
- Derive the total dependency budget from the caller's remaining deadline and leave explicit
  headroom for local processing, response serialization, and cancellation.
- Use observed latency distributions, dependency SLOs, and business impact to size phase limits.
- Include all attempts and backoff in the end-to-end budget.
- Use different budgets for interactive, batch, and streaming paths when their objectives differ.
- Treat library defaults as evidence to inspect, not as automatically safe or unsafe.

Do not prescribe a numeric timeout without stating the measurement, objective, provider contract,
or assumption used to derive it. Values in examples are illustrative, not universal defaults.

### Timeout Anti-Patterns
- No finite deadline on an operation that can block indefinitely
- A downstream budget greater than the caller's remaining deadline
- Resetting the full timeout at every service hop
- Configuring only one phase while another can wait indefinitely
- Reusing one timeout for dependencies with materially different latency behavior
- Launching a retry when the remaining deadline cannot accommodate the attempt and backoff

---

## 5. Retry Strategy Guide

### Retry Decision Process

Before retrying, establish all of the following:

1. **Repeat safety** — Is the operation naturally idempotent, protected by a stable
   operation-level idempotency key, or safely reconcilable after an ambiguous outcome?
2. **Failure classification** — Does the protocol/provider contract identify this failure as
   transient? A status family alone is not enough.
3. **Remaining budget** — Can another attempt and its backoff finish inside the end-to-end deadline?
4. **Amplification control** — Are aggregate retries bounded across SDK, proxy, service, queue,
   and client layers?

Conceptual decision guide:

```text
Can repeating the operation be proven safe?
├─ NO → Do not automatically retry. Fail, reconcile, or make the operation idempotent first.
└─ YES → Is this specific failure transient according to the protocol/provider contract?
   ├─ Validation/auth/not-found/unsupported-operation errors → Do not retry.
   ├─ 429 or 503 with Retry-After → Honor Retry-After only within the retry/deadline budget.
   ├─ Selected 502/503/504 or connection failures → Retry may be safe with bounded backoff.
   ├─ Timeout/connection loss after request send → Outcome may be ambiguous; require
   │  idempotency or read-after-write reconciliation before repeating a mutation.
   └─ Other 5xx responses → Do not assume retryability; classify by operation and contract.
```

### Backoff Configuration
- Prefer provider-supplied retry guidance such as `Retry-After` when trustworthy and bounded.
- Otherwise use exponential backoff with jitter to avoid synchronized retry waves.
- Derive base delay, cap, and maximum attempts from the remaining deadline, recovery behavior,
  traffic volume, and user impact.
- Stop when the retry budget or deadline is exhausted; do not convert exhaustion from one caller
  into dependency-wide breaker state without aggregated evidence.

### Retry Budget
- Bound retries as a fraction of normal traffic or another explicit capacity budget.
- Count attempts across all layers, including client SDKs, proxies, service code, queues, and callers.
- Reserve capacity for first attempts so retries cannot starve healthy traffic.
- When the budget is exhausted, fast-fail, degrade, or durably queue work according to business semantics.

### Retry Placement and Amplification

Place retries at the layer that owns the operation's semantic idempotency, can classify the
failure, and can see the remaining end-to-end deadline. Avoid accidental nested retries.

If A calls B and B calls C, with up to three attempts at both A→B and B→C, one request can produce
up to nine C attempts. A separate client retry at the edge can multiply that to 27. Inventory and
bound the complete chain rather than reasoning about one library in isolation.

---

## 6. Dependency Health Checking

### Active Health Checks
- [ ] Each dependency has an appropriate health signal or synthetic check where useful
- [ ] Checks are lightweight and do not create a second outage under load
- [ ] Checks are isolated from production traffic where that improves diagnostic value
- [ ] Interval and timeout are derived from detection objectives, traffic, and check cost
- [ ] Check timeout is shorter than the interval and cannot accumulate unbounded work

### Passive Health Checks
- [ ] Track error rates and latency per dependency in real time
- [ ] Detect slow degradation, not just hard failures
- [ ] Distinguish dependency failure from caller connectivity or configuration failure

### Startup Dependencies
- [ ] Distinguish hard dependencies (cannot serve safely without) from soft dependencies
- [ ] Readiness reflects the service's ability to serve its promised traffic
- [ ] Liveness does not fail merely because an external dependency is unavailable

---

## 7. Dependency Change Management & Rollback Safety (Lens 8 Alignment)

For broader rollout and rollback patterns, see `references/checklist-change-management.md`.

Many dependency incidents happen during deploys, config changes, SDK upgrades, certificate rotation,
or traffic routing changes. Review dependency integrations for change safety, not just steady-state behavior.

### Deployment / Release Checklist
- [ ] Dependency client changes are backward compatible during mixed-version rollout
- [ ] New request/response fields are additive first (callers tolerate unknown fields)
- [ ] Timeouts, retry counts, and circuit thresholds are configurable (not code-only)
- [ ] Feature flag or kill switch exists for risky dependency behavior changes
- [ ] Traffic can be shifted gradually (canary / percentage rollout / single region first)
- [ ] Dependency endpoint/host changes support rollback (old endpoint still valid during rollback window)

### Contract Change Safety
- [ ] Caller tolerates missing optional fields and ignores unknown fields
- [ ] Enum parsing handles new enum values safely (does not crash or default-allow)
- [ ] Validation rejects dangerous schema drift loudly (with actionable errors)
- [ ] Version negotiation strategy is documented if using versioned APIs
- [ ] Serialization changes were tested against older/newer service versions

### Secrets / Certificates / Connectivity Changes
- [ ] Secret rotation supports overlap window (old + new key valid during transition)
- [ ] Certificate rotation is tested before expiry (trust store, hostname, TLS version)
- [ ] DNS/endpoint failover latency is considered in timeout budgets
- [ ] Connection pool refresh behavior after endpoint changes is understood

### Rollback Safety Questions
- [ ] If the deployment is rolled back, can older code still parse new dependency responses?
- [ ] If config is rolled back, are in-flight retries safe?
- [ ] Are idempotency keys stable across deploy/restart boundaries?
- [ ] Is there a runbook for dependency-specific rollback/disable steps?

### Dependency Change Anti-Patterns
- Lockstep deployment requirement across multiple services without compatibility window
- SDK upgrade + retry/timeout policy changes + endpoint migration in one release
- No feature flag for new dependency code path on a critical endpoint
- Certificate rotation performed without synthetic checks and alerting
- "Just roll back" plan when the dependency contract is not backward compatible

---

## 8. Validation & Monitoring Add-Ons (Lens 8 + Required Finding Template Alignment)

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

Use these to strengthen recommendations in reviews. For P0/P1 findings, include at least one validation step and one monitoring item.

### Validation: Dependency Failure Drills
- [ ] Simulate connect, read, and total-deadline failures plus 429, selected transient 5xx,
  malformed response, and ambiguous post-send timeout
- [ ] Verify circuit breaker opens and recovers from aggregated health evidence
- [ ] Verify retry behavior uses bounded backoff/jitter and respects the total deadline
- [ ] Verify mutating operations are idempotent or reconcilable across retries and restarts
- [ ] Chaos test dependency outage and confirm the intended fail/degrade/queue behavior
- [ ] Mixed-version test for dependency client upgrade / contract change
- [ ] Rollback rehearsal when config/SDK/endpoint changes are part of the release

### Monitoring: Dependency Signals to Add / Check
- [ ] Per-dependency rate, error rate, latency distribution, and deadline-exceeded count
- [ ] Error classification by reason (phase timeout, 429, specific 5xx, parse error, auth)
- [ ] Circuit breaker state transitions, probe results, and open duration
- [ ] Retry attempts, amplification ratio, budget consumption, and retry-exhausted counts
- [ ] Fallback usage rate (cache fallback, degraded responses, queued work)
- [ ] Dependency-specific saturation signals (connection pool in-use, queue depth)
- [ ] Rollout dashboard overlays (deploy markers, config changes, certificate rotation events)

### Finding Snippet Template (Dependency)
```markdown
[DEPENDENCY]
Finding: <specific issue>
Evidence: <call path / code / config>
Why it matters: <blast radius, user impact, incident risk>
Recommendation: <deadline/retry/circuit/fallback/config/compatibility fix>
Validation: <failure injection or test plan>
Monitoring: <metrics/alerts/dashboard checks>
Priority: <P0/P1/P2/P3>
```
