from __future__ import annotations

import importlib.util
from pathlib import Path
import zipfile


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_archive_excludes_generated_python_artifacts(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(repo_root / "scripts" / "build_skill_artifacts.py", "build_skill_artifacts")

    skill_dir = tmp_path / "demo-skill"
    (skill_dir / "tests" / "__pycache__").mkdir(parents=True)
    (skill_dir / "tools" / "__pycache__").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when demo.\n---\n", encoding="utf-8")
    (skill_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    (skill_dir / "tests" / "__pycache__" / "test_demo.cpython-314.pyc").write_bytes(b"pyc")
    (skill_dir / "tools" / "__pycache__" / "helper.cpython-314.pyc").write_bytes(b"pyc")
    (skill_dir / "tools" / "helper.py").write_text("print('ok')\n", encoding="utf-8")
    (skill_dir / ".DS_Store").write_text("junk\n", encoding="utf-8")
    (skill_dir / "notes.tmp").write_text("junk\n", encoding="utf-8")

    output_dir = tmp_path / "dist"
    output_dir.mkdir()
    archive_path = module.build_archive(skill_dir, output_dir)

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()

    assert "demo-skill/tools/helper.py" in names
    assert "demo-skill/README.md" in names
    assert all("__pycache__/" not in name for name in names)
    assert all(not name.endswith(".pyc") for name in names)
    assert "demo-skill/.DS_Store" not in names
    assert "demo-skill/notes.tmp" not in names


def test_build_archive_keeps_files_when_skill_dir_lives_under_hidden_parent(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(repo_root / "scripts" / "build_skill_artifacts.py", "build_skill_artifacts")

    hidden_parent = tmp_path / ".worktrees" / "demo-worktree"
    skill_dir = hidden_parent / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Use when demo.\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text("# Demo\n", encoding="utf-8")

    output_dir = tmp_path / "dist"
    output_dir.mkdir()
    archive_path = module.build_archive(skill_dir, output_dir)

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()

    assert "demo-skill/SKILL.md" in names
    assert "demo-skill/README.md" in names
