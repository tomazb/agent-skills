#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


def find_skill_dirs(repo_root: Path) -> list[Path]:
    skill_dirs: list[Path] = []
    for skill_file in sorted(repo_root.glob("*/SKILL.md")):
        skill_dir = skill_file.parent
        if skill_dir.name.startswith("."):
            continue
        skill_dirs.append(skill_dir)
    return skill_dirs


def build_archive(skill_dir: Path, output_dir: Path) -> Path:
    archive_path = output_dir / f"{skill_dir.name}.skill"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill_dir.rglob("*")):
            if not path.is_file():
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
        print(archive_path.relative_to(repo_root))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())