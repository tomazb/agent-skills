/**
 * Test fixture: user-profile.js
 *
 * A user-profile API handler with multiple intentional resilience gaps,
 * designed to exercise the production-resilience-reviewer skill across
 * several failure lenses.
 *
 * Known issues (for skill verification):
 *   - Three sequential DB queries on every request (Lens 2: Load & Concurrency)
 *   - No connection-pool limits configured (Lens 2)
 *   - No request timeout on DB calls (Lens 3: Network & Latency)
 *   - Stale permission data served from 10-minute cache (Lens 4: Data Freshness)
 *   - No structured logging or correlation IDs (Lens 6: Debuggability)
 *   - No RED metrics on this hot-path endpoint (Lens 7: Observability)
 */

const db = require("./db"); // no pool-size config
const cache = require("./cache"); // in-memory, no TTL enforcement

async function getUserProfile(req, res) {
  const userId = req.params.id;

  // Three sequential queries — no batching
  const user = await db.query("SELECT * FROM users WHERE id = ?", [userId]);
  const preferences = await db.query(
    "SELECT * FROM preferences WHERE user_id = ?",
    [userId]
  );
  const permissions = await db.query(
    "SELECT * FROM permissions WHERE user_id = ?",
    [userId]
  );

  // Permissions cached for 10 minutes with no invalidation on role change
  cache.set(`perms:${userId}`, permissions, 600);

  res.json({ user, preferences, permissions });
}

module.exports = { getUserProfile };
