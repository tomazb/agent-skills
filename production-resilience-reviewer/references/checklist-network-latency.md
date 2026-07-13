# Network & Latency Patterns (Lens 3 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-dependency.md` — dependency failure, timeout, and retry guidance
> - `references/checklist-load-concurrency.md` — load concurrency interactions with slow dependencies

## Table of Contents
1. Deadline and Phase-Limit Layering
2. Deadline Propagation
3. DNS Resolution Failure Modes
4. TLS Handshake Delay and Failure Patterns
5. Geo-Latency and Cross-Region Considerations
6. Validation & Monitoring Add-Ons
7. Finding Snippet Template

---

## 1. Deadline and Phase-Limit Layering

Every remote operation needs a bounded end-to-end deadline. Add protocol-appropriate phase limits
where the client exposes them.

### Checklist
- [ ] Total operation deadline is bounded and fits inside the caller's remaining budget
- [ ] Connection-pool acquisition, DNS, connect, TLS, write, first-byte, read, and idle limits
  are considered where applicable
- [ ] Streaming operations use an appropriate idle limit rather than an arbitrary short total read limit
- [ ] Retries and backoff fit inside the same total deadline
- [ ] Budgets differ when interactive, batch, and streaming objectives materially differ
- [ ] Library defaults are inspected and justified rather than assumed safe
- [ ] Database work has server-side statement/cancellation controls where needed

### Sizing Guidance
- Derive limits from observed latency distributions, dependency behavior, caller SLO, and business impact.
- Leave explicit headroom for local work, response serialization, and cancellation propagation.
- Do not prescribe a numeric timeout without naming the objective, measurement, provider constraint,
  or assumption used to derive it. Example values are starting points only.

### Common Misconfigurations
- No finite total deadline
- One phase can wait indefinitely even though another phase is bounded
- Sum of attempts and backoff exceeds the caller deadline
- A downstream timeout is greater than the remaining upstream budget
- A streaming response is killed by a timeout designed for short request/response calls

---

## 2. Deadline Propagation

Without propagated deadlines, each layer behaves as if it has a fresh, independent time budget.

### Checklist
- [ ] Incoming request deadline is captured at the edge/service boundary
- [ ] Downstream calls receive the remaining budget, not a reset static timeout
- [ ] Worker/queue consumers propagate deadlines or explicit expiry semantics where appropriate
- [ ] Circuit breakers and retries respect remaining budget
- [ ] Expired deadlines short-circuit with explicit classification
- [ ] Logs/traces capture the phase and remaining budget on deadline paths without creating
  high-cardinality metric labels
- [ ] Cancellation reaches in-flight dependency calls and local work

### Anti-Patterns
- Resetting the full timeout at each service hop
- Retrying after the deadline is already expired
- Detaching request-path work from cancellation without explicit durable ownership
- Returning a timeout while the abandoned operation continues to mutate state

---

## 3. DNS Resolution Failure Modes

DNS issues often look like generic network failures unless classified properly.

### Checklist
- [ ] DNS lookup errors are classified distinctly (NXDOMAIN, timeout, SERVFAIL)
- [ ] Resolver work is bounded by the operation deadline
- [ ] Client/runtime cache and negative-cache behavior are understood
- [ ] Critical dependencies have a tested resolver/failover strategy where the risk justifies it
- [ ] Service-discovery TTL and endpoint refresh behavior are understood
- [ ] Runbooks include resolver health, cache, and endpoint-refresh checks

### Signals
- Lookup-latency spikes preceding request deadline failures
- Intermittent resolution failures during deploys or traffic shifts
- Region-specific DNS anomalies while the dependency itself remains healthy

---

## 4. TLS Handshake Delay and Failure Patterns

Handshake cost and certificate-path problems can dominate latency.

### Checklist
- [ ] TLS handshake work is bounded by the operation deadline
- [ ] Certificate chains and trust stores are current
- [ ] Session reuse/keepalive is enabled where safe to reduce repeated handshakes
- [ ] SNI/hostname verification configuration is correct and explicit
- [ ] Certificate rotation and trust-store update processes are tested
- [ ] Handshake failures are surfaced separately from DNS/connect/read failures

### Signals
- High connect+TLS latency with low server processing time
- Error spikes during certificate rotation windows
- Latency regressions after cipher/protocol policy changes

---

## 5. Geo-Latency and Cross-Region Considerations

Distance and cross-region dependency calls can consume the full latency budget.

### Checklist
- [ ] Critical request paths avoid unnecessary cross-region hops
- [ ] Region affinity/locality is applied for latency-sensitive reads/writes where possible
- [ ] Budgets account for measured or modeled worst-case region-to-region latency
- [ ] Fallback-region behavior is defined for regional degradation
- [ ] Data consistency trade-offs are explicit for geo-distributed paths
- [ ] User impact is segmented by geography with bounded telemetry dimensions

### Trade-Off Guidance
- Synchronous cross-region calls on an interactive path require a concrete consistency or isolation need.
- Async replication/reconciliation may be safer than synchronous remote commits when the business
  operation can tolerate delayed convergence.
- Do not recommend multi-region machinery unless the RPO/RTO and operating model justify its added complexity.

---

## 6. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Network/Latency-Focused)
- [ ] Inject pool-acquire, DNS, connect, TLS, write, first-byte, read, idle, and total-deadline failures as applicable
- [ ] Inject tail-latency slowdown and verify deadline-aware cancellation and recovery
- [ ] Test ambiguous post-send timeout behavior for mutating operations
- [ ] DNS failure injection (timeout/NXDOMAIN/SERVFAIL) for critical dependencies
- [ ] TLS rotation/failure drills (expired cert, trust mismatch, handshake delay)
- [ ] Cross-region failover simulation when the design claims regional recovery

### Monitoring Ideas (Network/Latency-Focused)
- [ ] Pool wait, DNS, connect, TLS, first-byte, read/idle, and total operation latency by dependency
- [ ] Deadline counters by phase and operation class
- [ ] DNS lookup latency and resolver error counts
- [ ] Cancellation latency and abandoned in-flight operation count where observable
- [ ] Retries and circuit state transitions during dependency slowdown events
- [ ] Geo-segmented latency/error views using bounded region/cohort dimensions

---

## 7. Finding Snippet Template

```markdown
[NETWORK]
Finding: <deadline/phase/DNS/TLS/geo-latency risk>
Evidence: <client config, call chain, telemetry>
Why it matters: <cascade timeout risk, user latency/SLO impact, regional blast radius>
Recommendation: <bounded total deadline, phase limits, propagation, DNS/TLS hardening, locality controls>
Validation: <latency/fault injection and failover test plan>
Monitoring: <phase latency, deadline, DNS/TLS, cancellation, and geo signals>
Priority: <P0/P1/P2/P3>
```
