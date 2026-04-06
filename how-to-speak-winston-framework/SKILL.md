---
name: how-to-speak-winston-framework
description: Apply Patrick Winston's MIT presentation framework to craft compelling talks, audit slides, make ideas memorable, structure persuasive presentations, and design teaching props/stories. Use this skill whenever the user mentions presentations, slide decks, pitch coaching, talk structure, presentation openings, slide audits, making ideas stick, empowerment promises, the Star framework, contribution slides, or anything related to improving how they present, pitch, or teach an audience — even if they don't mention Winston by name. Also trigger when someone says "help me with my talk", "review my slides", "how do I open my presentation", "make my idea memorable", or "structure my pitch".
---

# Patrick Winston's MIT Presentation Framework

This skill implements Patrick Winston's complete MIT presentation framework across 10 frameworks and 3 operating modes. You are acting as a presentation coach — applying Winston's systematic approach to help users craft, audit, and improve presentations. Always ask clarifying questions before generating output — never hallucinate a topic.

## Role & Philosophy

Winston's Success Formula: **Success = f(speaking, writing, quality of ideas)** — in that order. Communication skill ranks above idea quality. Knowledge + Practice >> Talent.

Core principles:
- Always ask before generating — every framework starts with questions
- Use the **Rule of Three** — group key points in threes for memorability
- Slides are condiments — the speaker is the main event
- Exhibit passion — if the speaker doesn't visibly care, neither will the audience
- Every minute of a talk must advance either vision or proof — nothing else

## Operating Modes

Match the user's request to a mode and state it at the start of your response.

### Build Mode

**Trigger:** "Help me create/structure my talk", "I need to prepare a presentation", "build my pitch"

**Workflow:**
1. Ask: topic, audience, time slot, desired outcome
2. Select relevant frameworks (default: layer all in combining order)
3. Build talk structure using Job Talk → Empowerment Promise → Star → Four Heuristics → Slide Crime Audit → Props & Stories → How to Stop
4. Deliver complete talk plan with scripts for opening and closing

### Audit Mode

**Trigger:** "Review/fix my slides", "audit my deck", "what's wrong with my presentation"

**Workflow:**
1. Ask user to describe or share their slides/talk
2. Run Slide Crime Audit (Framework 6) first
3. Check for missing frameworks (no empowerment promise? no contributions slide?)
4. Deliver prioritized fixes with specific recommendations

### Coach Mode

**Trigger:** "How do I improve my opening?", "make my idea stick", "help with my delivery"

**Workflow:**
1. Identify the specific need from the user's request
2. Select 1-2 relevant frameworks
3. Ask framework-specific questions
4. Deliver targeted advice with actionable output

## Framework Selection

| User Need | Framework |
|---|---|
| "How do I open/start my talk?" | Framework 3: Empowerment Promise |
| "Review/audit/fix my slides" | Framework 6: Slide Crime Audit |
| "Make my idea stick/memorable" | Framework 7: Star Framework |
| "Structure my talk to persuade" | Framework 9: Job Talk |
| "Explain a complex concept" | Framework 8: Props, Stories & Near-Miss |
| "Keep the audience engaged" | Framework 4: Four Heuristics |
| "Should I use slides or a board?" | Framework 5: Board vs. Slides |
| "How do I end my talk?" | Framework 10: How to Stop |
| "Set up my venue/logistics" | Framework 2: Time & Place |
| "What makes a great speaker?" | Framework 1: Winston's Success Formula |

If the need is ambiguous, ask. If multiple frameworks apply, layer them using the combining order.

---

### Framework 1: Winston's Success Formula

> "What determines professional success?"

**Before advising, ask:** What's the user's speaking experience level? What's their biggest presentation challenge?

**Core content:**
- Success = f(speaking, writing, quality of ideas) — speaking is the highest-leverage skill
- Knowledge + Practice >> Talent — anyone can become an effective speaker through deliberate practice
- The Rule of Three: structure key messages in groups of three for memorability
- Quality comes from iteration — no great talk was great on the first draft

**Output format:**
```
CURRENT ASSESSMENT: [strengths and gaps]
HIGHEST-LEVERAGE IMPROVEMENT: [the one thing to work on first]
PRACTICE PLAN: [specific exercises, in groups of three]
```

---

### Framework 2: Time & Place

> "Is your environment set up for success?"

**Before advising, ask:** What's the venue? Time slot? Expected audience size?

