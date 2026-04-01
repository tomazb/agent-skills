#!/usr/bin/env python3

from __future__ import annotations

import py_compile
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


def parse_frontmatter(skill_text: str) -> dict[str, str] | None:
    lines = skill_text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return None

    frontmatter: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return frontmatter
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
    return None


def find_skill_dirs(repo_root: Path) -> list[Path]:
    return sorted(
        skill_file.parent
        for skill_file in repo_root.glob("*/SKILL.md")
        if not skill_file.parent.name.startswith(".")
    )


def validate_markdown_file(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    issues: list[str] = []
    text = read_text(path)

    if not ends_with_newline(path):
        issues.append(f"{rel}: missing trailing newline")
    if not fence_count_ok(text):
        issues.append(f"{rel}: odd number of fenced code blocks")

    return issues


def validate_skill_dir(skill_dir: Path, repo_root: Path) -> list[str]:
    issues: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    skill_text = read_text(skill_file)
    frontmatter = parse_frontmatter(skill_text)

    if frontmatter is None:
        issues.append(f"{skill_file.relative_to(repo_root)}: missing or invalid YAML frontmatter")
    else:
        if frontmatter.get("name") != skill_dir.name:
            issues.append(
                f"{skill_file.relative_to(repo_root)}: frontmatter name '{frontmatter.get('name', '')}' does not match directory '{skill_dir.name}'"
            )
        if not frontmatter.get("description"):
            issues.append(f"{skill_file.relative_to(repo_root)}: missing frontmatter description")

    for md_file in sorted(skill_dir.rglob("*.md")):
        issues.extend(validate_markdown_file(md_file, repo_root))

    references_dir = skill_dir / "references"
    if references_dir.exists() and not any(references_dir.glob("*.md")):
        issues.append(f"{references_dir.relative_to(repo_root)}: directory exists but contains no markdown files")

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.exists():
        python_files = sorted(scripts_dir.rglob("*.py"))
        if not python_files:
            issues.append(f"{scripts_dir.relative_to(repo_root)}: directory exists but contains no Python files")
        for python_file in python_files:
            try:
                py_compile.compile(str(python_file), doraise=True)
            except py_compile.PyCompileError as error:
                issues.append(f"{python_file.relative_to(repo_root)}: {error.msg}")

    return issues


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    skill_dirs = find_skill_dirs(repo_root)
    issues: list[str] = []

    if not skill_dirs:
        print("Validation FAILED:\n")
        print("- No skill directories found.")
        return 1

    for skill_dir in skill_dirs:
        issues.extend(validate_skill_dir(skill_dir, repo_root))

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