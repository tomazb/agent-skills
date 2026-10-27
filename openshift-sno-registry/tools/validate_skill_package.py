#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

EXPECTED_NAME = "openshift-sno-registry"
FENCE_RE = re.compile(r"^\s*```")
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
README_VERSION_RE = re.compile(r"Current version:\s*\*\*(?P<version>[^*]+)\*\*")

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "VERSION",
    "CHANGELOG.md",
    "package.json",
    "references/deploy.md",
    "references/undeploy.md",
    "references/validation.md",
    "references/validated-sno.md",
    "scripts/select_registry_storage.py",
    "scripts/render_registry_pvc.py",
    "scripts/render_registry_config.py",
    "scripts/render_registry_smoke.py",
    "scripts/render_registry_push.py",
    "tools/validate_skill_package.py",
    "tools/validate_skill_package.sh",
]

REQUIRED_SKILL_SECTIONS = [
    "## Routing",
    "## Core Safety Rules",
    "## Required Source Checks",
    "## Inputs To Collect",
    "## Output Expectations",
]

REQUIRED_PHRASES = [
    "managementState",
    "Recreate",
    "image-registry-storage",
    "ReadWriteOnce",
    "ReadWriteMany",
    "openshift-lvm-storage",
    "WaitForFirstConsumer",
    "Removed",
    "100Gi",
    "defaultRoute",
    "python3 scripts/select_registry_storage.py",
    "python3 scripts/render_registry_pvc.py",
    "python3 scripts/render_registry_config.py",
    "python3 scripts/render_registry_smoke.py",
    "python3 scripts/render_registry_push.py",
    "--remove-signatures",
]

