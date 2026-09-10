#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
README_VERSION_RE = re.compile(r"^(Current version:\s+\*\*)[^\*]+(\*\*)$", flags=re.M)


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def render_updated_readme(readme_path: Path, version: str) -> str:
    text = readme_path.read_text(encoding="utf-8")
    updated, replacements = README_VERSION_RE.subn(rf"\g<1>{version}\g<2>", text)
    if replacements != 1:
        return ""
    return updated


def replace_file(source: Path, destination: Path) -> None:
    source.replace(destination)


def apply_file_updates(updates: list[tuple[Path, str]]) -> None:
    originals: dict[Path, str | None] = {}
    temp_paths: list[Path] = []
    replaced: list[Path] = []

    try:
        for path, content in updates:
            originals[path] = path.read_text(encoding="utf-8") if path.exists() else None
            temp_path = path.with_name(f".{path.name}.tmp")
            temp_path.write_text(content, encoding="utf-8")
            temp_paths.append(temp_path)

        for (path, _), temp_path in zip(updates, temp_paths):
            replace_file(temp_path, path)
            replaced.append(path)
    except OSError:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                if path.exists():
                    path.unlink()
                continue
            path.write_text(original, encoding="utf-8")
        raise
    finally:
        for temp_path in temp_paths:
            if temp_path.exists():
                temp_path.unlink()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: bump_version.py <version>", file=sys.stderr)
        return 2

    version = argv[1].strip()
    if not SEMVER_RE.match(version):
        return fail(f"invalid version '{version}'. Expected semantic version format.")

    root = Path(__file__).resolve().parents[1]
    version_file = root / "VERSION"
    package_file = root / "package.json"
    readme_file = root / "README.md"

    if not package_file.exists():
        return fail("package.json was not found.")
    if not readme_file.exists():
        return fail("README.md was not found.")

    try:
        package_data = json.loads(package_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail(f"package.json is invalid JSON: {exc}")
    if not isinstance(package_data, dict):
        return fail("package.json must contain a JSON object.")

    updated_readme = render_updated_readme(readme_file, version)
    if updated_readme == "":
        return fail("README.md exists but does not contain exactly one 'Current version: **...**' line.")

    package_data["version"] = version
    updates = [
        (package_file, json.dumps(package_data, indent=2) + "\n"),
        (version_file, f"{version}\n"),
        (readme_file, updated_readme),
    ]

    try:
        apply_file_updates(updates)
    except OSError as exc:
        return fail(f"failed to update version files: {exc}")

    print(f"Updated VERSION, package.json, and README.md to {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
