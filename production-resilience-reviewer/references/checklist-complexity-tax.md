# Checklist: Complexity Tax & Architecture Fit (Lens 12)

Deep-dive reference for evaluating whether an architecture matches its actual constraints.
Use this lens to challenge architecture-driven failure surface area with evidence, not taste.

Cross-references: `severity-calibration.md`, `validation-monitoring-patterns.md`

---

## 1. Evidence Before Judgment

Do not treat an architecture style as a finding by itself. Collect enough context to show
whether the choice is helping or hurting resilience, operability, cost, or failure modes.

- [ ] **Team size** — How many engineers build and operate the system?
- [ ] **Service count** — How many deployable units, queues, functions, agents, workflows,
  and platform components are in the path under review?
- [ ] **Ownership model** — Are services/modules owned end-to-end by stable teams, including
  on-call and incidents?
- [ ] **Deploy coupling** — How many repositories or services change for a typical feature,
  bug fix, or schema change?
- [ ] **Shared data ownership** — Which services own data independently, and which share
  tables, schemas, topics, or state machines?
- [ ] **Request path depth** — How many synchronous hops, async steps, or agent/tool calls
  does a critical user action traverse?
- [ ] **Traffic/cost profile** — Which components actually need independent scale, and which
  are expensive because of orchestration, transfer, or observability overhead?
- [ ] **Platform/SRE support** — Are paved paths, runbooks, cluster operations, observability,
  and incident response mature enough for the architecture?
- [ ] **Recent incident/on-call pain** — Which incidents, pages, or debugging delays were
  caused or amplified by the architecture?

File a finding only when the evidence shows a mismatch. Avoid "microservices bad" or
"Kubernetes overkill" claims without concrete impact.

---

## 2. Distribution Necessity

For each service or deployable boundary, look for at least one concrete justification.

- [ ] **Independent scaling proof** — Different CPU, memory, IO, latency, burst, or cost
  behavior that cannot be handled reasonably by scaling the parent application.
- [ ] **Team autonomy proof** — A team can ship, operate, and roll back the component without
  routine coordination with other teams.
- [ ] **Regulatory or blast-radius isolation proof** — Separation materially reduces
  compliance scope, tenant risk, or incident impact.
- [ ] **Technology divergence proof** — Different runtime, data store, hardware, or lifecycle
  is required and cannot coexist cleanly in the main application.
- [ ] **Reliability boundary proof** — Isolation prevents a specific failure mode from
  propagating, and the team can operate that boundary in incidents.

If none apply, recommend a smaller boundary: module, package, library, worker, or fewer
deployables with explicit internal ownership.

---

## 3. Distributed Monolith Signals

A distributed monolith pays distributed operational cost while retaining monolithic coupling.

- [ ] Multiple services share writable database tables or unversioned schemas.
- [ ] Coordinated deploys are routine for ordinary product changes.
- [ ] A feature regularly touches several repositories because boundaries do not match work.
- [ ] Test environments need the full fleet before a single service can be validated.
- [ ] Synchronous request chains are deep enough that tail latency or one dependency failure
  regularly affects the whole user action.
- [ ] Shared libraries force synchronized upgrades across many services.
- [ ] Ownership is nominal: one small team is effectively responsible for every service.

Severity depends on impact. It is usually **P1-HIGH** when these signals affect a critical
path, cause incident/debugging pain, or block independent rollback. It is usually
**P2-MEDIUM** when the mismatch is real but the blast radius is lower.

---

## 4. Event-Driven Sprawl

Async designs can improve decoupling, buffering, and recovery. They can also hide state and
make failures hard to diagnose.

- [ ] **Schema ownership** — Producers and consumers have versioned contracts and compatible
  rollout rules.
- [ ] **Replay behavior** — Reprocessing is idempotent, bounded, and observable.
- [ ] **Debug path** — Operators can trace one business event across topics, consumers,
  retries, DLQs, and compensating actions.
- [ ] **Chain length** — Async chains do not turn one action into a long sequence of opaque
  partial states.
- [ ] **Failure semantics** — Dropped, duplicated, delayed, and reordered events have explicit
  handling.
- [ ] **Ownership** — Someone owns the end-to-end workflow, not just individual consumers.

Flag event-driven sprawl when async decomposition makes correctness, replay, or incident
response materially harder than a simpler queue, worker, or transaction boundary would.

---

## 5. Kubernetes and Service Mesh Fit

Kubernetes and service meshes can be the right platform for multi-team, multi-service
systems with mature operations. They are findings only when the operational capability does
not match the machinery.

- [ ] **Cluster operations** — Upgrades, ingress, DNS, certificates, secrets, node health,
  storage, and autoscaling have clear ownership.
- [ ] **Paved paths** — Developers can deploy, observe, roll back, and debug without bespoke
  cluster expertise for every change.
