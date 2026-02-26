# Severity Calibration Matrix & Adjustment Rules

Use this reference to calibrate findings based on **impact × likelihood × blast radius × detectability**.
This file expands the summary in `SKILL.md`.

## Step 1: Assign a Baseline Severity from Impact

- **P0-CRITICAL**: Data loss/corruption, financial errors, security breach, unsafe access,
  irreversible side effects, or outage of a critical path
- **P1-HIGH**: Major degradation, high incident risk under load, slow recovery, or poor
  operator visibility on an important path
- **P2-MEDIUM**: Noticeable resilience debt, preventable toil, or best-practice gap with
  moderate risk
- **P3-LOW**: Hardening/polish/nice-to-have improvements

## Step 2: Adjust Using Context (Upgrade or Downgrade)

| Context Factor | Lower Severity Tendency | Higher Severity Tendency |
|---|---|---|
| User impact | Internal-only admin/reporting | Customer-facing critical workflow |
| Operation type | Read-only / cacheable | Mutating / irreversible side effects |
| Data sensitivity | Non-critical metadata | Money, auth, permissions, compliance data |
| Blast radius | Single request/user | Cross-tenant/system-wide/cascading |
| Frequency | Rare manual path | Hot path / every request / batch at scale |
| Detectability | Immediate loud failure + alerts | Silent failure / delayed discovery |
| Recoverability | Easy retry / replay / rollback | Hard to reconcile or irreversible |
| Change scope | Feature-flagged canary | Full rollout, no kill switch |
| Runtime isolation | Sandboxed / rate-limited | Shared pool / contention can cascade |

## Severity Adjustment Rules (Practical Defaults)

- **Raise by 1 level** if **any** of the following are true:
  - Silent corruption or silent failure
  - Money/auth/access-control impact
  - Hot path + likely under real traffic
  - No rollback / no feature flag for risky rollout
  - Poor observability makes incident triage slow
- **Raise by 2 levels** if multiple high-risk context factors combine
  (e.g., mutating + hot path + silent failure)
- **Lower by 1 level** only when blast radius is demonstrably small **and**
  failure is loud/easy to recover
- Never lower below:
  - **P0** for financial inconsistency, data corruption, security/permission bypass,
    or irreversible destructive migration risk
  - **P1** for missing timeouts/retries/error handling on a customer-facing critical
    dependency unless strong mitigating context exists

## Calibration Notes

- Treat code smells (missing timeout, broad catch, no retry budget) as **signals**, not
  automatic severity.
- A tiny internal script and a checkout/payment path should not receive the same severity
  for the same implementation gap.
- If you are unsure, state assumptions explicitly (traffic, criticality, user impact,
  deployment model) and calibrate based on those assumptions.
