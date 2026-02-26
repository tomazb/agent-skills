# Fault Domains & Disaster Recovery Patterns (Lens 9 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-change-management.md` — rollout/rollback execution patterns
> - `references/checklist-data.md` — data consistency and replay/reconciliation hazards

## Table of Contents
1. Fault Domain Mapping
2. RPO/RTO and Service Tiering
3. Backup, Restore, and Replay Safety
4. AZ/Region Failover Patterns
5. Control-Plane Dependency Risk
6. Runbooks, Ownership, and Drill Discipline
7. Validation & Monitoring Add-Ons
8. Finding Snippet Templates

---

## 1. Fault Domain Mapping

If fault domains are not explicit, failover plans are usually fiction.

### Fault Domain Checklist
- [ ] Dependencies are labeled as zonal, regional, global, or control-plane
- [ ] Single points of failure are called out (network, database, secrets, DNS, queue, deploy system)
- [ ] Cross-zone and cross-region data/control paths are documented
- [ ] Blast radius is defined for each domain loss scenario
- [ ] Degraded-mode behavior is specified for each major dependency outage

### Common Blind Spots
- "Multi-AZ app" using a single-AZ stateful store
- Regional data plane with global control-plane dependency that can block recovery
- DNS or cert-management dependency treated as always available
- Shared queue or cache cluster becoming an implicit global SPOF

---

## 2. RPO/RTO and Service Tiering

RTO/RPO must be explicit or incident recovery decisions become inconsistent.

### RPO/RTO Checklist
- [ ] Service tier is defined (critical revenue/auth path vs non-critical)
- [ ] **RPO** target is documented and approved
- [ ] **RTO** target is documented and approved
- [ ] RPO/RTO assumptions are realistic for current architecture and tooling
- [ ] Error budget and incident policy align with declared recovery objectives
- [ ] Customer-facing expectations are reflected in SLAs/SLOs/runbooks

### Severity Guidance
- Undefined RPO/RTO on critical path: usually **P1-HIGH**
- Declared RPO/RTO that cannot be achieved in drills: often **P1-HIGH** (or **P0** if safety/financial)

---

## 3. Backup, Restore, and Replay Safety

Backups are only useful if restore and replay are proven under realistic conditions.

### Backup/Restore Checklist
- [ ] Backup coverage includes all critical state (not just primary DB)
- [ ] Backup frequency and retention satisfy RPO requirements
- [ ] Restore workflow is automated, version-aware, and documented
- [ ] Restore verification includes correctness checks, not only completion status
- [ ] Encryption keys and secret dependencies for restore are tested
- [ ] Restore can run with partial infrastructure impairment

### Replay/Reconciliation Checklist
- [ ] Event replay procedure exists for at-least-once systems
- [ ] Deduplication/idempotency logic is validated during replay
- [ ] Reconciliation tools exist for partial side effects (payments, inventory, billing)
- [ ] Replay guardrails prevent duplicate mutation storms
- [ ] Replay completion and mismatch metrics are defined

### Anti-Patterns
- Successful backup jobs with no restore drills
- Restore tested only for tiny datasets
- Replay script with no idempotency guarantees
- Recovery procedure requiring local operator tribal knowledge

---

## 4. AZ/Region Failover Patterns

Failover is an operational system, not a theoretical architecture diagram.

### Failover Checklist
- [ ] Traffic steering supports zone/region evacuation
- [ ] Failover trigger criteria are explicit and observable
- [ ] Read/write behavior during failover is defined (read-only mode, queue-and-reconcile, full stop)
- [ ] Data replication lag is measured and factored into RPO decisions
- [ ] Failback procedure exists and avoids split-brain behavior
- [ ] Regional dependency bootstrapping is rehearsed (secrets, configs, credentials, endpoints)

### Failure Modes to Probe
- Control-plane healthy but data-plane partitioned
- Region isolated from upstream dependencies
- Partial AZ outage causing gray failures and request flapping
- Automated failover loops (oscillation) with no damping

---

## 5. Control-Plane Dependency Risk

Control-plane outages can block scale-out, rollbacks, and recovery actions.

### Control-Plane Checklist
- [ ] Recovery path does not require unavailable control-plane actions
- [ ] Last-known-good configs and artifacts are cacheable/offline-accessible
- [ ] Emergency override procedure exists when orchestration APIs are degraded
- [ ] Secret/certificate rotation process has outage-safe fallback windows
- [ ] Incident runbook identifies control-plane critical actions and alternatives

---

## 6. Runbooks, Ownership, and Drill Discipline

### Operational Readiness Checklist
- [ ] Primary and backup owners are defined for each DR action
- [ ] Runbooks include commands, prerequisites, rollback, and verification steps
- [ ] Drill cadence is scheduled (at least quarterly for critical paths)
- [ ] Drill findings feed backlog with owner + due date
- [ ] Recovery playbook can be executed by on-call without original implementer

### Drill Levels
- [ ] Tabletop drill (scenario walkthrough)
- [ ] Staging failover drill (technical execution)
- [ ] Production game day with scoped blast radius and clear abort criteria

---

## 7. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (DR-Focused)
- [ ] Region/AZ failover rehearsal with realistic traffic
- [ ] Backup restore drill using production-like volume
- [ ] Replay/reconciliation test after restore
- [ ] Simulate control-plane API unavailability during incident response
- [ ] Failback rehearsal after primary domain recovers

### Monitoring Ideas (DR-Focused)
- [ ] Replication lag and estimated RPO drift
- [ ] Restore/replay duration and success rates
- [ ] Failover trigger signals and action latency
- [ ] Error/latency/business KPI split by zone/region
- [ ] Runbook execution telemetry (step completion, manual interventions)

---

## 8. Finding Snippet Templates

### Finding Snippet Template (Disaster Recovery)
```markdown
[DR]
Finding: <fault-domain or recovery-path weakness>
Evidence: <architecture, runbook, restore/failover evidence>
Why it matters: <RPO/RTO miss risk, blast radius, recovery uncertainty>
Recommendation: <domain isolation, automation, tested failover/restore/replay plan>
Validation: <failover rehearsal + restore/replay test + failback test>
Monitoring: <replication lag, failover signals, recovery duration, correctness guardrails>
Priority: <P0/P1/P2/P3>
```