MAX_SKILL_LINES = 180
PHRASE_SCAN_EXCLUDES = {"README.md", "CHANGELOG.md"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def ends_with_newline(path: Path) -> bool:
    content = path.read_bytes()
    return not content or content.endswith(b"\n")


def fence_count_ok(text: str) -> bool:
    fences = sum(1 for line in text.splitlines() if FENCE_RE.match(line))
    return fences % 2 == 0


def parse_frontmatter(skill_text: str) -> dict[str, str] | None:
    match = FRONTMATTER_RE.match(skill_text)
    if not match:
        return None
    data: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def heading_lines(text: str) -> list[str]:
    headings: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            headings.append(line.strip())
    return headings


def check_markdown_file(path: Path, root: Path) -> list[str]:
    issues: list[str] = []
    rel = str(path.relative_to(root))
    text = read_text(path)
    if not ends_with_newline(path):
        issues.append(f"{rel}: missing trailing newline")
    if not fence_count_ok(text):
        issues.append(f"{rel}: odd number of ``` fences (unclosed code block?)")
    return issues


def check_required_files(root: Path) -> list[str]:
    return [f"Missing required file: {rel}" for rel in REQUIRED_FILES if not (root / rel).exists()]


def check_frontmatter(root: Path) -> list[str]:
    skill_file = root / "SKILL.md"
    if not skill_file.exists():
        return ["Missing SKILL.md at package root."]
    frontmatter = parse_frontmatter(read_text(skill_file))
    if frontmatter is None:
        return ["SKILL.md: missing or invalid YAML frontmatter"]
    issues: list[str] = []
    if frontmatter.get("name") != EXPECTED_NAME:
        issues.append(
            f"SKILL.md: frontmatter name '{frontmatter.get('name', '')}' does not match '{EXPECTED_NAME}'"
        )
    description = frontmatter.get("description", "")
    if not description:
        issues.append("SKILL.md: missing frontmatter description")
    elif not description.startswith("Use when"):
        issues.append("SKILL.md: description must start with 'Use when'")
    if "tools" in (frontmatter or {}):
        issues.append("SKILL.md: unexpected legacy frontmatter field 'tools'")
    return issues


def check_required_sections(skill_text: str) -> list[str]:
    present = set(heading_lines(skill_text))
    missing = [section for section in REQUIRED_SKILL_SECTIONS if section not in present]
    if missing:
        return [f"SKILL.md is missing required sections: {', '.join(missing)}"]
    return []


def check_versions_handoff(skill_text: str) -> list[str]:
    match = re.search(r"^## Required Source Checks\s*$", skill_text, re.MULTILINE)
    if not match:
        return ["SKILL.md: Required Source Checks missing openshift-versions handoff"]
    start = match.end()
    next_heading = re.search(r"^##\s+", skill_text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(skill_text)
    source_checks = skill_text[start:end]
    if "openshift-versions" not in source_checks:
        return ["SKILL.md: Required Source Checks missing openshift-versions handoff"]
    lowered = source_checks.lower()
    if "not cluster upgrade readiness" not in lowered or "release availability" not in lowered:
        return [
            "SKILL.md: Required Source Checks must clarify that release availability "
            "is not cluster upgrade readiness"
        ]
    return []


def check_version_sync(root: Path) -> list[str]:
    version_file = root / "VERSION"
    package_file = root / "package.json"
    if not version_file.exists() or not package_file.exists():
        return ["Missing VERSION or package.json."]
    version = read_text(version_file).strip()
    try:
        package_data = json.loads(read_text(package_file))
    except json.JSONDecodeError:
        return ["package.json is not valid JSON."]
    issues: list[str] = []
    if package_data.get("name") != EXPECTED_NAME:
        issues.append(
            f"package.json name '{package_data.get('name', '')}' does not match '{EXPECTED_NAME}'."
        )
    if package_data.get("version") != version:
        issues.append(
            f"VERSION ({version}) and package.json version ({package_data.get('version')}) are out of sync."
        )
    return issues


def check_changelog_version(root: Path) -> list[str]:
    version = read_text(root / "VERSION").strip() if (root / "VERSION").exists() else ""
    changelog = root / "CHANGELOG.md"
    if not changelog.exists():
        return ["Missing CHANGELOG.md file."]
    expected = {f"## {version}", f"## v{version}"}
    if any(line.strip() in expected for line in read_text(changelog).splitlines()):
        return []
    return [f"CHANGELOG.md does not contain a heading for VERSION '{version}'."]


def check_readme_version(root: Path) -> list[str]:
    readme = root / "README.md"
    version_file = root / "VERSION"
    if not readme.exists() or not version_file.exists():
        return []
    version = read_text(version_file).strip()
    match = README_VERSION_RE.search(read_text(readme))
    if match is None:
        return ["README.md: missing 'Current version: **<version>**' marker."]
    if match.group("version").strip() != version:
        return [
            f"README.md version ({match.group('version').strip()}) and VERSION ({version}) are out of sync."
        ]
    return []


def check_phrases(root: Path) -> list[str]:
    text = "\n".join(
        read_text(path)
        for path in sorted(root.rglob("*.md"))
        if path.name not in PHRASE_SCAN_EXCLUDES
    )
    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in text]
    if missing:
        return [f"Missing registry guidance: {', '.join(missing)}"]
    return []


def check_skill_file(root: Path) -> list[str]:
    skill_file = root / "SKILL.md"
    if not skill_file.exists():
        return ["Missing SKILL.md at package root."]
    issues = check_markdown_file(skill_file, root)
    skill_text = read_text(skill_file)
    if len(skill_text.splitlines()) > MAX_SKILL_LINES:
        issues.append(f"SKILL.md is longer than {MAX_SKILL_LINES} lines.")
    issues.extend(check_required_sections(skill_text))
    issues.extend(check_versions_handoff(skill_text))
    return issues


def validate_root(root: Path) -> list[str]:
    issues: list[str] = []
    issues.extend(check_required_files(root))
    issues.extend(check_frontmatter(root))
    issues.extend(check_skill_file(root))
    issues.extend(check_version_sync(root))
    issues.extend(check_changelog_version(root))
    issues.extend(check_readme_version(root))
    issues.extend(check_phrases(root))
    for md_file in sorted(root.rglob("*.md")):
        if md_file.name == "SKILL.md":
            continue
        issues.extend(check_markdown_file(md_file, root))
    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = validate_root(root)
    if issues:
        print("Validation FAILED:\n")
        for issue in issues:
            print(f"- {issue}")
        print("\nFix the issues above and re-run validation.")
        return 1
    print("Validation PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
