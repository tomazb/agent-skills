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
- [ ] Backpressure behavior is defined when queues are full (drop, reject, shed, throttle, block with timeout)
- [ ] Batch aggregators have size/time bounds
- [ ] Per-request list/map growth is bounded by pagination or hard limits
- [ ] DLQ/retry queues have retention and max-depth controls
- [ ] Queue consumers can keep up with producer rate at expected peak traffic

### Red Flags
- `append` loops over unbounded streams with no cap
- \"Load all rows into memory\" patterns in request handlers
- Queue depth metrics missing on asynchronous workflows

---

## 2. Connection Pool Sizing and Saturation

Pool exhaustion creates cascading latency and timeout failures.

### Checklist
- [ ] DB/HTTP/client pool max sizes are explicitly configured
- [ ] Acquire timeout is configured (no infinite wait for pool slot)
- [ ] Pool size aligns with worker concurrency and downstream capacity
- [ ] Idle/keepalive settings prevent connection churn
- [ ] Critical dependencies have independent pools (avoid noisy-neighbor starvation)
- [ ] Connection leaks are detectable (long-held connections, missing close/release)

### Heuristics
- If pool in-use is >80-90% during normal peaks, saturation risk is high.
- If request latency tracks pool wait time, pool starvation is likely root cause.

---

## 3. N+1 and Fan-Out Amplification Patterns

Fan-out causes throughput collapse when each request multiplies downstream calls.

### Checklist
- [ ] Request path avoids per-item dependency calls when batched alternatives exist
- [ ] Query plans avoid ORM N+1 access patterns
- [ ] Parallel fan-out has bounded concurrency
- [ ] Retry strategy does not multiply fan-out storms
- [ ] Aggregator endpoints enforce result size limits and pagination
- [ ] Expensive downstream joins are cached or precomputed when appropriate

### Common Patterns
- API handler loops over 500 items and calls dependency 500 times
- Nested fan-out (A calls B per item; B calls C per item)
- Serial fan-out where independent calls could be batched

---

## 4. Thread/Goroutine Explosion Signals

Concurrency primitives are cheap until they are not.

### Checklist
- [ ] Thread/goroutine creation is bounded by worker pools/semaphores
- [ ] Async tasks have cancellation and timeout support
- [ ] Work queues decouple ingress rate from worker count
- [ ] Blocking calls are not executed on event loops or limited executors
- [ ] Background workers have lifecycle ownership and graceful shutdown logic
- [ ] High-cardinality user input cannot create unbounded concurrent tasks

### Signals to Watch
- Rapid increase in runnable threads/goroutines with flat throughput
- Increased GC pressure and scheduler latency
- High context-switch rate with little useful work

---

## 5. Lock Contention and Coordination Hotspots

Correctness without throughput is still an outage at scale.

### Checklist
- [ ] Critical sections are short and avoid network/IO inside locks
- [ ] Lock ordering is documented for multi-lock paths
- [ ] Contended shared structures use sharding/partitioning where possible
- [ ] Hot counters/maps use lock-free/atomic alternatives where appropriate
- [ ] Read/write lock usage matches actual read/write ratios
- [ ] Deadlock detection/timeouts are available for critical lock paths

### Contention Signals
- CPU high + low throughput + threads blocked on mutex/semaphore
- p95/p99 latency spikes with normal downstream dependency health
- Profiling shows significant time in lock wait states

---

## 6. Validation & Monitoring Add-Ons

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

### Validation Ideas (Load/Concurrency-Focused)
- [ ] Load test at 1×/5×/10× expected traffic with dependency latency injection
- [ ] Queue saturation drill (fill queue to max, verify graceful rejection/degradation)
- [ ] Pool exhaustion test (limit pool, verify bounded failure behavior)
- [ ] Fan-out amplification simulation with large result sets
- [ ] Lock contention profiling under concurrent request storms

### Monitoring Ideas (Load/Concurrency-Focused)
- [ ] Queue depth, enqueue/dequeue rates, and age of oldest message
- [ ] Pool in-use %, wait time, timeout count, and connection error rates
- [ ] Thread/goroutine count, scheduler latency, context-switch rates
- [ ] p50/p95/p99 latency segmented by endpoint and dependency
- [ ] Lock wait time and contention counts (if runtime exposes them)

---

## 7. Finding Snippet Template

```markdown
[LOAD]
Finding: <load/concurrency bottleneck or failure mode>
Evidence: <queue/pool/fan-out/thread/lock signal from code or telemetry>
Why it matters: <latency collapse, throughput drop, cascading failures>
Recommendation: <bounded queues, pool tuning, batching, concurrency caps, lock redesign>
Validation: <load/fault/contension test plan>
Monitoring: <queue/pool/latency/thread/lock metrics and alerts>
Priority: <P0/P1/P2/P3>
```