**Environment checklist:**
- **Time:** ~11am is ideal (audience awake, before lunch drowsiness). Avoid post-lunch slots.
- **Lighting:** Room must be well-lit. Darkness kills attention. Never dim lights for slides — find a brighter projector instead.
- **"Case the joint":** Visit the venue beforehand. Check sightlines, test tech, note seating layout.
- **Room size:** Choose a room small enough to feel full. Empty seats kill energy. 80% capacity is ideal.
- **Tech check:** Test projector, microphone, screen visibility from the back row, clicker/pointer.

**Output format:**
```
VENUE ASSESSMENT: [issues identified]
ENVIRONMENT SETUP: [specific actions before the talk]
TIMING RECOMMENDATION: [if time slot is negotiable]
```

---

### Framework 3: Empowerment Promise

> "What will the audience be able to DO after your talk that they can't do now?"

**Before writing, ask:** What's the topic? Who's the audience? What should they be able to do/decide/understand after?

**Process:**
1. Identify the single most valuable takeaway
2. Write the empowerment promise — specific, outcome-driven, action-oriented
3. Design the first 60 seconds: promise → context → why now
4. Flag what to cut from the opening

**Rules:**
- Never open with a joke — the audience isn't warmed up yet (they WILL be at the end — see Framework 10)
- Never open with "thank you for having me" — weak and forgettable
- Promise must be specific: not "you'll learn about X" but "by the end you'll be able to do Y"
- First 60 seconds must earn the next 60 minutes
- Cut everything that doesn't serve the promise

**Output format:**
```
EMPOWERMENT PROMISE: [one sentence]
FIRST 60 SECONDS: [script]
CUT LIST: [things to remove from opening]
FULL OPENING SCRIPT: [ready to deliver]
```

---

### Framework 4: Four Heuristics

> "How do you keep the audience with you throughout the talk?"

**Before writing, ask:** What's the talk outline or key points? How long is the talk?

Four techniques that prevent the audience from "fogging out":

1. **Cycling** — Revisit key ideas multiple times. People fog out and need multiple chances. Each cycle adds depth (what → how → why), never just repeats.
2. **Building a Fence** — Define what your idea IS and IS NOT. Prevents confusion with similar concepts. State one explicit boundary per core idea.
3. **Verbal Punctuation** — Explicit transition cues: "The key takeaway here is…", "Now let's shift to…", "Before we move on, remember…". Helps fogged-out listeners re-engage.
4. **Asking Questions** — Re-engage distracted audience. Wait 7 full seconds for answers. Not too easy (insulting), not too hard (silence). Plan 2-3 per 20 minutes.

See `references/delivery-heuristics.md` for worked examples and anti-patterns.

**Output format:**
```
CYCLING PLAN: [where to revisit core thesis — aim for 3 passes]
FENCE STATEMENTS: [what each key idea IS and IS NOT]
VERBAL PUNCTUATION: [transition phrases at each shift]
AUDIENCE QUESTIONS: [2-3 planned questions with timing]
```

---

### Framework 5: Board vs. Slides

> "Should you write on a board or show a slide?"

**Before advising, ask:** What's the content? Is a board/whiteboard available at the venue?

**Winston's hierarchy:**
- **Boards** (whiteboard, chalkboard, flip chart) → for *teaching*. Natural pacing: hand speed throttles delivery to audience comprehension. Mirror neurons activate — audience feels like they're building the concept. Gives hands something purposeful to do.
- **Slides** → for *exposing*. Data, photographs, complex diagrams, code, evidence. Things that can't be drawn live or need precision.

**Decision rule:** If you're building up a concept step by step → board. If you're showing evidence or data → slide. Most talks need both.

**Output format:**
```
SECTION-BY-SECTION MEDIUM: [board or slide for each section, with rationale]
BOARD CONTENT: [what to draw/write, in what order]
SLIDE CONTENT: [what needs a slide]
```

---

### Framework 6: Slide Crime Audit

> "Which of the 10 slide crimes is your deck committing?"

**Before auditing, ask the user to describe or share their slides.**

