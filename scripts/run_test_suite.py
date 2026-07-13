#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def find_test_suites(repo_root: Path) -> list[Path]:
    """Return root tests followed by each top-level skill's tests directory."""
    suites: list[Path] = []
    root_tests = repo_root / "tests"
    if root_tests.is_dir():
        suites.append(root_tests)

    suites.extend(
        sorted(
            test_dir
            for test_dir in repo_root.glob("*/tests")
            if test_dir.is_dir() and not test_dir.parent.name.startswith(".")
        )
    )
    return suites


def suite_result_name(repo_root: Path, suite: Path) -> str:
    """Return a filesystem-safe JUnit result name for a test suite."""
    relative = suite.relative_to(repo_root)
    if relative == Path("tests"):
        return "root"
    return relative.parent.name


def run_test_suites(repo_root: Path, junit_dir: Path | None = None) -> int:
    """Run every discovered suite in a separate pytest process.

    Skill packages intentionally reuse helper module names such as
    ``validate_skill_package`` and ``render_smoke_manifest``. Separate processes
    preserve package isolation and prevent Python's global module cache from
    binding one skill's tests to another skill's helper.
    """
    suites = find_test_suites(repo_root)
    if not suites:
        print("No test suites found.", file=sys.stderr)
        return 1

    if junit_dir is not None:
        junit_dir.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    for suite in suites:
        relative_suite = suite.relative_to(repo_root)
        command = [sys.executable, "-m", "pytest", "-q", str(relative_suite)]
        if junit_dir is not None:
            result_file = junit_dir / f"{suite_result_name(repo_root, suite)}.xml"
            command.append(f"--junitxml={result_file}")

        print(f"\n=== pytest {relative_suite} ===", flush=True)
        try:
            result = subprocess.run(command, cwd=repo_root, check=False)
        except FileNotFoundError as error:
            print(f"Unable to run pytest: {error}", file=sys.stderr)
            return 1

        if result.returncode != 0:
            failed.append(str(relative_suite))

    if failed:
        print("\nFailed test suites:", file=sys.stderr)
        for suite in failed:
            print(f"- {suite}", file=sys.stderr)
        return 1

    print(f"\nAll {len(suites)} isolated test suites passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run root and per-skill pytest suites in isolated processes."
    )
    parser.add_argument(
        "--junit-dir",
        type=Path,
        help="Optional directory for one JUnit XML file per suite.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    junit_dir = None
    if args.junit_dir is not None:
        junit_dir = (
            args.junit_dir
            if args.junit_dir.is_absolute()
            else repo_root / args.junit_dir
        )

    return run_test_suites(repo_root, junit_dir)


if __name__ == "__main__":
    raise SystemExit(main())
