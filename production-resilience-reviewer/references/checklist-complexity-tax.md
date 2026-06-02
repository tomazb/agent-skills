# Checklist: Complexity Tax & Architecture Fit (Lens 12)

Deep-dive reference for evaluating whether an architecture matches its actual constraints.
This lens is the contrarian counterpart to the operational lenses — it challenges the
architecture itself rather than reviewing how well it handles failures.

Cross-references: `severity-calibration.md`, `validation-monitoring-patterns.md`

---

## 1. Distribution Necessity

For **each** service boundary, require at least one concrete justification:

- [ ] **Independent scaling proof** — This service has a demonstrably different resource
  profile (CPU/memory/IO) or traffic pattern that cannot be served by scaling the whole
  application. Evidence: load test data, resource utilization showing divergent profiles.
- [ ] **Team autonomy proof** — A dedicated team owns this service end-to-end and ships
  independently on a different cadence. Evidence: separate on-call rotation, independent
  release schedule, team size ≥ 3 engineers.
- [ ] **Regulatory isolation proof** — Compliance requirements (PCI-DSS, SOC2, HIPAA)
  mandate physical separation of this component from the rest of the system.
- [ ] **Technology divergence proof** — This component genuinely requires a different
  runtime, language, or data store that cannot coexist in the main application.

**If none of these apply**, the service boundary is adding distributed-system tax without
delivering independence. Recommend collapsing into a module within the main application.

**Red flags:**
- "We might need to scale it independently someday" — predicted problems, not observed ones
- "It's cleaner as a separate service" — code organization is not a deployment decision
- "Each microservice should be small" — size is not a valid decomposition criterion

---

## 2. Team Topology Fit

Conway's Law is a constraint, not a suggestion. Architecture must match organizational
communication structure.

- [ ] **Engineer-to-service ratio** — Calculate: `total_engineers / total_services`. If
  < 2, the team cannot sustain the operational burden. Below 1 is a strong P1 signal.
- [ ] **Platform team existence** — Does a dedicated platform/SRE team absorb cross-cutting
  concerns (CI/CD, observability, service mesh, infrastructure)? Without one, every
  product engineer shares the operational tax.
- [ ] **Cognitive load assessment** — Can a single engineer reason about the full request
  path for a typical user action? If tracing a request requires understanding > 5 services,
  cognitive load may exceed team capacity.
- [ ] **On-call sustainability** — Is the on-call rotation sustainable? N services × alerts
  × pages with a team of M engineers. If M < 8, a single on-call rotation covering all
  services is likely unsustainable.
- [ ] **Deployment coordination** — How many services must change for an average feature?
  If > 1 consistently, the architecture is not delivering independent deployability.

**Thresholds (heuristics, not rules):**
- < 10 engineers: monolith or modular monolith almost always wins
- 10–50 engineers: modular monolith; extract services only for proven divergent needs
- 50–150 engineers: selective microservices with dedicated platform team
- 150+ engineers: microservices with mature platform engineering

---

## 3. Latency & Performance Tax

Every service boundary converts an in-process call to a network call. Quantify the cost.

- [ ] **Call chain depth** — Map the longest synchronous call chain for a user-facing
  request. Each hop adds ~1–5ms (same-zone) of network latency plus serialization overhead.
  A 5-hop chain adds 10–25ms before any business logic runs.
- [ ] **Serialization overhead** — Each service boundary requires serialize → transmit →
  deserialize. JSON serialization of a complex object takes ~50–150μs per boundary.
  In a 5-service chain, pure SerDe overhead can reach ~1.5ms.
- [ ] **Fan-out amplification** — Does a single request fan out to multiple services? If
  service A calls B, C, and D in parallel, and each of those calls E, a single user
  request generates 7 internal calls. Map the actual fan-out graph.
- [ ] **Tail latency multiplication** — With N dependencies, the probability of at least
  one slow response per request is `1 - (1 - p_slow)^N`. With 10 dependencies each slow
  1% of the time: `1 - 0.99^10 = 9.6%` of requests hit a slow dependency.
- [ ] **Comparison baseline** — Would a modular monolith serving the same request path
  eliminate measurable latency? If yes, quantify the difference.

---

## 4. Operational Capacity

The operational tax of microservices is not one-time — it compounds with every service.

- [ ] **Pipeline count** — N services = N CI/CD pipelines to build, maintain, monitor,
  and debug. Each needs its own build config, test suite, container registry, deploy
  automation, and rollback strategy.
- [ ] **Observability infrastructure** — Distributed tracing (Jaeger/Zipkin/OTel), centralized
  logging (ELK/CloudWatch), unified metrics (Prometheus/Grafana), and service mesh
  (Istio/Linkerd) are prerequisites, not luxuries. Without them, debugging a production
  issue across services is guesswork.
- [ ] **Infrastructure-to-feature ratio** — What percentage of engineering time goes to
  infrastructure vs product features? If > 30%, the architecture is consuming the team.
  Segment's 3-engineer team was consumed by 140+ services.
- [ ] **Environment complexity** — Can a developer run the system locally for development?
  If running the full system requires N containers, M databases, and a service mesh, the
  development experience is degraded. Onboarding time > 1 day is a signal.
- [ ] **Incident complexity** — In a monolith, a bug is a stack trace. In microservices,
  a bug is a distributed mystery. Teams spend ~35% more time debugging distributed systems
  (DZone 2024). Is the team staffed for this overhead?

---

## 5. Distributed Monolith Smells

A distributed monolith has all the operational overhead of microservices with none of the
independence benefits. It is the worst outcome — worse than either a clean monolith or
properly independent microservices.

