# Data Consistency, Caching & Freshness Patterns

> Related references:
> - `references/severity-calibration.md` — severity/context calibration rules
> - `references/validation-monitoring-patterns.md` — reusable validation & monitoring patterns
> - `references/checklist-change-management.md` — rollout/migration/rollback deep-dive (Lens 8)


## Table of Contents
1. Cache Failure Patterns
2. Consistency Models & Their Traps
3. Race Condition Catalog
4. Thundering Herd Prevention
5. Data Validation at Boundaries
6. Data Change Management & Rollback Safety
7. Validation & Monitoring Add-Ons

---

## 1. Cache Failure Patterns

### Cache Stampede / Thundering Herd
- **Trigger**: Popular cache key expires, 1000 concurrent requests all miss cache, all hit DB
- **Impact**: Database gets 1000x normal load for that query, potentially cascading failure
- **Mitigations**:
  - Lock-based recomputation: First requester acquires lock, others wait or get stale value
  - Probabilistic early expiration: Each request has a small chance of refreshing before TTL
  - Background refresh: Separate process refreshes cache before expiration
  - Stale-while-revalidate: Serve stale value immediately, refresh asynchronously

### Cache Penetration
- **Trigger**: Requests for keys that will never exist in cache (e.g., random IDs, enumeration attacks)
- **Impact**: Every request hits the database, cache provides zero benefit
- **Mitigations**:
  - Cache negative results (short TTL, e.g., 60s) so repeated misses are cached
  - Bloom filter in front of cache to reject obviously-missing keys
  - Input validation to reject malformed keys before cache lookup

### Cache Pollution
- **Trigger**: Low-frequency items evict high-frequency items due to cache size limits
- **Impact**: Hit rate drops, effective cache size shrinks
- **Mitigations**:
  - LFU (Least Frequently Used) eviction instead of LRU for mixed workloads
  - Separate cache pools for different access patterns
  - Admission policies: don't cache items on first access, only on second

### Cache Inconsistency
- **Trigger**: Data updated in database but cache still holds old value
- **Impact**: Users see stale data, business logic operates on stale state
- **Severity depends on data type**:
  - Product descriptions: Low risk (stale for minutes is usually fine)
  - Prices: Medium risk (stale price could mean incorrect charges)
  - Permissions/access control: High risk (stale permissions = security hole)
  - Account balances: Critical risk (stale balance = double-spend possible)

### Cache Invalidation Patterns (Tradeoffs by Consistency, Latency & Complexity)
Use the pattern that matches your architecture and failure tolerance — there is no universal ranking.
Evaluate each option on **consistency guarantees**, **write latency**, **operational complexity**, and **rollback behavior**.

- **Write-through / write-around**: Can reduce staleness, but true atomicity across DB + cache is hard in distributed systems.
- **Delete-on-write (explicit invalidation)**: Common and effective; leaves a small inconsistency window but simpler than dual writes.
- **TTL-based expiration**: Simple and safe for low-risk data; consistency depends on TTL and access patterns.
- **Event-driven invalidation (CDC / outbox / change stream)**: Can be very reliable and scalable when delivery/replay semantics are well designed.
- **Stale-while-revalidate**: Excellent for availability/latency; requires careful use on business-critical mutable data.

**Review questions for any pattern**
- What is the maximum tolerated staleness for this data type?
- What happens if invalidation is delayed, duplicated, or lost?
- Can the system replay invalidation events safely after downtime?
- How is cache behavior affected during rollback or partial deploys?

### Cache Invalidation Anti-Patterns
- Updating the cache value instead of deleting it (risk of race: read old DB value, write to cache, overwrite newer value)
- Invalidating cache before writing to DB (race: another read repopulates cache with old DB value)
- No cache invalidation at all with long TTLs for mutable data
- Broadcast invalidation without deduplication (N servers each invalidate, causing N cache misses)

---

## 2. Consistency Models & Their Traps

### Read-After-Write Consistency
- **The trap**: User writes data, immediately reads it back, gets old value
- **Common cause**: Write goes to primary DB, read goes to replica (replication lag)
- **Mitigations**:
  - Read from primary for X seconds after a write (session-consistent reads)
  - Include a version token in the write response, reject reads with older version
  - For critical paths: always read from primary

