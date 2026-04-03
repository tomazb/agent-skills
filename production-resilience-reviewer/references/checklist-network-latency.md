# Network & Latency Patterns (Lens 3 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-dependency.md` — dependency failure, timeout, and retry guidance
> - `references/checklist-load-concurrency.md` — load concurrency interactions with slow dependencies

## Table of Contents
1. Timeout Layering (Connect vs Read vs Total)
2. Deadline Propagation
3. DNS Resolution Failure Modes
4. TLS Handshake Delay and Failure Patterns
5. Geo-Latency and Cross-Region Considerations
6. Validation & Monitoring Add-Ons
7. Finding Snippet Template

---

## 1. Timeout Layering (Connect vs Read vs Total)

A single timeout is rarely enough. Apply layered budgets.

### Checklist
- [ ] Connect timeout is explicitly configured (short, typically 0.5-3s)
- [ ] Read/response timeout is explicitly configured per dependency behavior
- [ ] Total request budget is bounded and less than caller timeout budget
- [ ] Retries fit inside total budget (including backoff time)
- [ ] Timeouts differ by path criticality (interactive vs batch/background)
- [ ] No dependency call relies on implicit library defaults

### Common Misconfigurations
- Only read timeout set; connect can hang
- Sum of retry budgets exceeds user-facing SLA
- Dependency timeout higher than upstream request timeout

---

## 2. Deadline Propagation

Without propagated deadlines, each layer behaves as if it has infinite time.

### Checklist
- [ ] Incoming request deadline is captured at edge/service boundary
- [ ] Downstream calls receive remaining budget, not static timeout defaults
- [ ] Worker/queue consumers propagate deadlines/cancellation contexts where possible
- [ ] Circuit breakers and retries respect remaining deadline budget
- [ ] Expired deadlines short-circuit quickly with explicit classification
- [ ] Logs/metrics include remaining budget on timeout paths

### Anti-Patterns
- Resetting timeout to full value at each service hop
- Retries launched after deadline already expired
- Background tasks detached from cancellation context on request path

---

## 3. DNS Resolution Failure Modes

DNS issues often look like generic network failures unless classified properly.

### Checklist
- [ ] DNS lookup errors are classified distinctly (NXDOMAIN, timeout, SERVFAIL)
- [ ] DNS resolver timeout is bounded
- [ ] Client stack caches/stabilizes resolver failures appropriately
- [ ] Critical dependencies support fallback resolvers or failover strategy where appropriate
- [ ] Service discovery TTL and refresh behavior are understood
- [ ] Runbooks include DNS cache flush/reload and resolver health checks

### Signals
- Spikes in lookup latency preceding request timeout spikes
- Intermittent host resolution failures during deploys/traffic shifts
- Region-specific DNS anomalies with otherwise healthy dependencies

---

## 4. TLS Handshake Delay and Failure Patterns

Handshake cost and cert path problems can dominate latency.

### Checklist
- [ ] TLS handshake timeout is bounded (if configurable in client/runtime)
- [ ] Certificate chains and trust stores are current
- [ ] Session reuse/keepalive is enabled where safe to reduce repeated handshakes
- [ ] SNI/hostname verification configuration is correct and explicit
- [ ] Cert rotation and trust-store update process is tested
- [ ] Handshake failures are surfaced separately from read/connect timeouts

### Signals
- High connect+TLS latency with low server processing time
- Error spikes during cert rotation windows
- Latency regressions after cipher/protocol policy changes

---

## 5. Geo-Latency and Cross-Region Considerations

Distance and cross-region dependency calls can consume the full latency budget.

### Checklist
- [ ] Critical request paths avoid unnecessary cross-region hops
- [ ] Region affinity/locality is applied for latency-sensitive reads/writes where possible
- [ ] Timeout budgets account for worst-case region-to-region RTT
- [ ] Fallback region behavior is defined for regional degradation
- [ ] Data consistency trade-offs are explicit for geo-distributed paths
- [ ] User impact is segmented by geography in observability

### Trade-Off Guidance
- Synchronous cross-region calls on user path: usually high-risk unless strictly required.
- Async replication/reconciliation often safer than synchronous remote commits for interactive workflows.

---

## 6. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Network/Latency-Focused)
- [ ] Inject connect delays/timeouts and verify graceful timeout classification
- [ ] Inject read latency (p95/p99 slowdowns) and verify deadline-aware behavior
- [ ] DNS failure injection (timeout/NXDOMAIN) for critical dependencies
- [ ] TLS failure drills (expired cert, trust mismatch, handshake timeout)
- [ ] Cross-region failover simulation for primary dependency path

### Monitoring Ideas (Network/Latency-Focused)
- [ ] Connect latency, TLS handshake latency, read latency by dependency
- [ ] Timeout counters by type (connect/read/total/deadline exceeded)
- [ ] DNS lookup latency and resolver error counts
- [ ] Retries and circuit state transitions during dependency slowdown events
- [ ] Geo-segmented latency/error views by region and client cohort

---

## 7. Finding Snippet Template

```markdown
[NETWORK]
Finding: <timeout/deadline/DNS/TLS/geo-latency risk>
Evidence: <client config, call chain, telemetry>
Why it matters: <cascade timeout risk, user latency/SLO impact, regional blast radius>
Recommendation: <layered timeout budgets, deadline propagation, DNS/TLS hardening, locality controls>
Validation: <latency/fault injection and failover test plan>
Monitoring: <connect/read/tls/dns/deadline metrics and alerts>
Priority: <P0/P1/P2/P3>
```
