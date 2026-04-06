# Star Framework Examples Reference

## Related Frameworks
- Framework 7: Star Framework

## How to Use These Examples

Each example shows all five Star elements applied to a real presentation topic. Use these as patterns — adapt the structure, not the content, to your own topic.

## Example 1: Technical Talk — "Why We Migrated to Event Sourcing"

**SYMBOL:** A ledger book — every page records what happened, pages are never torn out or rewritten.

**SLOGAN:** "Store what happened, not where you are."

**SURPRISE:** Most teams that adopt event sourcing don't do it for the event replay — they do it because it eliminates the arguments about what the "correct" current state is. The audit trail is the real product.

**SALIENT IDEA:** Your system's history IS its most valuable data asset — treating current state as the primary artifact throws away the information you need most during incidents and disputes.

**STORY:** "Last year our payments team spent 3 weeks investigating a billing discrepancy. We had the current balance but no record of how we got there. Every team had a different theory. After migrating to event sourcing, a similar issue took 20 minutes to resolve — we just replayed the events and watched the balance diverge at step 47. The system told us exactly what happened."

**HOW THEY WORK TOGETHER:** The ledger symbol makes the concept tangible. The slogan captures the paradigm shift in seven words. The surprise reframes the value proposition (it's about audit, not replay). The salient idea elevates it from a technique to a principle. The story makes it personal, specific, and memorable — "step 47" is the detail that sticks.

## Example 2: Research Presentation — "Attention Is Not What You Think"

**SYMBOL:** A spotlight that can only illuminate one thing at a time — but someone else is controlling the spotlight.

**SLOGAN:** "Attention is allocated, not directed."

**SURPRISE:** People don't choose what to pay attention to — their environment chooses for them. The feeling of "deciding to focus" is largely post-hoc rationalization.

**SALIENT IDEA:** Designing for attention means designing the environment, not asking people to try harder.

**STORY:** "We ran an experiment where participants watched a video and were told to count basketball passes. 50% didn't notice a person in a gorilla suit walk through the scene. This isn't a failure of attention — it's attention working exactly as designed. The task environment allocated their spotlight. When we changed the instructions to 'watch for anything unusual,' 90% saw the gorilla. Same video. Same people. Different environment."

**HOW THEY WORK TOGETHER:** The spotlight symbol makes the abstract concept of attention concrete and controllable. The slogan reframes agency ("allocated" not "directed"). The surprise challenges the deeply held belief that we control our focus. The salient idea turns it actionable — design environments, don't blame users.

## Example 3: Product Pitch — "Why Your Monitoring Is Lying to You"

**SYMBOL:** A smoke detector with no batteries — it looks like protection, but it's decoration.

**SLOGAN:** "Dashboards without alerts are decoration."

**SURPRISE:** Most teams have more monitoring than they can act on. The problem isn't too little data — it's that the data doesn't connect to decisions. Adding more metrics makes this worse, not better.

**SALIENT IDEA:** Monitoring exists to trigger decisions, not to display numbers. Every metric without a defined action threshold is waste.

**STORY:** "A customer had 47 Grafana dashboards. During their last outage, no one looked at any of them — they found out from Twitter. We asked them to list every dashboard that had changed an on-call engineer's behavior in the last month. The answer was three. We helped them delete the other 44 and add alert rules to the three that mattered. Their mean time to detection dropped from 23 minutes to 90 seconds."

**HOW THEY WORK TOGETHER:** The smoke detector without batteries is instantly visual and slightly uncomfortable — it looks safe but isn't. The slogan is quotable in any meeting. The surprise (more monitoring = worse) challenges the default instinct. The story has specific numbers (47 dashboards, 3 useful, 23 min → 90 sec) that make it credible and memorable.

## Example 4: Leadership Talk — "Why Good Engineers Leave"

**SYMBOL:** A leaking bucket — you keep pouring water in (hiring) but never fix the holes (retention).

**SLOGAN:** "Retention is a feature, not a perk."

**SURPRISE:** Exit interview data shows the top reason engineers leave isn't compensation — it's the feeling that their work doesn't matter. Teams with clear impact narratives retain 2x better than teams with higher pay but unclear purpose.

**SALIENT IDEA:** Engineers don't leave companies; they leave environments where they can't see the impact of their work.

**STORY:** "We had two teams with identical compensation bands. Team A shipped to production weekly and saw user metrics move. Team B worked on a platform rewrite with no user-facing changes for 8 months. Team A had 5% attrition. Team B had 40%. When we gave Team B a dashboard showing how their platform work reduced deploy times for other teams, attrition dropped to 10% in one quarter. Same engineers. Same pay. Different visibility into impact."

**HOW THEY WORK TOGETHER:** The leaking bucket is visceral — everyone has seen one. The slogan reframes retention from HR territory to engineering territory. The surprise contradicts the common assumption that pay drives retention. The story with parallel teams and specific numbers (5% vs 40% vs 10%) makes the case undeniable.

## Common Star Framework Failures

| Element | Failure Mode | How to Fix |
|---|---|---|
| Symbol | Abstract noun ("innovation", "synergy") | Must be a PHYSICAL OBJECT you can picture |
| Slogan | Requires context to understand | Must work when repeated in a meeting with no slides |
| Surprise | "Interesting" instead of challenging | Must actively CONTRADICT an assumption the audience holds |
| Salient Idea | Two ideas disguised as one (connected by "and") | If it has "and", split it. Pick the stronger half. |
| Story | Too generic ("a company had a problem") | Needs specific details (names, numbers, moments) |
| Story | Too specific (inside jargon, niche details) | Must resonate beyond the immediate audience |

## Star Element Quick Tests

- **Symbol test:** Can you draw it in 5 seconds? If not, it's too abstract.
- **Slogan test:** Say it to someone with no context. Do they want to hear more?
- **Surprise test:** Does the audience's face change? If they nod along, it's not a surprise.
- **Salient test:** Can you say it in one breath? If it needs "and", it's two ideas.
- **Story test:** Does it have at least one specific number or name? If not, add one.
