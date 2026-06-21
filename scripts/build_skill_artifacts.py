#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

# "tests" holds the development test suite, which is not part of the shipped skill
# and may import repo-root helpers (e.g. scripts/) that do not exist inside an
# extracted package. Excluding it keeps the archive self-contained and runnable.
IGNORED_DIR_NAMES = {"__pycache__", "tests"}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".swp", ".skill"}


def find_skill_dirs(repo_root: Path) -> list[Path]:
    skill_dirs: list[Path] = []
    for skill_file in sorted(repo_root.glob("*/SKILL.md")):
        skill_dir = skill_file.parent
        if skill_dir.name.startswith("."):
            continue
        skill_dirs.append(skill_dir)
    return skill_dirs


def should_archive_path(skill_dir: Path, path: Path) -> bool:
    try:
        relative_parts = path.relative_to(skill_dir).parts
    except ValueError:
        return False

    return (
        path.is_file()
        and not any(part in IGNORED_DIR_NAMES or part.startswith(".") for part in relative_parts)
        and path.suffix not in IGNORED_SUFFIXES
        and not path.name.endswith("~")
    )


def build_archive(skill_dir: Path, output_dir: Path) -> Path:
    archive_path = output_dir / f"{skill_dir.name}.skill"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill_dir.rglob("*")):
            if not should_archive_path(skill_dir, path):
                continue
            archive.write(path, arcname=path.relative_to(skill_dir.parent))
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build .skill archives into dist/")
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Directory where .skill archives will be written (default: dist)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    skill_dirs = find_skill_dirs(repo_root)
    if not skill_dirs:
        raise SystemExit("No skill directories found.")

    built_archives = [build_archive(skill_dir, output_dir) for skill_dir in skill_dirs]

    for archive_path in built_archives:
        # --output-dir may live outside the repo, so fall back to the absolute path
        # when it cannot be expressed relative to the repo root.
        try:
            print(archive_path.relative_to(repo_root))
        except ValueError:
            print(archive_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())