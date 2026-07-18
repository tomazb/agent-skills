"""Contract tests for Rook/ODF ownership routing pressure scenarios."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = Path(__file__).resolve().parent / "storage_ownership_scenarios"


def _skill_text(name: str) -> str:
    return (REPO_ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def _gate_section(skill_text: str) -> str:
    marker = "## Product Ownership Gate"
    start = skill_text.find(marker)
    assert start != -1, "missing Product Ownership Gate section"
    rest = skill_text[start + len(marker) :]
    next_heading = rest.find("\n## ")
    return rest if next_heading == -1 else rest[:next_heading]


def test_pressure_scenario_files_exist():
    expected = {
        "ambiguous-ceph-ownership.md",
        "odf-managed-upstream-rook-request.md",
        "upstream-rook-odf-remediation-request.md",
    }
    present = {path.name for path in SCENARIO_DIR.glob("*.md")}
    assert expected <= present


def test_rook_and_odf_skills_encode_ownership_contract():
    for skill_name, peer in (
        ("openshift-rook", "openshift-odf"),
        ("openshift-odf", "openshift-rook"),
    ):
        skill_text = _skill_text(skill_name)
        gate = _gate_section(skill_text)
        assert "StorageCluster" in gate
        assert "CephCluster" in gate
        assert "Subscription" in gate or "CSV" in gate
        assert peer in gate
        assert "namespace" in gate.lower()
        lowered = gate.lower()
        assert any(
            token in lowered
            for token in ("mixed", "conflict", "unknown", "insufficient")
        )
        assert any(
            token in lowered for token in ("stop", "do not", "never", "refuse", "hand off")
        )


def test_ambiguous_scenario_requires_discovery_before_mutation():
    scenario = (SCENARIO_DIR / "ambiguous-ceph-ownership.md").read_text(encoding="utf-8")
    assert "read-only ownership discovery" in scenario
    assert "Do not recommend" in scenario or "refuses mutation" in scenario.lower()


def test_odf_owned_scenario_blocks_upstream_rook():
    scenario = (
        SCENARIO_DIR / "odf-managed-upstream-rook-request.md"
    ).read_text(encoding="utf-8")
    assert "openshift-odf" in scenario
    assert "Refuse upstream Rook" in scenario or "Blocks upstream Rook" in scenario


def test_rook_owned_scenario_blocks_odf_layering():
    scenario = (
        SCENARIO_DIR / "upstream-rook-odf-remediation-request.md"
    ).read_text(encoding="utf-8")
    assert "openshift-rook" in scenario
    assert "Refuse installing ODF" in scenario or "Blocks layering ODF" in scenario
