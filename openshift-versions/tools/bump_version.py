#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


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

    if not package_file.exists():
        return fail("package.json was not found.")

    try:
        package_data = json.loads(package_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail(f"package.json is invalid JSON: {exc}")

    package_data["version"] = version
    package_file.write_text(json.dumps(package_data, indent=2) + "\n", encoding="utf-8")
    version_file.write_text(f"{version}\n", encoding="utf-8")

    print(f"Updated VERSION and package.json to {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
