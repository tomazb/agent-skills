#!/usr/bin/env python3

from __future__ import annotations

import py_compile
import re
import subprocess
from pathlib import Path
from typing import Callable

try:
    import yaml
    from skills_ref import validate as _skills_ref_validate
    from skills_ref.validator import validate_metadata as _skills_ref_validate_metadata
except ImportError:  # pragma: no cover - exercised by the CLI error path
    yaml = None
    _skills_ref_validate = None
    _skills_ref_validate_metadata = None


FENCE_RE = re.compile(r"^\s*```")


SkillSpecValidator = Callable[[Path], list[str]]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def ends_with_newline(path: Path) -> bool:
    content = path.read_bytes()
    return not content or content.endswith(b"\n")


def fence_count_ok(text: str) -> bool:
    fences = sum(1 for line in text.splitlines() if FENCE_RE.match(line))
    return fences % 2 == 0


def display_path(path: Path, root: Path) -> str:
    """Return a repository-relative path when possible, otherwise an absolute path."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def find_skill_dirs(repo_root: Path) -> list[Path]:
    return sorted(
        skill_file.parent
        for skill_file in repo_root.glob("*/SKILL.md")
        if not skill_file.parent.name.startswith(".")
    )


def validate_markdown_file(path: Path, root: Path) -> list[str]:
    rel = display_path(path, root)
    issues: list[str] = []
    text = read_text(path)

    if not ends_with_newline(path):
        issues.append(f"{rel}: missing trailing newline")
    if not fence_count_ok(text):
        issues.append(f"{rel}: odd number of fenced code blocks")

    return issues


def parse_frontmatter_with_yaml(skill_file: Path) -> tuple[dict[str, object] | None, list[str]]:
    """Parse YAML frontmatter with PyYAML for repository compatibility checks."""
    if yaml is None:
        return None, ["PyYAML is required; install requirements-dev.txt"]

    content = read_text(skill_file)
    if not content.startswith("---"):
        return None, ["SKILL.md must start with YAML frontmatter (---)"]

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, ["SKILL.md frontmatter not properly closed with ---"]

    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError as error:
        return None, [f"Invalid YAML in frontmatter: {error}"]

    if not isinstance(metadata, dict):
        return None, ["SKILL.md frontmatter must be a YAML mapping"]

    return metadata, []


def check_repository_frontmatter_policy(
    metadata: dict[str, object], skill_dir: Path
) -> list[str]:
    """Enforce repository-specific frontmatter conventions beyond skills-ref."""
    issues: list[str] = []
    if "tools" in metadata:
        issues.append(
            "Unexpected legacy frontmatter field 'tools'. Use the Agent Skills "
            "'allowed-tools' field instead."
        )

    description = metadata.get("description", "")
    if not isinstance(description, str) or not description.strip():
        issues.append("missing frontmatter description")
    elif not description.lstrip().startswith("Use when"):
        issues.append("description must start with 'Use when'")

    return issues


def validate_agent_skill_spec(
    skill_dir: Path,
    repo_root: Path,
    validator: SkillSpecValidator | None = None,
) -> list[str]:
    """Validate SKILL.md with skills-ref and repository frontmatter policy."""
    rel = display_path(skill_dir, repo_root)

    if validator is not None:
        try:
            spec_issues = validator(skill_dir)
        except Exception as error:
            return [
                f"{rel}/SKILL.md: skills-ref validation failed unexpectedly: {error}"
            ]
        return [
            f"{rel}/SKILL.md: Agent Skills spec: {issue}" for issue in spec_issues
        ]

    if (
        _skills_ref_validate is None
        or _skills_ref_validate_metadata is None
        or yaml is None
    ):
        return [
            f"{rel}/SKILL.md: skills-ref and PyYAML are required for Agent Skills "
            "spec validation; install requirements-dev.txt"
        ]

    skill_file = skill_dir / "SKILL.md"
    metadata, parse_issues = parse_frontmatter_with_yaml(skill_file)
    if parse_issues:
        return [
            f"{rel}/SKILL.md: Agent Skills spec: {issue}" for issue in parse_issues
        ]
    assert metadata is not None

    policy_issues = check_repository_frontmatter_policy(metadata, skill_dir)
    if policy_issues:
        return [
            f"{rel}/SKILL.md: Agent Skills spec: {issue}" for issue in policy_issues
        ]

    try:
        spec_issues = _skills_ref_validate(skill_dir)
    except Exception as error:
        return [
            f"{rel}/SKILL.md: skills-ref validation failed unexpectedly: {error}"
        ]

    return [f"{rel}/SKILL.md: Agent Skills spec: {issue}" for issue in spec_issues]


def validate_skill_dir(
    skill_dir: Path,
    repo_root: Path,
    *,
    spec_validator: SkillSpecValidator | None = None,
) -> list[str]:
    issues: list[str] = []
    issues.extend(
        validate_agent_skill_spec(
            skill_dir,
            repo_root,
            validator=spec_validator,
        )
    )

    for md_file in sorted(skill_dir.rglob("*.md")):
        issues.extend(validate_markdown_file(md_file, repo_root))

    references_dir = skill_dir / "references"
    if references_dir.exists() and not any(references_dir.glob("*.md")):
        issues.append(
            f"{display_path(references_dir, repo_root)}: directory exists but contains no markdown files"
        )

    for python_dir_name in ("scripts", "tools"):
        python_dir = skill_dir / python_dir_name
        if not python_dir.exists():
            continue

        python_files = sorted(python_dir.rglob("*.py"))
        shell_files = sorted(python_dir.rglob("*.sh"))
        if not python_files and not shell_files:
            issues.append(
                f"{display_path(python_dir, repo_root)}: directory exists but contains no Python or shell files"
            )
        for python_file in python_files:
            try:
                py_compile.compile(str(python_file), doraise=True)
            except py_compile.PyCompileError as error:
                issues.append(f"{display_path(python_file, repo_root)}: {error.msg}")

        for shell_file in shell_files:
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
                issues.append(f"{display_path(shell_file, repo_root)}: {shell_error}")

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
