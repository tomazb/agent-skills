from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_skill_dir_compiles_python_under_tools(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )

    skill_dir = tmp_path / "demo-skill"
    (skill_dir / "tools").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Use when demo.\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    (skill_dir / "tools" / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    issues = module.validate_skill_dir(skill_dir, tmp_path)

    assert any("broken.py" in issue for issue in issues)


def test_validate_skill_dir_checks_shell_entrypoints_under_tools(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )

    skill_dir = tmp_path / "demo-skill"
    (skill_dir / "tools").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Use when demo.\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    (skill_dir / "tools" / "validate_skill_package.sh").write_text(
        "if [ -n \"$BROKEN\"; then\n",
        encoding="utf-8",
    )

    issues = module.validate_skill_dir(skill_dir, tmp_path)

    assert any("validate_skill_package.sh" in issue for issue in issues)


def test_validate_skill_dir_accepts_shell_only_tools_directory(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )

    skill_dir = tmp_path / "demo-skill"
    (skill_dir / "tools").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Use when demo.\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    (skill_dir / "tools" / "validate_skill_package.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n",
        encoding="utf-8",
    )

    issues = module.validate_skill_dir(skill_dir, tmp_path)

    assert issues == []
