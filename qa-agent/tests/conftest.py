from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "tools" / "validate_skill_package.py"


def make_skill_text(*, missing_sections: list[str] | None = None) -> str:
    missing_sections = set(missing_sections or [])
    sections = [
        "---",
        "name: qa-agent",
        "description: demo",
        "---",
        "",
        "# QA Agent",
        "",
        "## Mission",
        "",
        "Mission text.",
        "",
        "## When To Use",
        "",
        "Use guidance.",
        "",
        "## When Not To Use",
        "",
        "Skip guidance.",
        "",
        "## Operating Modes",
        "",
        "### Mode: review",
        "",
        "Review guidance.",
        "",
        "### Mode: test-plan",
        "",
        "Plan guidance.",
        "",
        "### Mode: execute",
        "",
        "Execution guidance.",
        "",
        "### Mode: regression",
        "",
        "Regression guidance.",
        "",
        "### Mode: bug-hunt",
        "",
        "Bug-hunt guidance.",
        "",
        "### Mode Selection Rules",
        "",
        "If mode is omitted or ambiguous, default to mode `review`.",
        "",
        "## Operating Stance",
        "",
        "Stance.",
        "",
        "## Workflow",
        "",
        "1. Scope",
        "",
        "## Severity Calibration",
        "",
        "Calibrate.",
        "",
        "## Output Contract",
        "",
        "Ordered output.",
        "",
        "## Bug Report Format",
        "",
        "Template.",
        "",
        "## Anti-Patterns",
        "",
        "Do not.",
        "",
        "## Definition of Done",
        "",
        "Done criteria.",
        "",
        "## References",
        "",
        "Use references.",
        "",
    ]

    text = "\n".join(
        line
        for line in sections
        if not line.startswith("## ") and not line.startswith("### ") or line not in missing_sections
    )
    return text.rstrip() + "\n"


@pytest.fixture(scope="session")
def validator():
    spec = importlib.util.spec_from_file_location("validate_skill_package", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def package_factory(tmp_path, validator):
    counter = 0

    def _make(
        *,
        skill_text: str | None = None,
        include_references: bool = True,
        include_version: bool = True,
        include_changelog: bool = True,
        include_package_json: bool = True,
        include_readme: bool = True,
        changelog_text: str | None = None,
        package_json_text: str | None = None,
    ) -> Path:
        nonlocal counter
        counter += 1
        root = tmp_path / f"pkg_{counter}"
        root.mkdir(parents=True, exist_ok=True)

        content = skill_text if skill_text is not None else make_skill_text()
        (root / "SKILL.md").write_text(content, encoding="utf-8")

        if include_readme:
            (root / "README.md").write_text(
                "# QA Agent\n\nCurrent version: **1.2.3**\n",
                encoding="utf-8",
            )

        tools_dir = root / "tools"
        tools_dir.mkdir(exist_ok=True)
        (tools_dir / "validate_skill_package.py").write_text("# tool\n", encoding="utf-8")
        (tools_dir / "validate_skill_package.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (tools_dir / "bump_version.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")

        tests_dir = root / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "conftest.py").write_text("# tests\n", encoding="utf-8")
        (tests_dir / "test_validator_structure.py").write_text("# tests\n", encoding="utf-8")
        (tests_dir / "test_validator_markdown_checks.py").write_text("# tests\n", encoding="utf-8")
        (tests_dir / "test_validator_versions.py").write_text("# tests\n", encoding="utf-8")

        if include_references:
            for rel in validator.EXPECTED_REFERENCES:
                ref = root / rel
                ref.parent.mkdir(parents=True, exist_ok=True)
                ref.write_text("# ref\n", encoding="utf-8")

        if include_version:
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")

        if include_changelog:
            if changelog_text is None:
                changelog_text = "# Changelog\n\n## 1.2.3\n- Initial release.\n"
            (root / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")

        if include_package_json:
            if package_json_text is None:
                package_json_text = (
                    json.dumps({"name": "qa-agent", "version": "1.2.3"}, indent=2) + "\n"
                )
            (root / "package.json").write_text(package_json_text, encoding="utf-8")

        return root

    return _make
