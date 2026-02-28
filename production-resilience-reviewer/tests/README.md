# Testing the Production Resilience Reviewer Skill

This directory provides test fixtures and step-by-step instructions for verifying
that the **production-resilience-reviewer** skill works correctly in GitHub Copilot CLI.

---

## Prerequisites

- [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli) installed and authenticated
- Access to GitHub Copilot (individual, business, or enterprise subscription)

---

## Step 1: Install the skill

Copy the skill to a location where Copilot CLI knows to look for skills.

**Option A — project skill** (only available within this repository):

```bash
mkdir -p .github/skills/production-resilience-reviewer
cp production-resilience-reviewer/SKILL.md \
   .github/skills/production-resilience-reviewer/SKILL.md
```

**Option B — personal skill** (available across all your projects):

```bash
mkdir -p ~/.copilot/skills/production-resilience-reviewer
cp production-resilience-reviewer/SKILL.md \
   ~/.copilot/skills/production-resilience-reviewer/SKILL.md
```

---

## Step 2: Verify the skill is loaded

In the Copilot CLI, list available skills:

```
/skills list
```

You should see `production-resilience-reviewer` in the output. If you don't,
confirm the `SKILL.md` is in the correct location and re-run the command.

---

## Step 3: Run a quick smoke test

Invoke the skill explicitly and ask it to review one of the fixture files:

```
Use the /production-resilience-reviewer skill to review this code:

def charge_customer(customer_id, amount_cents):
    import requests
    try:
        response = requests.post(
            "https://api.stripe.com/v1/charges",
            auth=("sk_live_YOUR_KEY_HERE", ""),
            data={"amount": amount_cents, "currency": "usd", "customer": customer_id},
        )
        return response.json()
    except Exception:
        return {"error": "payment failed"}
```

**Expected findings** (the skill should surface at least):

- No timeout configured on the Stripe HTTP call (Lens 3 — **P1-HIGH**)
- No idempotency key — retrying risks double-charging (Lens 5 — **P0-CRITICAL**)
- `except Exception` swallows all errors with no context (Lens 6 — **P0-CRITICAL**)
- No metrics or structured logging (Lens 7 — **P1-HIGH**)

---

## Step 4: Test with the provided fixture files

The `fixtures/` directory contains three code samples, each seeded with known
resilience gaps. Feed them to Copilot to verify the skill's coverage:

### Fixture 1 — Payment service (`fixtures/payment-service.py`)

Trigger phrase:

```
Review fixtures/payment-service.py for production readiness.
```

Expected lenses triggered: **Dependency Failure (1)**, **Network & Latency (3)**,
**Retry & Backpressure (5)**, **Debuggability (6)**, **Observability (7)**.

### Fixture 2 — User profile handler (`fixtures/user-profile.js`)

Trigger phrase:

```
What could go wrong with this user-profile handler in production?
```

Expected lenses triggered: **Load & Concurrency (2)**, **Network & Latency (3)**,
**Data Freshness & Consistency (4)**, **Debuggability (6)**, **Observability (7)**.

### Fixture 3 — Order processor (`fixtures/order-processor.py`)

Trigger phrase:

```
Is this order-processing code production-ready? Review like a senior engineer.
```

Expected lenses triggered: **Retry & Backpressure (5)**,
**Change Management & Rollback Safety (8)**, **Fault Domains & DR (9)**,
**Security & Abuse as Reliability (10)**.

---

## Checklist: what a passing review looks like

For each fixture, a correct skill invocation should:

- [ ] State the selected review mode (**Quick** or **Full**)
- [ ] Assign P0/P1/P2/P3 priorities to each finding
- [ ] Include evidence (specific code line or pattern)
- [ ] Include a concrete recommendation
- [ ] Include a validation step (how to prove the fix works)
- [ ] Include a monitoring suggestion (metric or alert)

If any of these elements are missing, check that the SKILL.md was copied
correctly (full content, including frontmatter) and re-run `/skills list`
to confirm the skill is active.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Skill not listed by `/skills list` | Confirm `SKILL.md` is in the correct directory and the directory name matches |
| Skill triggers but gives a shallow review | Ensure the full `SKILL.md` was copied (not just the frontmatter) |
| Review mode is always Quick | Explicitly ask for a Full review: _"Give me a full production-readiness review"_ |
| Findings lack validation/monitoring steps | Invoke with: _"Use the /production-resilience-reviewer skill"_ to force skill selection |
