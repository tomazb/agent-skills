# How to Speak Winston Framework

Current version: **1.0.0**

Apply Patrick Winston's MIT presentation framework to craft talks, audit slides, coach speakers, and make ideas memorable. Covers ~90% of Winston's legendary "How to Speak" lecture across 10 systematic frameworks.

## Key Capabilities

- **Three operating modes:** Build (create talks from scratch), Audit (review existing presentations), Coach (targeted delivery improvement)
- **10 frameworks** covering Winston's full MIT lecture — from environment setup through delivery heuristics to memorable closings
- **Layered depth:** lean core instructions (<700 lines) with detailed reference files for deep dives
- **Misinterpretation guards** against 5 commonly misquoted Winston principles
- **Actionable output templates** for every framework — scripts, checklists, and structured plans

## Frameworks

| # | Framework | Phase | Purpose |
|---|---|---|---|
| 1 | Winston's Success Formula | Foundation | Philosophy and practice principles |
| 2 | Time & Place | Before | Environment and logistics setup |
| 3 | Empowerment Promise | Opening | First 60 seconds that earn the next 60 minutes |
| 4 | Four Heuristics | Mid-Talk | Cycling, fencing, verbal punctuation, questions |
| 5 | Board vs. Slides | Mid-Talk | Medium selection for teaching vs. exposing |
| 6 | Slide Crime Audit | Mid-Talk | 10 crimes that kill engagement + fixes |
| 7 | Star Framework | Stickiness | Making ideas impossible to forget |
| 8 | Props, Stories & Near-Miss | Stickiness | Physical demonstrations and boundary-setting |
| 9 | Job Talk Framework | Persuasion | Vision, proof of work, contributions structure |
| 10 | How to Stop | Closing | Final slide and verbal close |

## Operating Modes

**Build Mode** — "Help me create my talk"
Framework selection → full talk construction → opening and closing scripts.

**Audit Mode** — "Review my slides"
Slide Crime Audit first → missing framework check → prioritized fixes.

**Coach Mode** — "How do I improve my opening?"
Identify need → select 1-2 frameworks → targeted advice.

## Example Prompts

- "Help me structure a 30-minute conference talk on distributed caching"
- "Audit these slides for my quarterly business review"
- "How should I open my talk at the team offsite?"
- "Make my idea about observability-driven development stick"
- "I have a thesis defense next week — help me prepare"
- "What's wrong with ending my talk with 'any questions?'"

## Reference Files

| File | Content |
|---|---|
| `references/delivery-heuristics.md` | Worked examples for cycling, fencing, verbal punctuation, and audience questions |
| `references/slide-audit-checklist.md` | Expanded 10-crime audit with fixes, board alternatives, and the contributions pattern |
| `references/star-framework-examples.md` | Three fully worked Star framework examples across tech, research, and product domains |
| `references/talk-structure-templates.md` | Minute-by-minute outlines for keynotes, deep-dives, lightning talks, and thesis defenses |
| `references/common-mistakes.md` | Detailed corrections for 5 commonly misquoted aspects of Winston's advice |

## Validation

```bash
bash tools/validate_skill_package.sh
```

Or run the test suite:

```bash
pytest tests/ -v
```

## Version Management

```bash
python3 tools/bump_version.py 1.1.0
```

## Recent Highlights

### 1.0.0

- Full overhaul from 5 to 10 frameworks (~90% of Winston's MIT lecture)
- Added Build/Audit/Coach operating modes
- Added 5 reference files with worked examples and deep dives
- Full packaging with tests (25 passing), validation tooling, and version management
