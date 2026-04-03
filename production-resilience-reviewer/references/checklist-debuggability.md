# Debuggability Patterns (Lens 6 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-observability.md` — metrics/logging/alerting implementation details
> - `references/checklist-change-management.md` — rollout/rollback observability and runbook alignment

## Table of Contents
1. Exception Context Preservation
2. Structured Error Payloads
3. Correlation ID and Trace Propagation
4. Log Level Guidance and Consistency
5. Generic Catch-All and Exception Swallowing Detection
6. Validation & Monitoring Add-Ons
7. Finding Snippet Template

---

## 1. Exception Context Preservation

Error chains should preserve both technical root cause and business context.

### Checklist
- [ ] Exceptions are wrapped/rethrown with operation context (`what`, `which dependency`, `which input class`)
- [ ] Original exception/cause is preserved (stack trace and root type)
- [ ] Critical identifiers are included in sanitized form (order ID, tenant ID, request ID)
- [ ] Retry attempts/current state are included for transient failure paths
- [ ] Error messages distinguish user error vs dependency/system failure
- [ ] No broad \"failed\" messages without scope or actionability

### Anti-Patterns
- Re-throwing as generic exception and discarding original cause
- Logging exception only at outermost layer with no business context
- Catch-and-return-null behavior on critical paths

---

## 2. Structured Error Payloads

Machine-readable error contracts speed diagnosis and reduce guesswork.

### Checklist
- [ ] Error payloads include stable fields (`code`, `category`, `message`, `correlation_id`)
- [ ] Payload includes actionable metadata (`retryable`, `dependency`, `hint`)
- [ ] Internal details are separated from user-safe messages
- [ ] Error schema is documented and versioned where externally visible
- [ ] Similar failures map to consistent codes across services
- [ ] Sensitive fields are excluded or redacted by default

### Example Shape
```json
{
  "code": "DEPENDENCY_TIMEOUT",
  "category": "transient_dependency_failure",
  "message": "Payment provider timeout",
  "correlation_id": "req-123",
  "retryable": true,
  "dependency": "stripe",
  "hint": "Auto-retry scheduled; check provider status if persistent"
}
```

---

## 3. Correlation ID and Trace Propagation

A failure that cannot be traced across boundaries is expensive to debug.

### Checklist
- [ ] Correlation/request IDs are generated at ingress if absent
- [ ] IDs are propagated across sync and async boundaries
- [ ] Trace/span context is forwarded to downstream services
- [ ] Logs, metrics, and error payloads include the same primary request identifier
- [ ] Background tasks maintain parent linkage where operationally useful
- [ ] ID format and header conventions are standardized

### Failure Signals
- Dependency error logs cannot be joined to caller logs
- Retry logs lack a stable request identifier
- Incident timeline reconstruction requires guesswork

---

## 4. Log Level Guidance and Consistency

Inconsistent severity levels hide real incidents or create alert fatigue.

### Baseline Guide
- `ERROR`: request/operation failed and user/system impact exists
- `WARN`: degraded but recovered/fallback path, or suspicious condition needing follow-up
- `INFO`: state transitions and major business events
- `DEBUG`: high-volume diagnostic detail (off by default in production)

### Checklist
- [ ] Same failure type logs at same level across services
- [ ] Retries do not emit `ERROR` on every transient attempt (final failure should escalate)
- [ ] Log level transitions are deliberate during rollout/debug windows
- [ ] Alerting maps to error classes, not raw log volume only

---

## 5. Generic Catch-All and Exception Swallowing Detection

Catch-all logic is a common source of hidden production incidents.

### Checklist
- [ ] Generic catch blocks either rethrow with context or emit structured actionable errors
- [ ] Empty catch blocks are prohibited on critical paths
- [ ] Catch-all handlers include classification logic by exception type/cause
- [ ] Fallback behavior under catch-all is explicit and observable
- [ ] Panic/fatal-level exceptions are not silently converted to success responses
- [ ] Code review checks include grep for risky patterns (`catch (Exception)`, `except Exception`, broad panic recovery)

### Severity Guidance
- Swallowed exception with data-loss or financial risk: often **P0-CRITICAL**
- Generic catch-all with ambiguous logging on user path: usually **P1-HIGH**

---

## 6. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Debuggability-Focused)
- [ ] Inject representative failures and verify context-rich error chains
- [ ] Verify correlation IDs persist across service boundaries and async workflows
- [ ] Snapshot-test external error payload schema for consistency
- [ ] Run grep/lint checks for generic catch-all and swallow patterns
- [ ] Runbook drill: engineer can diagnose seeded failure within target time

### Monitoring Ideas (Debuggability-Focused)
- [ ] Error count by class/code/category and dependency
- [ ] Unclassified/unknown error ratio alerts
- [ ] Correlation ID missing-rate in logs/errors
- [ ] Retry attempt distributions and terminal failure signals
- [ ] Structured log parsing failure rate (schema drift indicator)

---

## 7. Finding Snippet Template

```markdown
[DEBUGGABILITY]
Finding: <missing context, poor classification, or tracing gap>
Evidence: <code/log examples, payload schema, missing IDs>
Why it matters: <slower incident response, mis-triage, prolonged outage>
Recommendation: <context-preserving errors, structured payloads, ID propagation, log-level cleanup>
Validation: <failure injection + trace/log verification plan>
Monitoring: <error classification, missing-ID, and debuggability quality metrics>
Priority: <P0/P1/P2/P3>
```