### Eventual Consistency Hazards
- **The trap**: Two services read the same data at different times, make decisions based on different states
- **Example**: Service A reads inventory=1, Service B reads inventory=1, both sell the item. Inventory is now -1.
- **Mitigations**:
  - Optimistic locking (version numbers, ETags)
  - Pessimistic locking (distributed locks) for critical sections
  - Idempotent operations that converge regardless of order (CRDTs)
  - Saga pattern for multi-service transactions with compensating actions

### Dual-Write Problem
- **The trap**: Writing to two systems (e.g., database + search index) without atomicity. One write succeeds, the other fails.
- **Mitigations**:
  - Outbox pattern: Write to one system (DB), use change data capture to replicate to the other
  - Transaction log tailing: Read the database's own replication log to drive secondary writes
  - Never write to two systems in the same request path without a coordination mechanism

---

## 3. Race Condition Catalog

### Check-Then-Act
```
// DANGEROUS: Race between check and action
if (inventory > 0) {        // Thread A reads: inventory = 1
                              // Thread B reads: inventory = 1
  inventory -= 1;            // Thread A: inventory = 0
                              // Thread B: inventory = -1 ← oversold
  createOrder();
}
```
**Fix**: Atomic decrement with condition (`UPDATE inventory SET count = count - 1 WHERE count > 0`)

### Read-Modify-Write
```
// DANGEROUS: Lost update
balance = getBalance(userId);      // Thread A reads: 100
                                    // Thread B reads: 100
balance += depositAmount;           // Thread A: 100 + 50 = 150
                                    // Thread B: 100 + 30 = 130
setBalance(userId, balance);        // Thread A writes: 150
                                    // Thread B writes: 130 ← Thread A's deposit is lost
```
**Fix**: Optimistic locking with version check, or atomic increment operations

### Time-of-Check to Time-of-Use (TOCTOU)
```
// DANGEROUS: Permission check and action are not atomic
if (userHasPermission(userId, resource)) {
  // Permission could be revoked between check and use
  performAction(resource);
}
```
**Fix**: Perform authorization check atomically with the action, or accept a small window and log for audit

---

## 4. Thundering Herd Prevention

### Scenarios That Trigger Thundering Herd
- Cache key expires for a popular resource
- Service restarts and all caches are cold
- Feature flag change causes all clients to re-fetch configuration
- Scheduled jobs all fire at exactly the same time (cron at :00)
- Service comes back after outage, all queued retries fire simultaneously

### Prevention Techniques
1. **Jittered expiration**: Add random offset to TTL (e.g., base TTL ± 10%)
2. **Request coalescing**: Multiple concurrent requests for the same key share a single backend call
3. **Staggered startup**: Don't start all instances simultaneously; add random delay
4. **Rate-limited cache warming**: On cold start, warm cache gradually, not all at once
5. **Jittered cron**: Don't schedule all jobs at :00; spread across the minute
6. **Retry jitter**: Always add randomness to retry delays

---

## 5. Data Validation at Boundaries

### Input Validation Checklist
Every piece of data that crosses a trust boundary (user input, API response, message queue payload, file content) must be validated:

- [ ] **Type**: Is it the expected type? (string, number, array, object)
- [ ] **Range**: Is a numeric value within acceptable bounds?
- [ ] **Length**: Is a string/array within size limits? (prevent memory exhaustion)
- [ ] **Format**: Does it match expected patterns? (email, URL, date, UUID)
- [ ] **Encoding**: Is it valid UTF-8? Are there null bytes or control characters?
- [ ] **Presence**: Are required fields actually present?
- [ ] **Referential integrity**: Do foreign keys reference existing records?

### Output Validation (Often Forgotten)
- [ ] **Response size**: Is the response within expected bounds? A 500MB JSON response is probably a bug.
- [ ] **Response time**: Did the query take suspiciously long? Log it.
- [ ] **Schema conformance**: Does the response match the expected schema? Log schema violations.

### API Response Defensive Parsing
```
// DANGEROUS: Trusting the shape of external API responses
const userName = response.data.user.name;  // Any of these could be undefined

// SAFE: Defensive access with validation
const userName = response?.data?.user?.name;
if (!userName || typeof userName !== 'string') {
  logger.warn('Unexpected response shape from UserService', {
    correlationId,
    responseKeys: Object.keys(response?.data || {}),
  });
  return fallbackValue;
}
```

