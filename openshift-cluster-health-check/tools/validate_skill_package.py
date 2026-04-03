#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

FENCE_RE = re.compile(r"^\s*```")
PHASE_HEADER_RE = re.compile(r"^### Phase (\d+)\b")

EXPECTED_REFERENCES = [
    "references/checklist-authentication.md",
    "references/checklist-certificates.md",
    "references/checklist-cluster-operators.md",
    "references/checklist-etcd.md",
    "references/checklist-networking.md",
    "references/checklist-nodes.md",
    "references/checklist-platform-specific.md",
    "references/checklist-pods-analysis.md",
    "references/checklist-storage.md",
    "references/output-contract.md",
    "references/severity-calibration.md",
]

MAX_SKILL_LINES = 700
EXPECTED_PHASES = list(range(0, 17))  # Phase 0 through Phase 16


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def ends_with_newline(p: Path) -> bool:
    b = p.read_bytes()
    return len(b) == 0 or b.endswith(b"\n")


def fence_count_ok(text: str) -> bool:
    fences = sum(1 for line in text.splitlines() if FENCE_RE.match(line))
    return fences % 2 == 0


def check_markdown_file(path: Path, root: Path) -> list[str]:
    issues: list[str] = []
    rel = str(path.relative_to(root))
    text = read_text(path)

    if not ends_with_newline(path):
        issues.append(f"{rel}: missing trailing newline")
    if not fence_count_ok(text):
        issues.append(f"{rel}: odd number of ``` fences (unclosed code block?)")

    return issues


def check_phase_headings(skill_md_text: str) -> list[str]:
    """Ensure SKILL.md contains Phase 0 through Phase 16 headings."""
    found = sorted(
        set(
            int(m.group(1))
            for line in skill_md_text.splitlines()
            for m in [PHASE_HEADER_RE.match(line)]
            if m
        )
    )
    if found != EXPECTED_PHASES:
        missing = sorted(set(EXPECTED_PHASES) - set(found))
        extra = sorted(set(found) - set(EXPECTED_PHASES))
        parts = []
        if missing:
            parts.append(f"missing phases: {missing}")
        if extra:
            parts.append(f"unexpected phases: {extra}")
        return [f"SKILL.md phase headings issue — {'; '.join(parts)}"]
    return []


def check_expected_references(root: Path) -> list[str]:
    return [
        f"Missing expected reference file: {ref}"
        for ref in EXPECTED_REFERENCES
        if not (root / ref).exists()
    ]


def check_version_sync(root: Path) -> list[str]:
    version_file = root / "VERSION"
    pkg_file = root / "package.json"

    if not version_file.exists() or not pkg_file.exists():
        return []

    file_version = read_text(version_file).strip()
    try:
        pkg = json.loads(read_text(pkg_file))
    except json.JSONDecodeError:
        return ["package.json is not valid JSON."]

    pkg_version = pkg.get("version", "")
    if pkg_version and pkg_version != file_version:
        return [
            f"VERSION ({file_version}) and package.json version ({pkg_version}) are out of sync."
        ]
    return []


def check_changelog_version(root: Path) -> list[str]:
    version_file = root / "VERSION"
    changelog_file = root / "CHANGELOG.md"

    if not version_file.exists() or not changelog_file.exists():
        return []

    version = read_text(version_file).strip()
    headings = {f"## {version}", f"## v{version}"}
    for line in read_text(changelog_file).splitlines():
        if line.strip() in headings:
            return []

    return [
        f"CHANGELOG.md does not contain a heading for VERSION '{version}' "
        f"(expected one of: {sorted(headings)})."
    ]


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
    issues.extend(check_phase_headings(skill_text))
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
