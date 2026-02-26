#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

NUM_HEADER_RE = re.compile(r"^##\s+(\d+)\.\s+")
FENCE_RE = re.compile(r"^\s*```")
ORDERED_LINE_RE = re.compile(r"^(\d+)\.\s+\S")

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def ends_with_newline(p: Path) -> bool:
    b = p.read_bytes()
    return len(b) == 0 or b.endswith(b"\n")

def fence_count_ok(text: str) -> bool:
    fences = sum(1 for line in text.splitlines() if FENCE_RE.match(line))
    return fences % 2 == 0

def find_leaked_toc_titles(text: str) -> list[str]:
    """
    Heuristic detector for the specific regression we saw:
    section-numbered items like '7. Something' appearing *immediately under* a numbered section header,
    typically matching the next section numbers.

    This avoids flagging legitimate step lists (which usually start at 1) and ignores content inside code fences.
    """
    lines = text.splitlines()
    issues: list[str] = []
    in_code = False

    def next_nonempty(idx: int) -> tuple[int, str] | None:
        j = idx + 1
        while j < len(lines):
            s = lines[j].strip()
            if s:
                return j, s
            j += 1
        return None

    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue

        m = NUM_HEADER_RE.match(line.strip())
        if not m:
            continue

        header_num = int(m.group(1))
        nxt = next_nonempty(i)
        if not nxt:
            continue
        j, s = nxt
        # If the very next non-empty line looks like a top-level section number (>= header+1),
        # it's likely a leaked TOC entry rather than an intended list.
        ml = ORDERED_LINE_RE.match(s)
        if ml:
            item_num = int(ml.group(1))
            if item_num >= header_num + 1:
                issues.append(
                    f"Possible leaked TOC title under numbered header at line {i+1}: '{s}'"
                )
                # Also check the following line, in case multiple leaked entries were pasted.
                nxt2 = next_nonempty(j)
                if nxt2:
                    _, s2 = nxt2
                    ml2 = ORDERED_LINE_RE.match(s2)
                    if ml2 and int(ml2.group(1)) >= header_num + 1:
                        issues.append(
                            f"Possible leaked TOC title under numbered header at line {i+1}: '{s2}'"
                        )
    return issues



def check_lens_headings(skill_md_text: str, errors: list[str]) -> None:
    """Ensure SKILL.md contains Lens 1..8 headings (prevents accidental deletions)."""
    import re
    lens_nums = sorted({int(n) for n in re.findall(r"^### Lens (\d+):", skill_md_text, flags=re.M)})
    expected = list(range(1, 9))
    if lens_nums != expected:
        errors.append(f"SKILL.md lens headings mismatch: found {lens_nums}, expected {expected}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues: list[str] = []

    skill = root / "SKILL.md"
    if not skill.exists():
        issues.append("Missing SKILL.md at package root.")
    else:
        lines = read_text(skill).splitlines()
        if len(lines) > 500:
            issues.append(f"SKILL.md is {len(lines)} lines (> 500).")
        if not ends_with_newline(skill):
            issues.append("SKILL.md does not end with a trailing newline.")
        if not fence_count_ok(read_text(skill)):
            issues.append("SKILL.md has an odd number of ``` fences (likely an unclosed code block).")
        issues.extend([f"SKILL.md: {msg}" for msg in find_leaked_toc_titles(read_text(skill))])

    md_files = list(root.rglob("*.md"))
    for p in md_files:
        if not ends_with_newline(p):
            issues.append(f"{p.relative_to(root)}: missing trailing newline")
        txt = read_text(p)
        if not fence_count_ok(txt):
            issues.append(f"{p.relative_to(root)}: odd number of ``` fences (unclosed code block?)")
        for msg in find_leaked_toc_titles(txt):
            issues.append(f"{p.relative_to(root)}: {msg}")

    if issues:
        print("Validation FAILED:\n")
        for msg in issues:
            print(f"- {msg}")
        print("\nFix the issues above and re-run validation.")
        return 1

    print("Validation PASSED.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
