#!/usr/bin/env python3
from __future__ import annotations

import json
import py_compile
import re
import subprocess
from pathlib import Path

FENCE_RE = re.compile(r"^\s*```")
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.S)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
README_VERSION_RE = re.compile(r"^Current version:\s+\*\*(?P<version>[^*]+)\*\*$", re.M)
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "VERSION",
    "CHANGELOG.md",
    "package.json",
    "tools/validate_skill_package.py",
    "tools/validate_skill_package.sh",
    "tools/bump_version.py",
    "tests/conftest.py",
    "tests/test_validator_markdown_checks.py",
    "tests/test_validator_structure.py",
    "tests/test_validator_versions.py",
    "tests/test_skill_baseline.md",
]

REQUIRED_SECTIONS = [
    "## Why this skill exists",
    "## Default stance",
    "## Decision lenses",
    "## Response pattern",
    "## After the user responds",
]

EXPECTED_LENSES = [
    "### Evidence Lens",
    "### Scope Lens",
    "### Timing Lens",
    "### Complexity Lens",
    "### Reversibility Lens",
    "### Opportunity Cost Lens",
]

MAX_SKILL_LINES = 160


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def ends_with_newline(path: Path) -> bool:
    content = path.read_bytes()
    return not content or content.endswith(b"\n")


def fence_count_ok(text: str) -> bool:
    fences = sum(1 for line in text.splitlines() if FENCE_RE.match(line))
    return fences % 2 == 0


def normalize_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def extract_frontmatter_fields(skill_text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(skill_text)
    if not match:
        return {}

    fields: dict[str, str] = {}
    lines = match.group("body").splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        if ":" not in line:
            index += 1
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        if value in {">", "|"}:
            index += 1
            block: list[str] = []
            while index < len(lines) and (
                lines[index].startswith(" ")
                or lines[index].startswith("\t")
                or lines[index] == ""
            ):
                block.append(lines[index].strip())
                index += 1
            fields[key] = " ".join(block).strip()
            continue

        fields[key] = normalize_yaml_scalar(value)
        index += 1

    return fields


def markdown_headings(skill_text: str) -> set[str]:
    headings: set[str] = set()
    for line in visible_lines(skill_text):
        match = HEADING_RE.match(line)
        if match:
            headings.add(f"{match.group(1)} {match.group(2).strip()}")
    return headings


def strip_frontmatter(skill_text: str) -> str:
    match = FRONTMATTER_RE.match(skill_text)
    if match:
        return skill_text[match.end():]
    return skill_text


def visible_lines(skill_text: str) -> list[str]:
    lines: list[str] = []
    in_fence = False

    for line in strip_frontmatter(skill_text).splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)

    return lines


def section_lines(skill_text: str, heading: str) -> list[str]:
    lines = visible_lines(skill_text)
    capture = False
    body: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            body.append(stripped)

    return [line for line in body if line]


def numbered_items(lines: list[str]) -> dict[int, str]:
    items: dict[int, str] = {}
    current_number: int | None = None

    for line in lines:
        match = re.match(r"^(\d+)\.\s+(.*)", line)
        if match:
            current_number = int(match.group(1))
            items[current_number] = match.group(2).strip()
            continue
        if current_number is not None:
            items[current_number] = f"{items[current_number]} {line}".strip()

    return items


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


def check_skill_frontmatter(skill_text: str) -> list[str]:
    issues: list[str] = []
    fields = extract_frontmatter_fields(skill_text)
    if not fields:
        return ["SKILL.md: missing YAML frontmatter."]

    if fields.get("name") != "challenging-decisions":
        issues.append("SKILL.md: frontmatter name must be 'challenging-decisions'.")

    description = fields.get("description", "")
    if not description.startswith("Use when"):
        issues.append("SKILL.md: description must start with 'Use when'.")

    return issues


def check_required_sections(skill_text: str) -> list[str]:
    headings = markdown_headings(skill_text)
    missing = [section for section in REQUIRED_SECTIONS if section not in headings]
    if not missing:
        return []
    return [f"SKILL.md is missing required sections: {', '.join(missing)}"]


def check_lens_headings(skill_text: str) -> list[str]:
    headings = markdown_headings(skill_text)
    missing = [lens for lens in EXPECTED_LENSES if lens not in headings]
    if not missing:
        return []
    return [f"SKILL.md is missing required lens headings: {', '.join(missing)}"]


