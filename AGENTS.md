# AGENTS.md
## Repository Scope
This repository stores reusable agent skills. Each skill should live in its own directory with a `SKILL.md` file and any supporting scripts or tests nearby.

## Skill Authoring Conventions
- Write skill descriptions in `Use when...` form so they describe triggering conditions, not workflow summaries.
- Keep skill instructions concise and move heavy operational detail into scripts or tests when possible.
- When changing a skill's behavior, update the skill document and its adjacent validation/tests together.

## Python Script Conventions
- Prefer Python 3.9+ compatible code.
- Add focused unit tests for command-level behavior when changing helper scripts that call external CLIs.

## Verification
- Run the relevant local tests for the skill you changed.
- Use `python3 scripts/validate_skill_collection.py` for a broader repository validation pass when a change affects multiple skills or packaging.
