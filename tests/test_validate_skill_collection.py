from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_spec(_skill_dir: Path) -> list[str]:
    return []


def make_skill(tmp_path: Path, *, name: str = "demo-skill") -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when demo.\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    return skill_dir


def test_validate_skill_dir_compiles_python_under_tools(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )

    skill_dir = make_skill(tmp_path)
    (skill_dir / "tools").mkdir(parents=True)
    (skill_dir / "tools" / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    issues = module.validate_skill_dir(
        skill_dir, tmp_path, spec_validator=valid_spec
    )

    assert any("broken.py" in issue for issue in issues)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not found")
def test_validate_skill_dir_checks_shell_entrypoints_under_tools(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )

    skill_dir = make_skill(tmp_path)
    (skill_dir / "tools").mkdir(parents=True)
    (skill_dir / "tools" / "validate_skill_package.sh").write_text(
        "if [ -n \"$BROKEN\"; then\n",
        encoding="utf-8",
    )

    issues = module.validate_skill_dir(
        skill_dir, tmp_path, spec_validator=valid_spec
    )

    assert any("validate_skill_package.sh" in issue for issue in issues)


def test_validate_skill_dir_accepts_shell_only_tools_directory(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )

    skill_dir = make_skill(tmp_path)
    (skill_dir / "tools").mkdir(parents=True)
    (skill_dir / "tools" / "validate_skill_package.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n",
        encoding="utf-8",
    )

    issues = module.validate_skill_dir(
        skill_dir, tmp_path, spec_validator=valid_spec
    )

    assert issues == []


def test_validate_agent_skill_spec_surfaces_reference_errors(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )
    skill_dir = make_skill(tmp_path)

    issues = module.validate_agent_skill_spec(
        skill_dir,
        tmp_path,
        validator=lambda _path: ["Description exceeds 1024 character limit"],
    )

    assert issues == [
        "demo-skill/SKILL.md: Agent Skills spec: Description exceeds 1024 character limit"
    ]


def test_validate_agent_skill_spec_reports_missing_dependency(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    module = load_module(
        repo_root / "scripts" / "validate_skill_collection.py",
        "validate_skill_collection",
    )
    skill_dir = make_skill(tmp_path)
    monkeypatch.setattr(module, "_skills_ref_validate", None)

    issues = module.validate_agent_skill_spec(skill_dir, tmp_path)

    assert issues == [
        "demo-skill/SKILL.md: skills-ref is required for Agent Skills spec validation; "
        "install requirements-dev.txt"
    ]
