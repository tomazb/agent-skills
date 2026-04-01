from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "tools" / "validate_skill_package.py"


def make_skill_text(*, missing_phases: list[int] | None = None) -> str:
    """Generate a minimal valid SKILL.md with all Phase 0-16 headings.

    Pass ``missing_phases`` to omit specific phase headings for negative tests.
    """
    skip = set(missing_phases or [])
    lines = [
        "---",
        "name: openshift-cluster-health-check",
        "description: demo",
        "---",
        "",
        "# OpenShift Cluster Health Check",
        "",
    ]
    for phase_num in range(0, 17):
        if phase_num in skip:
            continue
        lines.append(f"### Phase {phase_num} \u2014 Example")
        lines.append("")
        lines.append(f"Phase {phase_num} guidance.")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
                    json.dumps(
                        {"name": "openshift-cluster-health-check", "version": "1.2.3"},
                        indent=2,
                    )
                    + "\n"
                )
            (root / "package.json").write_text(package_json_text, encoding="utf-8")

        return root

    return _make