def check_guidance_guards(skill_text: str) -> list[str]:
    issues: list[str] = []
    default_stance = section_lines(skill_text, "## Default stance")
    response_pattern = section_lines(skill_text, "## Response pattern")
    response_items = numbered_items(response_pattern)
    after_response = section_lines(skill_text, "## After the user responds")
    primary_followup_lines: list[str] = []
    for line in after_response:
        if line.lower().startswith("note:"):
            break
        primary_followup_lines.append(line)
    primary_followup = " ".join(primary_followup_lines).lower()

    if not any(line.lower() == "challenge before agreement." for line in default_stance):
        issues.append("SKILL.md: default stance must require challenge before agreement.")
    if not any("agree-first language" in line.lower() for line in default_stance):
        issues.append("SKILL.md: default stance must forbid agree-first language.")
    if "strongest counterarguments" not in response_items.get(2, "").lower():
        issues.append("SKILL.md: response pattern must surface the strongest counterarguments.")
    if "forcing question" not in response_items.get(4, "").lower():
        issues.append("SKILL.md: response pattern must end with a forcing question.")
    if (
        not after_response
        or "new evidence" not in primary_followup
        or "endorse with conditions" not in primary_followup
        or "smaller move instead" not in primary_followup
    ):
        issues.append(
            "SKILL.md: follow-up guidance must tell the model what to do after the user responds."
        )

    return issues


def check_version_sync(root: Path) -> list[str]:
    issues: list[str] = []
    version_file = root / "VERSION"
    package_file = root / "package.json"

    if not version_file.exists():
        issues.append("Missing VERSION file.")
        return issues
    if not package_file.exists():
        issues.append("Missing package.json file.")
        return issues

    version = read_text(version_file).strip()
    if not SEMVER_RE.match(version):
        issues.append("VERSION must be a valid semantic version.")
        return issues
    try:
        package_data = json.loads(read_text(package_file))
    except json.JSONDecodeError:
        issues.append("package.json is not valid JSON.")
        return issues
    if not isinstance(package_data, dict):
        issues.append("package.json must contain a JSON object.")
        return issues

    package_version = package_data.get("version", "")
    if not isinstance(package_version, str) or not SEMVER_RE.match(package_version):
        issues.append("package.json version must be a valid semantic version.")
        return issues
    if package_version != version:
        issues.append(
            f"VERSION ({version}) and package.json version ({package_version}) are out of sync."
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
    if not any(line.strip() in headings for line in read_text(changelog_file).splitlines()):
        issues.append(f"CHANGELOG.md does not contain a heading for VERSION '{version}'.")

    return issues


def check_readme_version(root: Path) -> list[str]:
    readme_file = root / "README.md"
    version_file = root / "VERSION"

    if not readme_file.exists() or not version_file.exists():
        return []

    version = read_text(version_file).strip()
    matches = [match.group("version") for match in README_VERSION_RE.finditer(read_text(readme_file))]
    if len(matches) != 1:
        return ["README.md must contain exactly one 'Current version: **...**' line."]
    if matches[0] == version:
        return []
    return [f"README.md version does not match VERSION '{version}'."]


def check_skill_file(root: Path) -> list[str]:
    issues: list[str] = []
    skill_file = root / "SKILL.md"
    if not skill_file.exists():
        return ["Missing SKILL.md at package root."]

    skill_text = read_text(skill_file)
    line_count = len(skill_text.splitlines())
    if line_count > MAX_SKILL_LINES:
        issues.append(f"SKILL.md is {line_count} lines (> {MAX_SKILL_LINES}).")

    issues.extend(check_markdown_file(skill_file, root))
    issues.extend(check_skill_frontmatter(skill_text))
    issues.extend(check_required_sections(skill_text))
    issues.extend(check_lens_headings(skill_text))
    issues.extend(check_guidance_guards(skill_text))
    return issues


def check_packaged_tools(root: Path) -> list[str]:
    issues: list[str] = []
    tools_dir = root / "tools"
    if not tools_dir.exists():
        return issues

    for python_file in sorted(tools_dir.rglob("*.py")):
        try:
            py_compile.compile(str(python_file), doraise=True)
        except py_compile.PyCompileError as error:
            issues.append(f"{python_file.relative_to(root)}: {error.msg}")

    for shell_file in sorted(tools_dir.rglob("*.sh")):
        try:
            result = subprocess.run(
                ["bash", "-n", str(shell_file)],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            continue
        if result.returncode != 0:
            shell_error = result.stderr.strip() or "shell syntax check failed"
            issues.append(f"{shell_file.relative_to(root)}: {shell_error}")

    return issues


def validate_root(root: Path) -> list[str]:
    issues: list[str] = []
    skill_file = root / "SKILL.md"

    issues.extend(check_required_files(root))
    issues.extend(check_skill_file(root))
    issues.extend(check_packaged_tools(root))
    issues.extend(check_version_sync(root))
    issues.extend(check_changelog_version(root))
    issues.extend(check_readme_version(root))

    for md_file in sorted(root.rglob("*.md")):
        if md_file == skill_file:
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
