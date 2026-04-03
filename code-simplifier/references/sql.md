# SQL Simplification Reference

Load this file when simplifying SQL queries (application SQL, migration scripts, analytics queries, stored-procedure query bodies).

## Table of Contents
1. Query Simplification Patterns
2. Common Anti-Patterns → Fixes
3. Dialect-Specific Notes
4. When NOT to Simplify

---

## 1. Query Simplification Patterns

### Subquery → CTE when intent is easier to follow

Use a CTE when a subquery is reused, deeply nested, or conceptually a named intermediate step.

```sql
-- Before
SELECT o.id, o.total
FROM orders o
WHERE o.customer_id IN (
  SELECT c.id
  FROM customers c
  WHERE c.status = 'active'
);

-- After
WITH active_customers AS (
  SELECT id
  FROM customers
  WHERE status = 'active'
)
SELECT o.id, o.total
FROM orders o
JOIN active_customers ac ON ac.id = o.customer_id;
```

### CASE consolidation

Merge repeated branching logic into a single normalized expression.

```sql
-- Before
SELECT
  CASE WHEN status = 'ok' THEN 'healthy' ELSE 'unhealthy' END AS app_health,
  CASE WHEN status = 'ok' THEN 0 ELSE 1 END AS is_unhealthy
FROM service_status;

-- After
WITH normalized AS (
  SELECT
    CASE WHEN status = 'ok' THEN 'healthy' ELSE 'unhealthy' END AS app_health
  FROM service_status
)
SELECT
  app_health,
  CASE WHEN app_health = 'healthy' THEN 0 ELSE 1 END AS is_unhealthy
FROM normalized;
```

### Join optimization through clearer join intent

Move filter predicates to the appropriate place and remove accidental cross joins.

```sql
-- Before
SELECT u.id, p.plan_name
FROM users u, plans p
WHERE u.plan_id = p.id
  AND p.active = true;

-- After
SELECT u.id, p.plan_name
FROM users u
JOIN plans p ON p.id = u.plan_id
WHERE p.active = true;
```

---

## 2. Common Anti-Patterns → Fixes

| Anti-Pattern | Why It Hurts | Simplification Direction |
|---|---|---|
| `SELECT *` in production query paths | Pulls unnecessary columns, fragile to schema drift, unclear intent | Select explicit columns needed by caller |
| Implicit conversions (`WHERE id = '123'`, mixed text/numeric/date comparisons) | Can bypass indexes and cause subtle correctness/perf issues | Use explicit casts and correct typed literals/parameters |
| Missing indexes on join/filter keys | Forces scans and makes query complexity explode under load | Add/validate indexes on frequent `JOIN`, `WHERE`, and `ORDER BY` keys |

---

## 3. Dialect-Specific Notes

### PostgreSQL
- Prefer `WITH` for readability; for performance-sensitive paths validate plans with `EXPLAIN (ANALYZE, BUFFERS)`.
- Use `FILTER (WHERE ...)` for aggregate clarity when it simplifies multiple conditional aggregates.
- Use `ILIKE` carefully; add trigram or expression indexes when case-insensitive search is hot-path.

### MySQL
- Check whether CTEs are materialized in your version/plan; derived tables may behave differently than expected.
- Watch implicit string-to-number coercions; they can produce surprising comparisons.
- Confirm index usage with `EXPLAIN FORMAT=TRADITIONAL` or `EXPLAIN ANALYZE` (MySQL 8+).

### SQLite
- Keep queries simple and explicit; planner features differ from server RDBMSs.
- Date/time handling is text/function-based; be explicit with formats/functions.
- Index support is available but limited compared with PostgreSQL/MySQL advanced indexing features.

---

## 4. When NOT to Simplify

Hold back when:

- Query shape is intentionally constrained by ORM/query-builder generation and edits would desync generated artifacts.
- Vendor-specific hints or constructs are required to preserve known production plans.
- Migration/backfill SQL is written for one-time operational safety and readability changes would add risk without clear value.