### Special Cases: AI/ML Model Responses
When consuming AI-generated content or ML model outputs:
- [ ] Validate output format strictly (models can return malformed JSON, truncated responses)
- [ ] Set maximum output token/size limits
- [ ] Implement content safety checks before displaying to users
- [ ] Handle model timeout/rate limiting (LLM APIs are frequently rate-limited)
- [ ] Cache model responses when inputs are identical (LLM calls are expensive)
- [ ] Have a fallback for when the model is unavailable (static response, queue for later, graceful degradation)


---

## 6. Data Change Management & Rollback Safety (Lens 8 Alignment)

For broader rollout and rollback patterns, see `references/checklist-change-management.md`.

Data changes (schema, formats, indexes, backfills, cache keys, event versions) are a major source of production incidents.
Review the change plan, not just the steady-state data model.

### Schema & Model Change Checklist
- [ ] Expand/contract approach used for destructive changes (additive first, removal later)
- [ ] New columns/fields are nullable or have safe defaults during rollout
- [ ] Old and new application versions can coexist during deployment
- [ ] Reads tolerate both old and new formats (dual-read or backward-compatible parsing)
- [ ] Writes are compatible during rollout (dual-write when necessary, with comparison metrics)
- [ ] Migration is idempotent and safe to resume after interruption

### Backfill & Migration Safety
- [ ] Backfill is rate-limited and can be paused/resumed
- [ ] Backfill progress is measurable (cursor/progress metric)
- [ ] Backfill does not overwhelm primary DB, replicas, caches, or queues
- [ ] Retry logic for backfill workers is idempotent and bounded
- [ ] Partial failure behavior is defined (skip, retry, DLQ, manual reconciliation)
- [ ] Rollback plan accounts for data already written in new format

### Cache / Event Versioning Changes
- [ ] Cache key versioning strategy exists (`user:v2:{id}`) to avoid serving incompatible shapes
- [ ] Event schema evolution is documented (additive fields first, consumer tolerance)
- [ ] Consumers handle duplicates and replays after deploy/rollback
- [ ] Ordering assumptions are explicit (and safe if violated)

### Data Change Anti-Patterns
- Destructive migration + app deploy in one step with no compatibility window
- Backfill run at full speed during peak traffic
- Changing cache value shape without key versioning
- Rollback plan that assumes "data will revert itself"
- Schema change tested only on empty/small datasets

---

## 7. Validation & Monitoring Add-Ons (Lens 8 + Required Finding Template Alignment)

See also `references/validation-monitoring-patterns.md` for shared patterns and additional examples.

For P0/P1 data findings, include how to prove the fix and how to watch it in production.

### Validation: Data Safety Tests
- [ ] Migration dry-run on production-like dataset (or sampled clone)
- [ ] Mixed-version deploy test (old + new app versions) for reads/writes
- [ ] Rollback rehearsal after new-format writes occur
- [ ] Concurrency test for race conditions (check-then-act, lost update, TOCTOU)
- [ ] Cache stampede simulation / cold-cache load test
- [ ] Duplicate/replay test for queue consumers and idempotency keys
- [ ] Invariant checks (e.g., balance never negative, permissions monotonicity, row counts match)

### Monitoring: Data Integrity & Freshness Signals
- [ ] Freshness lag metrics (replication lag, event lag, cache age/staleness)
- [ ] Cache hit rate + miss rate + stampede indicators + invalidation error count
- [ ] Data mismatch compare metrics during dual-read/dual-write rollout
- [ ] Migration/backfill progress, throughput, error rate, retry rate, ETA
- [ ] Queue consumer lag / DLQ depth / duplicate detection counters
- [ ] Business guardrails (payment success rate, order completion rate, authz deny/allow anomalies)
- [ ] Alerts for stuck migrations, rising lag, mismatch spikes, or invariant violations

### Finding Snippet Template (Data)
```markdown
[DATA]
Finding: <staleness / consistency / race / migration risk>
Evidence: <code path / schema change / cache pattern>
Why it matters: <business impact, corruption risk, blast radius>
Recommendation: <pattern change / migration plan / idempotency / versioning fix>
Validation: <tests, load simulation, rollback rehearsal, invariant checks>
Monitoring: <freshness, mismatch, lag, guardrail metrics + alerts>
Priority: <P0/P1/P2/P3>
```
