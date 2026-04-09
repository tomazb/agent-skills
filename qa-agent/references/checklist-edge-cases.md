# Edge Case Checklist

Use this list when expanding a test matrix.

- Empty, null, missing, malformed, and wrong-type inputs.
- Boundary values (min, max, off-by-one, overflow/underflow).
- Locale/timezone/date transitions (DST and leap boundaries).
- Unicode and non-ASCII text handling.
- Large payloads and repeated requests.
- Duplicate submission and idempotency checks.
- Invalid state transitions and cancellation/retry loops.
