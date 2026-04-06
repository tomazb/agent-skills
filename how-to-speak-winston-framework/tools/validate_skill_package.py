#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

FENCE_RE = re.compile(r"^\s*```")
FRAMEWORK_HEADER_RE = re.compile(r"^### Framework (\d+):")

EXPECTED_REFERENCES = [
    "references/delivery-heuristics.md",
    "references/slide-audit-checklist.md",
    "references/star-framework-examples.md",
    "references/talk-structure-templates.md",
    "references/common-mistakes.md",
]

REQUIRED_SECTIONS = [
    "## Role & Philosophy",
    "## Operating Modes",
    "### Build Mode",
    "### Audit Mode",
    "### Coach Mode",
    "## Framework Selection",
    "## Applicability Warnings",
    "## Misinterpretation Guards",
    "## Key Principles",
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


def check_framework_headings(skill_md_text: str) -> list[str]:
    """Ensure SKILL.md contains Framework 1..10 headings."""
    nums = sorted(
        int(n)
        for n in re.findall(FRAMEWORK_HEADER_RE.pattern, skill_md_text, flags=re.M)
    )
    expected = list(range(1, 11))
    if nums != expected:
        return [
            f"SKILL.md framework headings mismatch: found {nums}, expected {expected}"
        ]
    return []


def check_framework_spacing(skill_md_text: str) -> list[str]:
    """Require exactly one blank line immediately after each framework heading."""
    lines = skill_md_text.splitlines()
    issues: list[str] = []
    for i, line in enumerate(lines):
        if not FRAMEWORK_HEADER_RE.match(line):
            continue
        blank_lines = 0
        scan_idx = i + 1
        while scan_idx < len(lines) and not lines[scan_idx].strip():
            blank_lines += 1
            scan_idx += 1
        if blank_lines != 1:
            issues.append(
                f"SKILL.md framework heading at line {i + 1} must be followed by exactly 1 blank line (found {blank_lines})."
            )
    return issues


def check_required_sections(skill_text: str) -> list[str]:
    missing = [s for s in REQUIRED_SECTIONS if s not in skill_text]
    if not missing:
        return []
    return [f"SKILL.md is missing required sections: {', '.join(missing)}"]


def check_expected_references(root: Path) -> list[str]:
    issues: list[str] = []
    for ref in EXPECTED_REFERENCES:
        if not (root / ref).exists():
            issues.append(f"Missing expected reference file: {ref}")
    return issues


def check_version_sync(root: Path) -> list[str]:
    issues: list[str] = []
    version_file = root / "VERSION"
    pkg_file = root / "package.json"

    if not version_file.exists():
        issues.append("Missing VERSION file.")
        return issues
    if not pkg_file.exists():
        issues.append("Missing package.json file.")
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
    issues: list[str] = []
    version_file = root / "VERSION"
    changelog_file = root / "CHANGELOG.md"

    if not changelog_file.exists():
        issues.append("Missing CHANGELOG.md file.")
        return issues
    if not version_file.exists():
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
    issues.extend(check_required_sections(skill_text))
    issues.extend(check_framework_headings(skill_text))
    issues.extend(check_framework_spacing(skill_text))
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
