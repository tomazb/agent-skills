# Security & Abuse as Reliability Patterns (Lens 10 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-dependency.md` — dependency-specific timeout/retry/circuit patterns
> - `references/checklist-observability.md` — telemetry and alerting implementation patterns

## Table of Contents
1. AuthN/AuthZ Failure Modes
2. Abuse and Adversarial Load Paths
3. Secure Degradation and Safety Controls
4. Credential and Secret Abuse Resilience
5. Multi-Tenant Isolation Under Attack
6. Incident Response Readiness
7. Validation & Monitoring Add-Ons
8. Finding Snippet Templates

---

## 1. AuthN/AuthZ Failure Modes

Security failures often surface as reliability incidents with a larger blast radius.

### Auth Failure Checklist
- [ ] Authentication failures default to deny, not allow
- [ ] Authorization failures default to deny, not allow
- [ ] Cache/IdP/session lookup errors do not bypass access controls
- [ ] Unknown role/permission values are treated as untrusted
- [ ] Permission checks are colocated with mutating actions (no client-only enforcement)
- [ ] Service-to-service auth failures are observable and classified clearly

### High-Risk Anti-Patterns
- Auth cache miss fallback of "allow"
- "Temporary bypass" flags that are easy to leave enabled
- Silent auth failures that return partial success without audit signals

---

## 2. Abuse and Adversarial Load Paths

Treat abuse handling as capacity and availability engineering.

### Abuse Path Checklist
- [ ] Public endpoints enforce per-actor limits (user/key/token)
- [ ] Global safety limits exist to protect shared infrastructure
- [ ] Limits are resistant to bypass (IP rotation, spoofed headers, user-agent churn)
- [ ] Expensive operations require stricter admission control
- [ ] Asymmetric operations (cheap request, expensive backend work) are guarded
- [ ] Bot traffic detection and challenge strategy are defined

### Abuse Scenarios to Model
- Credential stuffing against login or token mint endpoints
- High-cardinality query abuse causing cache/database stress
- Low-and-slow abuse that avoids naive rate thresholds
- Bursty attack traffic saturating downstream dependencies

---

## 3. Secure Degradation and Safety Controls

When protections degrade, the system must stay safe and predictable.

### Degradation Checklist
- [ ] Fail-secure defaults for privileged or financial operations
- [ ] Degraded modes are explicit (read-only, queued processing, temporary feature disablement)
- [ ] Kill switch exists for high-risk endpoints/paths
- [ ] Circuit breakers and throttling are coordinated (avoid defeating each other)
- [ ] Feature flags controlling security behavior are audited and access-restricted
- [ ] Safe error responses avoid information leaks while preserving operator context

---

## 4. Credential and Secret Abuse Resilience

Credential incidents quickly become availability incidents if rotation/revocation is brittle.

### Credential Safety Checklist
- [ ] Secret scopes follow least privilege
- [ ] Rotation supports overlap windows (old + new during cutover)
- [ ] Revocation runbook exists and is tested
- [ ] Service behavior during secret fetch failures is defined
- [ ] Secret/API key usage is attributable (who/what/where)
- [ ] Suspicious credential usage triggers alerting and protective actions

---

## 5. Multi-Tenant Isolation Under Attack

One abusive tenant should not degrade all tenants.

### Isolation Checklist
- [ ] Per-tenant quotas and concurrency caps are enforced server-side
- [ ] Noisy-neighbor controls prevent shared pool starvation
- [ ] Critical background jobs are partitioned or prioritized by tenant class
- [ ] Fair-queueing or weighted scheduling strategy is documented
- [ ] Tenant-level kill switch/suspension workflow exists

### Severity Guidance
- Shared-resource starvation with no tenant isolation: usually **P1-HIGH**
- Privilege bypass or auth fail-open on sensitive mutation: typically **P0-CRITICAL**

---

## 6. Incident Response Readiness

### Response Checklist
- [ ] Security-abuse alerts route to clear owners (on-call + security)
- [ ] Playbooks include immediate containment actions and rollback strategy
- [ ] Decision matrix exists for block/challenge/degrade responses
- [ ] Post-incident review captures reliability and abuse-control gaps

---

## 7. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Security/Abuse-Focused)
- [ ] Auth failure injection: IdP/cache failures do not fail open
- [ ] Rate-limit bypass tests (rotating identities/IPs, mixed endpoints)
- [ ] Credential leak simulation and revocation drill
- [ ] Tenant noisy-neighbor simulation under load
- [ ] Kill-switch rehearsal for high-risk endpoint

### Monitoring Ideas (Security/Abuse-Focused)
- [ ] Auth success/failure and deny reasons by endpoint
- [ ] Rate-limit trigger counts and bypass suspicion indicators
- [ ] Challenge/block action rates with false-positive tracking
- [ ] Per-tenant saturation and isolation breach signals
- [ ] Incident response timing (detect, contain, recover)

---

## 8. Finding Snippet Templates

### Finding Snippet Template (Security/Abuse Reliability)
```markdown
[SECURITY]
Finding: <auth/abuse reliability gap>
Evidence: <code path, policy, throttling behavior, telemetry>
Why it matters: <fail-open risk, shared-resource collapse, incident blast radius>
Recommendation: <fail-closed logic, layered throttles, isolation, kill switch>
Validation: <auth failure injection + abuse simulation + containment drill>
Monitoring: <auth/deny metrics, throttle triggers, tenant saturation, containment latency>
Priority: <P0/P1/P2/P3>
```
