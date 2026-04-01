#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

FENCE_RE = re.compile(r"^\s*```")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def ends_with_newline(path: Path) -> bool:
    content = path.read_bytes()
    return not content or content.endswith(b"\n")


def fence_count_ok(text: str) -> bool:
    fences = sum(1 for line in text.splitlines() if FENCE_RE.match(line))
    return fences % 2 == 0


def check_markdown_file(path: Path, root: Path) -> list[str]:
    issues: list[str] = []
    rel = path.relative_to(root)
    text = read_text(path)

    if not ends_with_newline(path):
        issues.append(f"{rel}: missing trailing newline")
    if not fence_count_ok(text):
        issues.append(f"{rel}: odd number of ``` fences (unclosed code block?)")

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
    try:
        package_data = json.loads(read_text(package_file))
    except json.JSONDecodeError:
        issues.append("package.json is not valid JSON.")
        return issues

    package_version = package_data.get("version", "")
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
        issues.append(
            f"CHANGELOG.md does not contain a heading for VERSION '{version}'."
        )

    return issues


def validate_root(root: Path) -> list[str]:
    issues: list[str] = []
    skill_path = root / "SKILL.md"
    if not skill_path.exists():
        issues.append("Missing SKILL.md at package root.")
        return issues

    issues.extend(check_version_sync(root))
    issues.extend(check_changelog_version(root))

    for md_file in sorted(root.rglob("*.md")):
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