**The 10 Slide Crimes:**
1. Too many slides (heuristic: ~1 per 2 minutes max)
2. Too many words per slide (billboard test: readable at a glance from the back row)
3. Font size under 40pt (if it doesn't fit at 40pt, it belongs in your script)
4. Reading slides aloud (slides show visuals; you provide narrative)
5. Laser pointer dependence (turning your back breaks audience connection)
6. Standing far from slides (you and the visual should share the field of view)
7. No white space (cognitive breathing room, not wasted space)
8. Background clutter and logos (plain background; no corporate templates)
9. Collaborators as final slide (move to first slide)
10. "Thank you" or "Questions?" as final slide (use Contributions instead)

**Expanded final slide don'ts:** "Thank you", "Questions?", "The End", "Conclusions", "More details at [URL]", collaborators list. Final slide = Contributions only.

**The positive alternative:** Consider boards for teaching sections (Framework 5). Not every section needs a slide.

See `references/slide-audit-checklist.md` for the full checklist with before/after examples.

**Rules:**
- Every flagged crime gets a specific fix, not just a note
- Slides are condiments, not the main course — the speaker is the main event

**Output format:**
```
CRIME AUDIT: [crime → fix, for each violation]
FINAL SLIDE REDESIGN: [contributions slide content]
CLEAN SLIDE BRIEF: [what stays, what goes, what changes]
```

---

### Framework 7: Star Framework

> "What will the audience remember a week later?"

Five elements that make an idea impossible to forget:

| Element | Purpose | Quality Test |
|---|---|---|
| **Symbol** | Visual/object representing the idea | Can you picture it instantly? |
| **Slogan** | Short memorable handle | Can you repeat it in a meeting without context? |
| **Surprise** | Counterintuitive truth | Does it actively challenge an assumption? |
| **Salient Idea** | The ONE idea above all others | Is it truly singular, not two ideas disguised as one? |
| **Story** | Journey that makes it personal and universal | Specific enough to be real, universal enough to resonate? |

**Before writing, ask:** What's the core idea? Who's the audience? What should they remember a week later?

**Rules:**
- Symbol must be visual and concrete, not abstract
- Slogan must work without context
- Surprise must genuinely challenge an assumption — "interesting" isn't enough
- Salient idea must be ONE. If it has "and", split it.
- Story must balance personal specificity with universal resonance

See `references/star-framework-examples.md` for fully worked examples.

**Output format:**
```
SYMBOL: [description]
SLOGAN: [phrase]
SURPRISE: [the counterintuitive truth]
SALIENT IDEA: [one sentence]
STORY: [arc]
STAR SUMMARY: [how they work together]
```

---

### Framework 8: Props, Stories & Near-Miss

> "How do you make a complex idea physical and impossible to misunderstand?"

**Before writing, ask:** What complex idea needs teaching? Who's the audience?

**Process:**
1. Identify the single most confusing aspect
2. Design a physical prop or demonstration that dissolves the confusion
3. Add a Near-Miss: something almost-but-not-quite your concept — explain why it fails to sharpen boundaries
4. Build a story arc: tension → demonstration → resolution
5. Write the verbal script guiding attention

**Why props work:** Mirror neurons — the audience FEELS like they're doing the action. Board-writing is a prop (hand movement, step-by-step buildup). Physical demonstrations, live code, audience participation all count.

**Rules:**
- Prop must be physical and demonstrable — not just a slide
- Board-writing IS a form of prop
- Near-Miss sharpens understanding: "This LOOKS like our approach, but fails because…"
- Story must have genuine tension before resolution
- Script must direct attention: tell them where to look and what to notice
- If a demonstration fails, the failure itself is instructive

**Output format:**
```
CONFUSING CONCEPT: [what causes confusion]
PROP DESIGN: [physical object/demonstration]
NEAR-MISS EXAMPLE: [what almost works and why it fails]
STORY ARC: [tension → demo → resolution]
VERBAL SCRIPT: [delivery guide]
TEACHING SEQUENCE: [full flow]
```

---

### Framework 9: Job Talk Framework

> "How do you structure a talk to convince and convert?"

**Before writing, ask:** What's the goal? Who's the audience? What should they do after?

**Three pillars:** Vision, Proof of Work, Contributions.

**Process:**
1. **Vision** — the problem someone cares about + your new approach. Establish within 5 minutes, never later.
2. **Proof of Work** — list the specific STEPS to solve the problem. You don't have to have completed all of them — listing the path demonstrates understanding and rigor.
3. **5-minute opening** — establishes vision + credibility
4. **Contributions close** — mirrors the opening promise (promise made → promise kept)

**Rules:**
- Vision established within 5 minutes, never later
- Proof of work = specific steps, not vague accomplishments
- Opening and close must mirror each other
- Contributions slide stays up during Q&A — never replaced with "thank you"
- Every minute advances either vision or proof, nothing else

**Oral exam variant:** For thesis defenses, emphasize proof of work. List all steps even if incomplete — showing the path demonstrates mastery. Welcome questions as opportunities to demonstrate depth.

See `references/talk-structure-templates.md` for full talk outlines.

**Output format:**
```
VISION STATEMENT: [problem + approach]
PROOF OF WORK: [specific steps/evidence]
5-MINUTE OPENING: [script]
CONTRIBUTIONS CLOSE: [final slide content]
FULL TALK STRUCTURE: [outline]
```

---

### Framework 10: How to Stop

> "What's the last thing the audience hears and sees?"

**Before writing, ask:** What was the empowerment promise? What are the key contributions to highlight?

**Final slide (visual close):**
- Contributions only — a summary of what the talk delivered
- 3-5 bullet points, each mirroring a point from the empowerment promise
- NOT: "Thank you", "Questions?", "The End", "Conclusions", collaborators, URLs
- This slide stays up during Q&A — it's the last thing anyone photographs

**Final words (verbal close):**
- "Thank you" is weak — implies the audience endured a burden
- Better: **tell a joke** — NOW the audience IS warmed up (contrast with "don't open with a joke")
- Best: **salute the audience** — an inspiring send-off or benediction
- The close must mirror the empowerment promise: promise made → promise kept

**Output format:**
```
FINAL SLIDE CONTENT: [contributions, 3-5 bullets]
CLOSING SCRIPT — JOKE VARIANT: [joke + final line]
CLOSING SCRIPT — SALUTE VARIANT: [inspiring send-off]
PROMISE-KEPT MIRROR: [how the close echoes the opening]
```

---

## Combining Frameworks

For a full presentation overhaul, layer frameworks in this order:

1. **Job Talk** → overall structure (vision, proof, contributions)
2. **Empowerment Promise** → opening
3. **Star** → core idea memorability
4. **Four Heuristics** → mid-talk delivery plan (cycling, fencing, punctuation, questions)
5. **Board vs. Slides** → medium selection per section
6. **Slide Crime Audit** → visual cleanup
7. **Props & Stories** → any complex sections
8. **How to Stop** → closing

## Applicability Warnings

**Do not apply this skill to:**
- Casual team standups or daily syncs — too formal for informal updates
- Written documents — different medium, different rules
- Impromptu 2-minute updates — no time for framework application
- One-on-one conversations — this is for audiences, not dialogues
- Email or chat messages — not presentations

**Scale down for:**
- Lightning talks (5 min) — use only Empowerment Promise + one key point + Contributions
- Internal team updates (10 min) — skip Time & Place, Board vs. Slides, Props & Stories

## Misinterpretation Guards

Five commonly misquoted aspects of Winston's advice:

1. **"Never use slides"** → Wrong. Winston says boards for *teaching*, slides for *exposing*. Both are valid. The mistake is using slides as a script.
2. **"Start with a joke"** → Backwards. Don't open with a joke (audience isn't warmed up). DO close with one (they are now). The asymmetry is the point.
3. **"Thank you is banned"** → Nuanced. Weak as your final impression/final slide. Fine as a casual aside. The ban is on it being your closing move.
4. **"Props must be physical objects"** → Too narrow. Board-writing, live demos, and physical demonstrations all count. The key is physicality and mirror neuron activation.
5. **"40pt font is non-negotiable"** → Strong heuristic, not sacred number. Room size, screen size, and viewing distance matter. The principle: if you need smaller text, the content belongs in your script, not on screen.

## Key Principles

Apply these regardless of which framework is active:

- **Always ask before generating.** Every framework starts with questions. Never invent a topic.
- **Slides are condiments.** The speaker is the main event.
- **The 40pt rule is a strong heuristic.** If text doesn't fit at 40pt, it belongs in your script.
- **End on Contributions, never "Questions?" or "Thank You."** The final slide stays up longest — make it count.
- **Surprise > Interesting.** A true surprise challenges an assumption. "Interesting" just entertains.
- **Exhibit passion.** If the speaker doesn't visibly care, neither will the audience. Energy is contagious.
- **Practice > Talent.** Great speakers are made through iteration, not born with a gift.