- [ ] **Mesh justification** — mTLS, traffic shaping, policy, or telemetry needs are concrete
  and verified.
- [ ] **Failure visibility** — Sidecar/proxy failures, policy mistakes, and retries are visible
  in dashboards and runbooks.
- [ ] **Local and test workflow** — The platform does not make ordinary development or
  integration testing disproportionately slow.

Prefer a smaller runtime, managed platform, or simpler ingress/traffic controls when the
team cannot operate the current platform during incidents.

---

## 6. Serverless Orchestration Fit

Serverless functions and state machines are useful for bursty, isolated workflows. They can
become expensive or hard to reason about when state, retries, and partial failures are spread
across too many steps.

- [ ] **State locality** — The current state and next action are easy to inspect.
- [ ] **Retry semantics** — Platform retries, application retries, and compensation logic do
  not conflict.
- [ ] **Cost bounds** — Fan-out, polling, transitions, and data transfer have guardrails.
- [ ] **Local debugging** — Developers can reproduce representative workflows without relying
  on production-only behavior.
- [ ] **Recovery path** — Operators can resume, cancel, replay, or reconcile failed executions.

Flag orchestration complexity when the workflow would be safer as a worker, batch job,
single service, or simpler state machine.

---

## 7. AI and Multi-Agent Workflow Fit

AI and agentic systems add model latency, tool fan-out, non-determinism, and observability
requirements. Review them as architecture, not just prompt logic.

- [ ] **Hop necessity** — Each agent, model call, or tool call has a clear purpose and output
  contract.
- [ ] **Fan-out control** — Parallel tool calls and recursive planning are bounded by budget,
  latency, and safety limits.
- [ ] **Debuggability** — Prompts, tool inputs/outputs, model choices, and final decisions are
  traceable enough for incident review.
- [ ] **Cost and latency** — The workflow meets user-facing latency and spend constraints
  under realistic load.
- [ ] **Fallback and escalation** — Low-confidence, failed-tool, or unsafe-output cases have a
  deterministic path.

Flag unnecessary agent hops when a deterministic function, direct tool call, or simpler
single-agent flow would be cheaper, faster, and easier to debug.

---

## 8. Cost and Operability Model

Compare the current architecture against the simplest plausible architecture that preserves
required resilience.

- [ ] **Per-boundary overhead** — Each deployable adds pipeline, config, observability,
  ownership, rollout, and incident-response cost.
- [ ] **Data movement** — Cross-service, cross-zone, cross-region, and object-store transfers
  are measured on hot paths.
- [ ] **Observability spend** — Logs, traces, metrics, and high-cardinality labels scale with
  architecture shape, not only user traffic.
- [ ] **Human cost** — On-call rotations, debugging time, release coordination, and onboarding
  are part of the cost model.
- [ ] **Cost-per-change** — Estimate whether a typical feature is cheaper or more reliable in
  the current design than in a simpler boundary.

Use qualitative judgment if precise cost data is unavailable. Prefer "measure this before
deciding" over unsupported multipliers.

---

## 9. Case Studies as Calibration, Not Rules

Use case studies to generate questions, not to assign severity by analogy.

**Prime Video audio/video monitoring** — The team reported that consolidating a specific
distributed monitoring workflow into a more local design reduced infrastructure cost and
removed orchestration/data-transfer overhead. This does not mean Prime Video abandoned
distributed systems; it means a specific workflow did not benefit from that distribution.
Source: https://www.primevideotech.com/video-streaming/scaling-up-the-prime-video-audio-video-monitoring-service-and-reducing-costs-by-90

**Twilio Segment "Goodbye Microservices"** — Segment described a destination-delivery area
where many small services became difficult to test, deploy, and maintain, then consolidated
that area into a simpler service. Use it to ask whether a service split still delivers
independence and developer velocity.
Source: https://www.twilio.com/en-us/blog/developers/best-practices/goodbye-microservices/

**Shopify modular monolith** — Shopify described using a large Rails monolith with enforced
component boundaries through Packwerk. Use it as evidence that internal modularity and
single deployability can coexist at large scale when boundaries are actively managed.
Source: https://shopify.engineering/blogs/engineering/shopify-monolith

---

## Severity Guidance

- **P1-HIGH**: Evidence-backed distributed-monolith coupling on a critical path; operational
  overload already causing incidents or delayed recovery; architecture-driven latency,
  retry, event, or agent fan-out that amplifies failures.
- **P2-MEDIUM**: Avoidable complexity with measurable cost, debugging, or delivery drag;
  premature boundaries; platform machinery that exceeds current operating maturity but has
  limited blast radius.
- **P3-LOW**: Architecture choices that are suboptimal or worth revisiting, but not causing
  material resilience, cost, or operability harm yet.

See `severity-calibration.md` for the full calibration matrix.
See `validation-monitoring-patterns.md` for validation and monitoring approaches.
