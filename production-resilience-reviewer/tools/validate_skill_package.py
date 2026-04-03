#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

NUM_HEADER_RE = re.compile(r"^##\s+(\d+)\.\s+")
FENCE_RE = re.compile(r"^\s*```")
ORDERED_LINE_RE = re.compile(r"^(\d+)\.\s+\S")
LENS_HEADER_RE = re.compile(r"^### Lens (\d+):")

EXPECTED_REFERENCES = [
    "references/checklist-change-management.md",
    "references/checklist-data.md",
    "references/checklist-debuggability.md",
    "references/checklist-dependency.md",
    "references/checklist-disaster-recovery.md",
    "references/checklist-load-concurrency.md",
    "references/checklist-network-latency.md",
    "references/checklist-observability.md",
    "references/checklist-quota-limit-exhaustion.md",
    "references/checklist-security-abuse-reliability.md",
    "references/severity-calibration.md",
    "references/validation-monitoring-patterns.md",
]

MAX_SKILL_LINES = 700


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

    def next_nonempty_after(line_idx: int) -> tuple[int, str] | None:
        # This search is intentionally exclusive of line_idx (starts at line_idx + 1).
        scan_idx = line_idx + 1
        while scan_idx < len(lines):
            stripped = lines[scan_idx].strip()
            if stripped:
                return scan_idx, stripped
            scan_idx += 1
        return None

    for header_line_idx, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue

        header_match = NUM_HEADER_RE.match(line.strip())
        if not header_match:
            continue

        header_num = int(header_match.group(1))
        first_candidate = next_nonempty_after(header_line_idx)
        if not first_candidate:
            continue

        first_item_line_idx, first_item_line = first_candidate
        first_item_match = ORDERED_LINE_RE.match(first_item_line)
        if not first_item_match:
            continue

        if int(first_item_match.group(1)) >= header_num + 1:
            issues.append(
                f"Possible leaked TOC title under numbered header at line {header_line_idx + 1}: '{first_item_line}'"
            )

            # Keep scanning consecutive leaked TOC entries.
            current_scan_idx = first_item_line_idx
            while True:
                next_candidate = next_nonempty_after(current_scan_idx)
                if not next_candidate:
                    break

                next_item_line_idx, next_item_line = next_candidate
                next_item_match = ORDERED_LINE_RE.match(next_item_line)
                if not next_item_match:
                    break

                if int(next_item_match.group(1)) < header_num + 1:
                    break

                issues.append(
                    f"Possible leaked TOC title under numbered header at line {header_line_idx + 1}: '{next_item_line}'"
                )
                current_scan_idx = next_item_line_idx

    return issues


def check_lens_headings(skill_md_text: str) -> list[str]:
    """Ensure SKILL.md contains Lens 1..11 headings (prevents accidental deletions)."""
    lens_nums = sorted(int(n) for n in re.findall(LENS_HEADER_RE.pattern, skill_md_text, flags=re.M))
    expected = list(range(1, 12))
    if lens_nums != expected:
        return [f"SKILL.md lens headings mismatch: found {lens_nums}, expected {expected}"]
    return []


def check_lens_spacing(skill_md_text: str) -> list[str]:
    """Require exactly one blank line immediately after each lens heading."""
    lines = skill_md_text.splitlines()
    issues: list[str] = []
    for i, line in enumerate(lines):
        if not LENS_HEADER_RE.match(line):
            continue

        blank_lines = 0
        scan_idx = i + 1
        while scan_idx < len(lines) and not lines[scan_idx].strip():
            blank_lines += 1
            scan_idx += 1

        if blank_lines != 1:
            issues.append(
                f"SKILL.md lens heading at line {i + 1} must be followed by exactly 1 blank line (found {blank_lines})."
            )
    return issues


def check_expected_references(root: Path) -> list[str]:
    """Ensure all expected reference files exist."""
    issues: list[str] = []
    for ref in EXPECTED_REFERENCES:
        if not (root / ref).exists():
            issues.append(f"Missing expected reference file: {ref}")
    return issues


def check_version_sync(root: Path) -> list[str]:
    """Ensure VERSION file and package.json version field are in sync."""
    issues: list[str] = []
    version_file = root / "VERSION"
    pkg_file = root / "package.json"

    if not version_file.exists() or not pkg_file.exists():
        return issues

    file_version = read_text(version_file).strip()
    try:
        pkg = json.loads(read_text(pkg_file))
    except json.JSONDecodeError:
        issues.append("package.json is not valid JSON.")
        return issues

    pkg_version = pkg.get("version", "")
    if pkg_version and pkg_version != file_version:
        issues.append(
            f"VERSION ({file_version}) and package.json version ({pkg_version}) are out of sync."
        )
    return issues


def check_changelog_version(root: Path) -> list[str]:
    """Ensure CHANGELOG.md includes a heading for the VERSION value."""
    issues: list[str] = []
    version_file = root / "VERSION"
    changelog_file = root / "CHANGELOG.md"

    if not version_file.exists() or not changelog_file.exists():
        return issues

    version = read_text(version_file).strip()
    headings = {f"## {version}", f"## v{version}"}
    for line in read_text(changelog_file).splitlines():
        if line.strip() in headings:
            return issues

    issues.append(
        f"CHANGELOG.md does not contain a heading for VERSION '{version}' (expected one of: {sorted(headings)})."
    )
    return issues


def check_markdown_file(path: Path, root: Path) -> list[str]:
    issues: list[str] = []
    rel = str(path.relative_to(root))
    text = read_text(path)

    if not ends_with_newline(path):
        issues.append(f"{rel}: missing trailing newline")
    if not fence_count_ok(text):
        issues.append(f"{rel}: odd number of ``` fences (unclosed code block?)")
    issues.extend(f"{rel}: {msg}" for msg in find_leaked_toc_titles(text))
    return issues


def check_skill_file(root: Path) -> list[str]:
    issues: list[str] = []
    skill = root / "SKILL.md"
    if not skill.exists():
        return ["Missing SKILL.md at package root."]

    skill_text = read_text(skill)
    line_count = len(skill_text.splitlines())
    if line_count > MAX_SKILL_LINES:
        issues.append(f"SKILL.md is {line_count} lines (> {MAX_SKILL_LINES}).")

    issues.extend(check_markdown_file(skill, root))
    issues.extend(check_lens_headings(skill_text))
    issues.extend(check_lens_spacing(skill_text))
    return issues


def validate_root(root: Path) -> list[str]:
    issues: list[str] = []
    skill = root / "SKILL.md"

    issues.extend(check_skill_file(root))
    issues.extend(check_expected_references(root))
    issues.extend(check_version_sync(root))
    issues.extend(check_changelog_version(root))

    for md_file in sorted(root.rglob("*.md")):
        if md_file == skill:
            continue
        issues.extend(check_markdown_file(md_file, root))

    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = validate_root(root)

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
