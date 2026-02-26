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

Every external dependency can fail in these ways. Check for handling of ALL of them:

### Connection-Level Failures
- **Connection refused**: Service is down or port is wrong
- **DNS resolution failure**: DNS server down, name doesn't exist, TTL cache expired
- **TLS handshake failure**: Certificate expired, CA not trusted, protocol mismatch
- **Connection timeout**: Service is unreachable (firewall, network partition)
- **Connection reset**: Service crashed mid-request, load balancer killed connection

### Request-Level Failures
- **Read timeout**: Service accepted connection but response is too slow
- **HTTP 4xx**: Client error (bad request, unauthorized, forbidden, not found, rate limited)
- **HTTP 5xx**: Server error (internal error, bad gateway, service unavailable, gateway timeout)
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
- Any external HTTP/gRPC call that could become slow or unresponsive
- Database queries that could hang under load
- Any call where continued retrying would make things worse

### Implementation Checklist
- [ ] Three states: CLOSED (normal), OPEN (failing, fast-fail), HALF-OPEN (testing recovery)
- [ ] Configurable failure threshold (e.g., 5 failures in 60 seconds)
- [ ] Configurable recovery timeout (e.g., try again after 30 seconds)
- [ ] Success threshold in HALF-OPEN state before returning to CLOSED
- [ ] Metric emission on state transitions (critical for dashboards)
- [ ] Separate circuit breakers per dependency (not one global breaker)
- [ ] Consider: separate breakers per endpoint within a dependency if failure rates differ

### Common Mistakes
- Setting the failure threshold too high (circuit never opens)
- Setting recovery timeout too low (circuit flaps open/closed rapidly)
- Using a single global circuit breaker for all dependencies
- Not emitting metrics on circuit state changes
- Forgetting to handle the "circuit is open" case in the caller (throwing a generic error instead of a specific "dependency unavailable" error)

---

## 3. Fallback Strategies

Ranked by preference (use the highest applicable):

1. **Cached value**: Serve the last known good response (with staleness indicator to caller)
2. **Degraded response**: Return partial data with a flag indicating incompleteness
3. **Default value**: Return a safe, static default (only if the business logic allows it)
4. **Queue for later**: Accept the request, queue it, process when dependency recovers
5. **Graceful error**: Return a clear, actionable error to the user
6. **Feature flag disable**: Automatically disable the feature that depends on the failed service

### Fallback Anti-Patterns
- Falling back to a different dependency that has the same upstream failure (correlated failure)
- Falling back to a cache without checking if the cached data is still valid for the operation
- Returning a default value for a financial or access-control decision (dangerous: "default allow" on auth failure)
- Silently serving stale data without any indicator to the user or caller

---

## 4. Timeout Strategy Guide

### Every network call needs TWO timeouts:
1. **Connect timeout**: How long to wait for TCP connection establishment (typically 1-5s)
2. **Read/response timeout**: How long to wait for the response after connection is established

### Timeout Sizing Rules
- **User-facing synchronous paths**: Total timeout < caller's timeout. If your API has a 30s timeout, your downstream calls should sum to < 25s (leave headroom for processing).
- **Background/async jobs**: Can be more generous (30s-120s) but still must be finite.
- **Database queries**: Typically 5-15s for OLTP. If a query takes longer, it's likely a problem.
- **Statement-level timeouts**: Set query-level timeouts in the database itself, not just connection-level.

### Timeout Anti-Patterns
- No timeout at all (the call hangs forever, holding resources)
- Setting connect timeout but not read timeout
- Setting timeout higher than the caller's timeout (guaranteed caller timeout)
- Using the same timeout for all dependencies regardless of their expected latency
- Not accounting for retries in the timeout budget (3 retries × 10s timeout = 30s worst case)

---

## 5. Retry Strategy Guide

### The Retry Decision Tree
```
Is the operation idempotent?
├─ NO → Do NOT retry (or make it idempotent first with idempotency key)
└─ YES → Is the error retryable?
   ├─ 4xx (except 429) → Do NOT retry (client error, retrying won't help)
   ├─ 429 → Retry with Retry-After header value (or exponential backoff)
   ├─ 5xx → Retry with backoff
   ├─ Timeout → Retry with backoff (but verify idempotency!)
   └─ Connection error → Retry with backoff
```

### Backoff Configuration
- Base delay: 100ms-1s depending on the operation
- Multiplier: 2x (exponential)
- Jitter: ALWAYS add random jitter (±25-50%) to prevent thundering herd
- Max delay: Cap at 30-60s
- Max retries: 2-3 for user-facing, 5-10 for background jobs

### Retry Budget
- Global retry budget: Limit total retries across all callers to X% of normal traffic
- Per-caller retry budget: No more than 3 retries per request per dependency
- When retry budget is exhausted: fast-fail (open circuit breaker)

### Retry Amplification
If your call chain is A → B → C, and each layer retries 3x:
- 1 failure at C = 3 attempts from B = 9 attempts from A
- Solution: Only retry at one layer (typically the closest to the failure), or use a global retry budget

---

## 6. Dependency Health Checking

### Active Health Checks
- [ ] Each dependency has a health check endpoint or mechanism
- [ ] Health checks are lightweight (don't hit the database for a DB health check)
- [ ] Health checks run on a separate circuit from production traffic
- [ ] Health check interval is appropriate (5-30s typically)
- [ ] Health check timeout is shorter than the check interval

### Passive Health Checks
- [ ] Track error rates per dependency in real-time
- [ ] Detect slow degradation (p99 latency creeping up) not just hard failures
- [ ] Distinguish between "dependency is down" and "our connection to dependency is broken"

### Startup Dependencies
- [ ] Distinguish between hard dependencies (can't start without) and soft dependencies (can start, will degrade)
- [ ] Readiness probe only passes when hard dependencies are verified
- [ ] Liveness probe does NOT check external dependencies (don't kill your pod because Stripe is down)


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
- [ ] Traffic can be shifted gradually (canary / % rollout / single region first)
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
- [ ] Simulate connect timeout, read timeout, 429, 5xx, malformed response
- [ ] Verify circuit breaker opens and recovers correctly (including metrics)
- [ ] Verify retry behavior uses backoff + jitter and respects max attempts
- [ ] Verify mutating operations are idempotent under retries and process restarts
- [ ] Chaos test dependency outage (or use fault injection proxy) and confirm graceful degradation
- [ ] Mixed-version test for dependency client upgrade / contract change
- [ ] Rollback rehearsal when config/SDK/endpoint changes are part of the release

### Monitoring: Dependency Signals to Add / Check
- [ ] Per-dependency rate, error rate, latency (p50/p95/p99), timeout count
- [ ] Error classification by reason (timeout, 429, 5xx, parse error, auth)
- [ ] Circuit breaker state transitions and open duration
- [ ] Retry attempts and retry-exhausted counts
- [ ] Fallback usage rate (cache hits used as fallback, degraded-mode responses)
- [ ] Dependency-specific saturation signals (connection pool in-use, queue depth)
- [ ] Rollout dashboard overlays (deploy markers, config changes, certificate rotation events)

### Finding Snippet Template (Dependency)
```markdown
[DEPENDENCY]
Finding: <specific issue>
Evidence: <call path / code / config>
Why it matters: <blast radius, user impact, incident risk>
Recommendation: <timeout/retry/circuit/fallback/config/compatibility fix>
Validation: <failure injection or test plan>
Monitoring: <metrics/alerts/dashboard checks>
Priority: <P0/P1/P2/P3>
```
