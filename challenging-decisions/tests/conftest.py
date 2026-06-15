from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = PACKAGE_ROOT / "tools" / "validate_skill_package.py"
BUMP_VERSION_PATH = PACKAGE_ROOT / "tools" / "bump_version.py"


EXPECTED_LENSES = [
    "### Evidence Lens",
    "### Scope Lens",
    "### Timing Lens",
    "### Complexity Lens",
    "### Reversibility Lens",
    "### Opportunity Cost Lens",
]


def make_skill_text(
    *,
    description: str = (
        "Use when a decision sounds reasonable but still needs pressure-testing before agreement, "
        "especially for scope, architecture, sequencing, or irreversible product trade-offs."
    ),
    missing_sections: list[str] | None = None,
    missing_lenses: list[str] | None = None,
    include_challenge_first: bool = True,
    include_agreement_guard: bool = True,
    include_counterarguments: bool = True,
    include_forcing_question: bool = True,
    include_followup: bool = True,
) -> str:
    missing_sections = set(missing_sections or [])
    missing_lenses = set(missing_lenses or [])

    sections = [
        "---",
        "name: challenging-decisions",
        "description: >",
        f"  {description}",
        "---",
        "",
        "# Challenging Decisions",
        "",
        "## Why this skill exists",
        "",
        "Normal assistants often challenge weak decisions through only one lens, and they can still agree first on plausible decisions.",
        "",
        "## Default stance",
        "",
        *(["Challenge before agreement."] if include_challenge_first else []),
        "Use named lenses instead of theatrical personas.",
        *( ["Do not lead with agree-first language or early reassurance.", ""] if include_agreement_guard else [] ),
        "",
        "## Decision lenses",
        "",
        *(line for lens in EXPECTED_LENSES if lens not in missing_lenses for line in (lens, "Ask the sharpest question from this lens.", "")),
        "## Response pattern",
        "",
        "1. Name the decision and the likely upside.",
        *( ["2. Surface the strongest counterarguments first."] if include_counterarguments else ["2. Surface counterarguments."] ),
        "3. Say what evidence, trigger, or constraint would change the call.",
        *( ["4. End with a forcing question that makes the decision earn the next step."] if include_forcing_question else ["4. End with a question."] ),
        "",
        "## After the user responds",
        "",
        *( ["Re-evaluate with the new evidence, state the remaining risk, and either endorse with conditions or propose the smaller move instead."] if include_followup else ["Continue the conversation."] ),
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
                or "# Challenging Decisions\n\nCurrent version: **1.0.0**\n",
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
                "# Baseline\n\n- Yes, that makes sense.\n",
                encoding="utf-8",
            )

        if include_version:
            (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")

        if include_changelog:
            (root / "CHANGELOG.md").write_text(
                changelog_text or "# Changelog\n\n## 1.0.0\n- Initial release.\n",
                encoding="utf-8",
            )

        if include_package_json:
            (root / "package.json").write_text(
                package_json_text
                or (json.dumps({"name": "challenging-decisions", "version": "1.0.0"}, indent=2) + "\n"),
                encoding="utf-8",
            )

        for rel in extra_missing_files or []:
            path = root / rel
            if path.exists():
                path.unlink()

        return root

    return _make
