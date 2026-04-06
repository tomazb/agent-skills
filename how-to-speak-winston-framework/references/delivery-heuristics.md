# Delivery Heuristics Reference

## Related Frameworks
- Framework 4: Four Heuristics

## 1. Cycling

Revisit key ideas multiple times throughout a talk. People "fog out" — cycling gives them multiple chances to grasp the idea. Each cycle should add depth or a new angle, not merely repeat.

**Heuristic:** Plan 3 passes of your core thesis — introduction (what), middle (how), and close (why it matters).

**Worked example:** In a 30-minute talk on event-driven architecture:
- Minute 5: "Event-driven means services react to what happened, not what might happen." (introduce concept)
- Minute 15: "Here's how the order service publishes an event and the inventory service subscribes." (show mechanism)
- Minute 25: "This is why event-driven outperforms request-reply at scale — loose coupling means independent deployment." (connect to value)

**Anti-pattern:** Repeating the same sentence verbatim. Cycling adds depth each pass — if it sounds identical, you're repeating, not cycling.

## 2. Building a Fence

Define what your idea IS and IS NOT. This prevents the audience from confusing it with neighboring concepts.

**Heuristic:** For every core idea, state one explicit "this is NOT" boundary.

**Worked example:** "Event sourcing stores every state change as an immutable event. It is NOT the same as event-driven architecture — you can have event-driven systems without event sourcing, and vice versa."

**Anti-pattern:** Fencing too broadly ("this is not like anything else") or too narrowly ("this differs from X in parameter Y"). The fence should prevent the single most likely confusion.

## 3. Verbal Punctuation

Use explicit verbal signals at every transition. These help fogged-out listeners "get back on the bus."

**Effective phrases:**
- "The key takeaway here is..."
- "Now let's shift to..."
- "So to summarize this section..."
- "The important thing to notice is..."
- "Here's where it gets interesting..."
- "Let me pause and highlight..."
- "Before we move on, remember..."
- "The reason this matters is..."

**Heuristic:** Insert verbal punctuation at every topic shift and before every key point. If you wouldn't send an email without paragraph breaks, don't give a talk without verbal punctuation.

**Anti-pattern:** Filler words masquerading as punctuation. "Um", "so", "basically", "like" are not verbal punctuation — they signal uncertainty, not structure.

## 4. Asking Questions

Re-engage a distracted audience by asking a question and waiting for an answer.

**The 7-second rule:** After asking, wait a full 7 seconds. It feels eternal but gives people time to formulate an answer. Counting silently to 7 forces you to wait long enough.

**Difficulty calibration (the Goldilocks zone):**
- Too easy: "Does anyone use email?" → insulting, no engagement
- Too hard: "What's the time complexity of this algorithm?" → silence, embarrassment
- Just right: "What would happen if this service went down for 5 minutes?" → makes them think, answer is reachable

**Heuristic:** Plan 2-3 audience questions per 20 minutes. Place them after key concepts (tests understanding) or before transitions (re-engages attention).

**Anti-pattern:** Rhetorical questions with no pause. If you ask "Isn't that interesting?" and immediately continue, you've wasted the technique. Real questions demand real pauses.

## Combining Heuristics

The four heuristics work best together. A typical 5-minute segment might flow:

1. **Verbal punctuation** → "The key idea in this section is..."
2. **Fence** → "This is X. It is NOT Y."
3. **Core explanation** → teach the concept
4. **Question** → "What would happen if...?" (wait 7 seconds)
5. **Cycle marker** → "This connects back to our earlier point about..."

## Common Mistakes

| Mistake | Why It Fails | Fix |
|---|---|---|
| Cycling without adding depth | Sounds like a broken record | Each pass adds a new angle: what → how → why |
| Fencing too broadly | Doesn't prevent the actual confusion | Fence against the one most likely mix-up |
| Verbal filler as punctuation | Signals uncertainty, not structure | Replace "so, um" with "The key point is..." |
| Asking then not waiting | Teaches audience to ignore questions | Count to 7. Every time. |
| Too many questions | Feels like an exam, not a talk | 2-3 per 20 minutes maximum |

## Quick Self-Check

Before delivering, verify:
- [ ] Core thesis appears at least 3 times, each with increasing depth
- [ ] Every key concept has one "this is NOT" fence
- [ ] Every topic transition has explicit verbal punctuation
- [ ] 2-3 real questions planned per 20 minutes, with pauses marked in notes
- [ ] No section longer than 10 minutes without at least one heuristic applied
