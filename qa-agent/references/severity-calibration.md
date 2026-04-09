# Severity Calibration Guide

Use severity as release-risk communication, not as blame.

| Severity | Impact | Typical Escalation Signals |
|----------|--------|----------------------------|
| Critical | User harm, data/security compromise, complete outage | auth bypass, corruption, no workaround |
| High | Core workflow broken or materially wrong | payment/order flow failure, incorrect critical result |
| Medium | Important but non-core degradation | localized correctness bug, degraded UX |
| Low | Minor friction or cosmetic issue | copy/layout inconsistency |

Adjust final severity with blast radius and detectability.
