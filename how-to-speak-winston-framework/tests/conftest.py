from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "tools" / "validate_skill_package.py"

EXPECTED_REFERENCES = [
    "references/delivery-heuristics.md",
    "references/slide-audit-checklist.md",
    "references/star-framework-examples.md",
    "references/talk-structure-templates.md",
    "references/common-mistakes.md",
]


def make_skill_text(
    *,
    missing_sections: list[str] | None = None,
    missing_frameworks: list[int] | None = None,
    double_blank_after_framework: int | None = None,
) -> str:
    """Generate a valid SKILL.md with all 10 frameworks.

    Params:
        missing_sections: list of '## Section' headings to omit.
        missing_frameworks: list of framework numbers (1-10) to omit.
        double_blank_after_framework: framework number to add an extra blank line after.
    """
    missing_sections = set(missing_sections or [])
    missing_frameworks = set(missing_frameworks or [])

    lines = [
        "---",
        "name: how-to-speak-winston-framework",
        "description: demo",
        "---",
        "",
        "# Patrick Winston's MIT Presentation Framework",
        "",
    ]

    sections = [
        "## Role & Philosophy",
        "## Operating Modes",
        "### Build Mode",
        "### Audit Mode",
        "### Coach Mode",
        "## Framework Selection",
        "## Applicability Warnings",
        "## Misinterpretation Guards",
        "## Key Principles",
    ]

    for section in sections:
        if section in missing_sections:
            continue
        lines.append(section)
        lines.append("")
        lines.append(f"Content for {section}.")
        lines.append("")

    framework_names = [
        "Winston's Success Formula",
        "Time & Place",
        "Empowerment Promise",
        "Four Heuristics",
        "Board vs. Slides",
        "Slide Crime Audit",
        "Star Framework",
        "Props, Stories & Near-Miss",
        "Job Talk Framework",
        "How to Stop",
    ]

    for i, name in enumerate(framework_names, 1):
        if i in missing_frameworks:
            continue
        lines.append(f"### Framework {i}: {name}")
        lines.append("")
        if double_blank_after_framework == i:
            lines.append("")
        lines.append(f"> Guiding question for framework {i}.")
        lines.append("")
        lines.append(f"Framework {i} guidance.")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@pytest.fixture(scope="session")
def validator():
    spec = importlib.util.spec_from_file_location(
        "validate_skill_package", VALIDATOR_PATH
    )
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
        changelog_text: str | None = None,
        package_json_text: str | None = None,
    ) -> Path:
        nonlocal counter
        counter += 1
        root = tmp_path / f"pkg_{counter}"
        root.mkdir(parents=True, exist_ok=True)

        content = skill_text if skill_text is not None else make_skill_text()
        (root / "SKILL.md").write_text(content, encoding="utf-8")
        (root / "README.md").write_text("# README\n", encoding="utf-8")

        if include_references:
            for rel in EXPECTED_REFERENCES:
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
                    json.dumps(
                        {"name": "how-to-speak-winston-framework", "version": "1.2.3"},
                        indent=2,
                    )
                    + "\n"
                )
            (root / "package.json").write_text(package_json_text, encoding="utf-8")

        return root

    return _make
