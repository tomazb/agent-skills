# Error Path Checklist

Use this list for negative and failure-path validation.

- Dependency timeouts and partial failures.
- Permission denied and auth/authz failures.
- Upstream malformed responses and schema drift.
- Retry exhaustion and backoff behavior.
- Resource pressure (disk full, pool exhausted, quota limits).
- Correct user-facing error messages and status codes.
- Cleanup and state consistency after failure.
