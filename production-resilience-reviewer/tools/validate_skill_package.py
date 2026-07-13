#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

NUM_HEADER_RE = re.compile(r"^##\s+(\d+)\.\s+")
FENCE_RE = re.compile(r"^\s*```")
ORDERED_LINE_RE = re.compile(r"^(\d+)\.\s+\S")
LENS_HEADER_RE = re.compile(r"^### Lens (\d+):")
README_VERSION_RE = re.compile(
    r"^Current version:\s+\*\*([^*]+)\*\*$", flags=re.M
)

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
    "references/checklist-complexity-tax.md",
    "references/severity-calibration.md",
    "references/validation-monitoring-patterns.md",
]

MAX_SKILL_LINES = 700

REQUIRED_RESILIENCE_GUIDANCE_PHRASES = [
    "production architecture trade-offs affecting resilience, operability, cost, or failure modes",
    "Minimum evidence before judging",
    "team size",
    "service count",
    "ownership model",
    "deploy coupling",
    "shared data ownership",
    "request path depth",
    "traffic/cost profile",
    "platform/SRE support",
    "recent incident/on-call pain",
    "Right-Sized Resilience",
    "Would fail-fast or queue-and-reconcile be safer than retrying?",
    "Are metrics/logs useful without creating cardinality or cost blowups?",
    "Does the RPO/RTO match business impact?",
    "Does the rollout mechanism reduce net risk?",
    "Can the expensive path be bounded, simplified, or removed?",
]

REQUIRED_CORRECTNESS_GUIDANCE_PHRASES = [
    "not merely `5xx`",
    "Request and trace IDs belong in logs, traces, and error context — not metric labels",
    "Do not prescribe a numeric timeout",
    "Absence of retries is not automatically a defect",
    "do not infer authorship from code smells",
]

UNSAFE_GUIDANCE_PATTERNS = [
    "If 3+ of these 11 signals",
    "├─ 5xx → Retry with backoff",
    "retry only at outermost layer",
    "Logs, metrics, and error payloads include the same primary request identifier",
    "If a label can have more than ~100 unique values",
    "load test at 1×/5×/10×",
    "at least quarterly for critical paths",
    "30-50% on critical dependencies",
    "timeout=5, idempotency_key=request_id",
    "@retry(",
]

UNSUPPORTED_COMPLEXITY_CLAIMS = [
    "DZone 2024",
    "CNCF 2025 Survey",
    "35%",
    "42%",
    "3.75x",
    "3.75×",
    "6x",
    "6×",
]


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
    Detect section-numbered TOC entries accidentally pasted immediately below a
    numbered section header. Ignore content inside fenced code blocks.
    """
    lines = text.splitlines()
    issues: list[str] = []
    in_code = False

    def next_nonempty_after(line_idx: int) -> tuple[int, str] | None:
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
                "Possible leaked TOC title under numbered header at "
                f"line {header_line_idx + 1}: '{first_item_line}'"
            )

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
                    "Possible leaked TOC title under numbered header at "
                    f"line {header_line_idx + 1}: '{next_item_line}'"
                )
                current_scan_idx = next_item_line_idx

    return issues


def check_lens_headings(skill_md_text: str) -> list[str]:
    """Ensure SKILL.md contains Lens 1..12 headings."""
    lens_nums = sorted(
        int(n) for n in re.findall(LENS_HEADER_RE.pattern, skill_md_text, flags=re.M)
    )
    expected = list(range(1, 13))
    if lens_nums != expected:
        return [
            f"SKILL.md lens headings mismatch: found {lens_nums}, expected {expected}"
        ]
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
                f"SKILL.md lens heading at line {i + 1} must be followed by "
                f"exactly 1 blank line (found {blank_lines})."
            )
    return issues


def check_expected_references(root: Path) -> list[str]:
    """Ensure all expected reference files exist."""
    issues: list[str] = []
    for ref in EXPECTED_REFERENCES:
        if not (root / ref).exists():
            issues.append(f"Missing expected reference file: {ref}")
    return issues


def check_resilience_guidance_guards(
    skill_md_text: str, complexity_reference_text: str
) -> list[str]:
    """Guard Lens 12 evidence calibration and weak complexity-tax claims."""
    issues: list[str] = []
    normalized_skill_text = " ".join(skill_md_text.split())

    for phrase in REQUIRED_RESILIENCE_GUIDANCE_PHRASES:
        if phrase not in normalized_skill_text:
            if phrase == REQUIRED_RESILIENCE_GUIDANCE_PHRASES[0]:
                issues.append(
                    "SKILL.md: description must target production architecture trade-offs "
                    "affecting resilience, operability, cost, or failure modes."
                )
            else:
                issues.append(f"SKILL.md: missing resilience guidance phrase: {phrase}")

    found_unsupported = [
        claim for claim in UNSUPPORTED_COMPLEXITY_CLAIMS if claim in complexity_reference_text
    ]
    if found_unsupported:
        issues.append(
            "references/checklist-complexity-tax.md: unsupported complexity-tax claim(s): "
            + ", ".join(found_unsupported)
        )

    return issues


def check_correctness_guidance_guards(
    skill_md_text: str, reference_texts: dict[str, str]
) -> list[str]:
    """Prevent regressions to unsafe universal retry, metric, SLO, and provenance rules."""
    issues: list[str] = []
    normalized_skill_text = " ".join(skill_md_text.split())

    for phrase in REQUIRED_CORRECTNESS_GUIDANCE_PHRASES:
        if phrase not in normalized_skill_text:
            issues.append(f"SKILL.md: missing correctness guidance phrase: {phrase}")

    documents = {"SKILL.md": skill_md_text, **reference_texts}
    for path, text in documents.items():
        for pattern in UNSAFE_GUIDANCE_PATTERNS:
            if pattern in text:
                issues.append(f"{path}: unsafe resilience guidance pattern: {pattern}")

    return issues


def check_version_sync(root: Path) -> list[str]:
    """Ensure VERSION and package.json version are in sync."""
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
    """Ensure CHANGELOG.md includes a heading for VERSION."""
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
        f"CHANGELOG.md does not contain a heading for VERSION '{version}' "
        f"(expected one of: {sorted(headings)})."
    )
    return issues


def check_readme_version(root: Path) -> list[str]:
    """Require README.md and keep its Current version marker in sync with VERSION."""
    readme_file = root / "README.md"
    version_file = root / "VERSION"

    if not readme_file.exists():
        return ["Missing README.md file."]
    if not version_file.exists():
        return []

    match = README_VERSION_RE.search(read_text(readme_file))
    if not match:
        return [
            "README.md does not contain a 'Current version: **<version>**' marker."
        ]

    readme_version = match.group(1).strip()
    version = read_text(version_file).strip()
    if readme_version != version:
        return [
            f"README.md current version ({readme_version}) and VERSION ({version}) "
            "are out of sync."
        ]
    return []


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
    issues.extend(check_readme_version(root))

    complexity_ref = root / "references/checklist-complexity-tax.md"
    if skill.exists() and complexity_ref.exists():
        issues.extend(
            check_resilience_guidance_guards(
                read_text(skill), read_text(complexity_ref)
            )
        )

    if skill.exists():
        reference_texts = {
            ref: read_text(root / ref)
            for ref in EXPECTED_REFERENCES
            if (root / ref).exists()
        }
        issues.extend(
            check_correctness_guidance_guards(read_text(skill), reference_texts)
        )

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
