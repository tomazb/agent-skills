from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = PACKAGE_ROOT / "tools" / "validate_skill_package.py"
BUMP_VERSION_PATH = PACKAGE_ROOT / "tools" / "bump_version.py"


def make_skill_text(
    *,
    description: str = (
        "Use when creating a new skill in this collection, or modifying an existing "
        "skill's SKILL.md, package layout, version, changelog, tests, or validation tooling."
    ),
    missing_sections: list[str] | None = None,
    missing_guides: list[str] | None = None,
) -> str:
    missing_sections = set(missing_sections or [])
    missing_guides = set(missing_guides or [])

    guides = {
        "validate_skill_collection.py": "Run python3 scripts/validate_skill_collection.py from the repository root.",
        "run_test_suite.py": "Run python3 scripts/run_test_suite.py from the repository root.",
        "package.json": "Keep VERSION and the package.json version in sync.",
        "AGENTS.md": "Update the root README.md and the AGENTS.md Skill Inventory together.",
    }

    sections = [
        "---",
        "name: skill-authoring",
        "description: >",
        f"  {description}",
        "---",
        "",
        "# Skill Authoring",
        "",
        "## When to use",
        "",
        "Use this skill when creating or modifying a skill in this collection.",
        "",
        "## Package layout",
        "",
        "Required files plus optional references, tools, scripts, assets, and tests.",
        "",
        "## Frontmatter rules",
        "",
        "Descriptions start with Use when and avoid the legacy tools field.",
        "",
        "## Versioning and changelog",
        "",
        "Keep VERSION, CHANGELOG.md, and the README version line in sync.",
        "",
        "## Validation",
        "",
        *(f"{text}" for key, text in guides.items() if key not in missing_guides),
        "",
    ]

    text = "\n".join(
        line
        for line in sections
        if not line.startswith("## ") or line not in missing_sections
    )
    return text.rstrip() + "\n"


@pytest.fixture(scope="session")
def validator():
    if not VALIDATOR_PATH.exists():
        pytest.fail(f"validator missing at {VALIDATOR_PATH}")

    spec = importlib.util.spec_from_file_location("validate_skill_package", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def bump_version_module():
    if not BUMP_VERSION_PATH.exists():
        pytest.fail(f"bump_version missing at {BUMP_VERSION_PATH}")

    spec = importlib.util.spec_from_file_location("bump_version", BUMP_VERSION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def make_skill_text_fn():
    return make_skill_text


@pytest.fixture
def package_factory(tmp_path):
    counter = 0

    def _make(
        *,
        skill_text: str | None = None,
        include_version: bool = True,
        include_changelog: bool = True,
        include_package_json: bool = True,
        include_readme: bool = True,
        include_baseline: bool = True,
        extra_missing_files: list[str] | None = None,
        changelog_text: str | None = None,
        package_json_text: str | None = None,
        readme_text: str | None = None,
        tool_python_text: str = "# tool\n",
        tool_shell_text: str = "#!/usr/bin/env bash\n",
    ) -> Path:
        nonlocal counter
        counter += 1
        root = tmp_path / f"pkg_{counter}"
        root.mkdir(parents=True, exist_ok=True)

        (root / "SKILL.md").write_text(skill_text or make_skill_text(), encoding="utf-8")

        if include_readme:
            (root / "README.md").write_text(
                readme_text
                or "# Skill Authoring\n\nCurrent version: **0.1.0**\n",
                encoding="utf-8",
            )

        tools_dir = root / "tools"
        tools_dir.mkdir(exist_ok=True)
        (tools_dir / "validate_skill_package.py").write_text("# tool\n", encoding="utf-8")
        (tools_dir / "validate_skill_package.sh").write_text(tool_shell_text, encoding="utf-8")
        (tools_dir / "bump_version.py").write_text(tool_python_text, encoding="utf-8")

        tests_dir = root / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "conftest.py").write_text("# tests\n", encoding="utf-8")
        (tests_dir / "test_validator_markdown_checks.py").write_text("# tests\n", encoding="utf-8")
        (tests_dir / "test_validator_structure.py").write_text("# tests\n", encoding="utf-8")
        (tests_dir / "test_validator_versions.py").write_text("# tests\n", encoding="utf-8")
        if include_baseline:
            (tests_dir / "test_skill_baseline.md").write_text(
                "# Baseline\n\n- Skill changed without tests.\n",
                encoding="utf-8",
            )

        if include_version:
            (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")

        if include_changelog:
            (root / "CHANGELOG.md").write_text(
                changelog_text or "# Changelog\n\n## 0.1.0\n- Initial release.\n",
                encoding="utf-8",
            )

        if include_package_json:
            (root / "package.json").write_text(
                package_json_text
                or (json.dumps({"name": "skill-authoring", "version": "0.1.0"}, indent=2) + "\n"),
                encoding="utf-8",
            )

        for rel in extra_missing_files or []:
            path = root / rel
            if path.exists():
                path.unlink()

        return root

    return _make
