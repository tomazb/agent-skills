# Load & Concurrency Patterns (Lens 2 Deep-Dive)

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-dependency.md` — dependency-level retry/timeout/circuit guidance
> - `references/checklist-network-latency.md` — network-latency-specific timeout and deadline details

## Table of Contents
1. Unbounded Queue and Buffer Detection
2. Connection Pool Sizing and Saturation
3. N+1 and Fan-Out Amplification Patterns
4. Thread/Goroutine Explosion Signals
5. Lock Contention and Coordination Hotspots
6. Validation & Monitoring Add-Ons
7. Finding Snippet Template

---

## 1. Unbounded Queue and Buffer Detection

Unbounded in-memory growth is often the first failure under load.

### Checklist
- [ ] Input queues/channels have explicit max depth
- [ ] Backpressure behavior is defined when queues are full (drop, reject, shed, throttle, block with deadline)
- [ ] Batch aggregators have size/time bounds
- [ ] Per-request list/map growth is bounded by pagination or hard limits
- [ ] DLQ/retry queues have retention and max-depth controls
- [ ] Queue consumers can keep up with the measured or forecast producer rate

### Red Flags
- `append` loops over unbounded streams with no cap
- "Load all rows into memory" patterns in request handlers
- Queue depth, oldest-item age, or enqueue/dequeue rate is not observable

---

## 2. Connection Pool Sizing and Saturation

Pool exhaustion creates cascading latency and deadline failures.

### Checklist
- [ ] DB/HTTP/client pool max sizes are explicitly configured or their defaults are verified
- [ ] Acquire deadline is configured (no infinite wait for a pool slot)
- [ ] Pool size aligns with worker concurrency, downstream capacity, and deployment replica count
- [ ] Idle/keepalive settings prevent connection churn without retaining stale connections indefinitely
- [ ] Critical dependencies have independent pools where noisy-neighbor starvation is credible
- [ ] Connection leaks are detectable (long-held connections, missing close/release)

### Evidence-Based Heuristics
- Derive warning and critical saturation thresholds from the headroom needed to meet the latency
  SLO during expected peaks and dependency slowdown. Do not use one universal utilization percentage.
- If request latency tracks pool wait time while dependency service time remains stable, pool
  starvation is a strong root-cause signal.
- If increasing the pool shifts saturation to the database or dependency, the pool was not the
  actual capacity constraint.

---

## 3. N+1 and Fan-Out Amplification Patterns

Fan-out causes throughput collapse when each request multiplies downstream calls.

### Checklist
- [ ] Request path avoids per-item dependency calls when batched alternatives exist
- [ ] Query plans avoid ORM N+1 access patterns
- [ ] Parallel fan-out has bounded concurrency and cancellation
- [ ] Retry strategy does not multiply fan-out storms
- [ ] Aggregator endpoints enforce result size limits and pagination
- [ ] Expensive downstream joins are cached or precomputed only when consistency permits it

### Common Patterns
- API handler loops over a user-controlled result set and calls a dependency per item
- Nested fan-out (A calls B per item; B calls C per item)
- Serial fan-out where batching or bounded parallelism is safe

---

## 4. Thread/Goroutine Explosion Signals

Concurrency primitives are cheap until they are not.

### Checklist
- [ ] Thread/goroutine creation is bounded by worker pools/semaphores
- [ ] Async tasks have cancellation and deadline support
- [ ] Work queues decouple ingress rate from worker count
- [ ] Blocking calls are not executed on event loops or scarce executors
- [ ] Background workers have lifecycle ownership and graceful shutdown logic
- [ ] High-cardinality user input cannot create unbounded concurrent tasks

### Signals to Watch
- Rapid increase in runnable threads/goroutines with flat throughput
- Increased GC pressure and scheduler latency
- High context-switch rate with little useful work
- Growing cancellation lag or orphaned task count

---

## 5. Lock Contention and Coordination Hotspots

Correctness without throughput is still an outage at scale.

### Checklist
- [ ] Critical sections are short and avoid network/IO inside locks
- [ ] Lock ordering is documented for multi-lock paths
- [ ] Contended shared structures use sharding/partitioning where appropriate
- [ ] Hot counters/maps use lock-free/atomic alternatives where appropriate
- [ ] Read/write lock usage matches actual read/write ratios
- [ ] Deadlock detection/deadlines are available for critical lock paths

### Contention Signals
- CPU high + low throughput + threads blocked on mutex/semaphore
- Tail latency spikes with normal downstream dependency health
- Profiling shows significant time in lock wait states

---

## 6. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Load/Concurrency-Focused)
- [ ] Test expected peak, planned growth, stress, and failure-amplified demand derived from the
  traffic model; include dependency latency injection
- [ ] Queue saturation drill (fill queue to its limit, verify intended rejection/degradation)
- [ ] Pool exhaustion test (constrain the pool, verify bounded acquire failure and recovery)
- [ ] Fan-out amplification simulation with maximum allowed result sets
- [ ] Lock contention profiling under representative concurrency

### Monitoring Ideas (Load/Concurrency-Focused)
- [ ] Queue depth, enqueue/dequeue rates, and age of oldest message
- [ ] Pool in-use, wait time, acquire deadline count, and connection error rates
- [ ] Thread/goroutine count, scheduler latency, context-switch rates, and orphaned tasks
- [ ] Latency distributions segmented by normalized endpoint and dependency
- [ ] Lock wait time and contention counts (if runtime exposes them)

---

## 7. Finding Snippet Template

```markdown
[LOAD]
Finding: <load/concurrency bottleneck or failure mode>
Evidence: <queue/pool/fan-out/thread/lock signal from code or telemetry>
Why it matters: <latency collapse, throughput drop, cascading failures>
Recommendation: <bounded queues, pool tuning, batching, concurrency caps, lock redesign>
Validation: <load/fault/contention test plan>
Monitoring: <queue/pool/latency/thread/lock metrics and alerts>
Priority: <P0/P1/P2/P3>
```