- [ ] **Shared database** — Multiple services read from or write to the same database
  tables. Any schema change cascades across services. This eliminates independent
  deployability.
- [ ] **Coordinated deploys** — A change in one service requires deploying other services
  simultaneously. If a library bump requires redeploying the fleet, the architecture is
  a distributed monolith.
- [ ] **Cross-service PRs** — A single feature routinely touches ≥ 3 service repositories.
  The boundaries are in the wrong place.
- [ ] **Full-fleet test environments** — Integration/E2E testing requires spinning up all
  services. If you cannot test one service in isolation, independence is illusory.
- [ ] **Synchronous call chains > 2 hops** — Deep synchronous chains create tight runtime
  coupling. A → B → C → D means D's latency directly impacts A's response time, and any
  failure cascades the full chain.
- [ ] **Shared libraries with tight coupling** — A shared library that forces synchronized
  version upgrades across services re-creates monolithic coupling at the dependency level.

**If ≥ 3 of these smells are present**, classify the architecture as a distributed monolith
and flag as **P1-HIGH**.

---

## 6. Cost Model

Microservices architectures cost 3.75×–6× more than equivalent monoliths in infrastructure
alone, before accounting for people costs.

- [ ] **Per-service infrastructure** — Each service needs compute, storage, networking,
  monitoring, and a deployment pipeline. Multiply by N services for the baseline.
- [ ] **Network egress** — Inter-service traffic generates data transfer costs, especially
  cross-AZ or cross-region. A system making 50 internal calls per user request pays for
  50 network round-trips that a monolith handles at zero incremental cost.
- [ ] **Platform team headcount** — A microservices architecture typically demands 2–4
  platform engineers plus distributed operational effort. A modular monolith can often
  run with 1–2 operations engineers.
- [ ] **Observability costs** — Distributed tracing, centralized logging, and metrics
  infrastructure scale with service count, not user count. More services = higher
  observability spend regardless of traffic.
- [ ] **Cost-per-feature comparison** — Compare the fully-loaded cost of delivering a
  feature (dev time + infra + ops) in the current architecture vs a modular monolith
  baseline. If the current architecture is ≥ 2× more expensive per feature, the
  complexity tax exceeds its benefits.

---

## 7. Alternative Architectures

Not every system needs microservices. Evaluate simpler alternatives before accepting
distributed complexity.

### When a Modular Monolith Wins
- Team < 50 engineers
- Domain boundaries still evolving
- No divergent scaling requirements between components
- No regulatory isolation mandates
- Development velocity is the primary constraint
- Shopify existence proof: 2.8M lines, 37 components, hundreds of engineers, billions in
  GMV — all on a modular Rails monolith with enforced boundaries (Packwerk)

### When Selective Extraction Wins
- One specific module has proven divergent scaling needs (e.g., image processing requiring
  10× the compute of the API)
- One module has a genuinely different deployment cadence (compliance-reviewed quarterly
  vs feature team shipping daily)
- Use the Strangler Fig pattern: facade → extract one capability → validate → repeat

### When Microservices Win
- 150+ engineers with stable, team-owned bounded contexts
- Dedicated platform team absorbing cross-cutting concerns
- Proven independent scaling requirements (not predicted)
- Regulatory isolation mandates (PCI scope reduction)
- Multiple teams needing genuinely independent deployment cadences

### Decision Heuristic
Ask: "What specific, observed problem does this architecture solve that a modular monolith
cannot?" If the answer references predicted scale, conference talks, or "best practices,"
the architecture is solving an imagined problem.

---

## 8. Case Studies (Condensed)

**Amazon Prime Video (2023)** — Video quality monitoring service rebuilt from distributed
Lambda/Step Functions architecture to single-process monolith. Result: 90% infrastructure
cost reduction. The distributed architecture added network overhead and orchestration
complexity without delivering value — all components processed the same video stream.

**Segment** — Built 140+ microservices for event routing. Three engineers spent most of
their time keeping services running instead of building features. Consolidated back to a
monolith. "Instead of enabling us to move faster, the small team found themselves mired
in exploding complexity."

**Shopify** — 2.8M lines of Ruby on Rails, 37 internal components with enforced boundaries
(Packwerk), hundreds of active developers, processes $200B+ annual GMV. Explicitly
evaluated and rejected microservices. Extracts services only for proven divergent scaling
(storefront rendering) or regulatory isolation (credit-card vaulting).

**CNCF 2025 Survey** — 42% of organizations that adopted microservices are now consolidating
services back into larger units. Primary drivers: debugging complexity, operational
overhead, and network latency.

**SpringOne 2024** — Team consolidated 47 microservices back to modular monolith.
Deployment time: 40 min → 6 min. Cloud costs: -63%. The 47-service architecture had
become a distributed monolith — dense inter-service call graph, no service deployable
independently.

---

## Severity Guidance

- **P1-HIGH**: Distributed monolith anti-patterns (≥ 3 smells from Section 5); microservices
  with < 10 engineers and no platform team; cost multiplier ≥ 4× with no independence benefit
- **P2-MEDIUM**: Premature decomposition (unstable domain boundaries); over-engineering
  (service mesh for < 5 services, Kubernetes for < 10 engineers); engineer-to-service
  ratio < 2 but > 1
- **P3-LOW**: Architecture decisions that are suboptimal but not actively harmful; minor
  over-provisioning of infrastructure tooling

See `severity-calibration.md` for the full calibration matrix.
See `validation-monitoring-patterns.md` for validation and monitoring approaches.
