"""Contract tests for the ODF SNO pre-flight gate routing invariants.

The gate is the only thing that stops the generic install path from being
followed on a SNO cluster running an ODF release with known regressions. It is
prose, so nothing else fails when it is weakened or removed — these tests pin
the invariants: topology discovery exists, both affected channels are named,
the gate precedes the generic install steps, and each version routes to its
validated procedure.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO_ROOT / "openshift-odf" / "references" / "install-and-preflight.md"
VALIDATED = REPO_ROOT / "openshift-odf" / "references" / "validated-odf-sno.md"

GATE_HEADING = "## SNO Pre-flight Gate"
SIZING_HEADING = "## Sizing And Prerequisites"


def _preflight_text() -> str:
    return PREFLIGHT.read_text(encoding="utf-8")


def _gate_section(text: str) -> str:
    start = text.find(GATE_HEADING)
    assert start != -1, f"missing {GATE_HEADING!r} section"
    rest = text[start + len(GATE_HEADING) :]
    next_heading = rest.find("\n## ")
    return rest if next_heading == -1 else rest[:next_heading]


def test_topology_discovery_command_is_documented():
    # The gate keys off controlPlaneTopology, so the runbook must show how to
    # read it rather than expecting the operator to already know the topology.
    text = _preflight_text()
    assert "oc get infrastructure cluster" in text
    assert "{.status.controlPlaneTopology}" in text


def test_gate_names_both_affected_channels():
    gate = _gate_section(_preflight_text())
    assert "SingleReplica" in gate
    assert "stable-4.20" in gate
    assert "stable-4.22" in gate


def test_gate_stops_before_the_generic_install_path():
    # Ordering is the whole point: a gate placed after the install steps would
    # be read too late.
    text = _preflight_text()
    gate_at = text.find(GATE_HEADING)
    sizing_at = text.find(SIZING_HEADING)
    assert gate_at != -1 and sizing_at != -1
    assert gate_at < sizing_at, "SNO gate must precede the generic install path"
    assert "stop here" in _gate_section(text).lower()


def test_gate_routes_each_version_to_its_validated_procedure():
    gate = _gate_section(_preflight_text())
    assert "references/validated-odf-sno.md" in gate
    assert "ODF 4.20 SNO" in gate
    assert "ODF 4.22 SNO" in gate


def test_gate_targets_exist_in_the_validated_runbook():
    # A route that points at a section which does not exist is a dead end.
    validated = VALIDATED.read_text(encoding="utf-8")
    assert "ODF 4.20 SNO" in validated
    assert "ODF 4.22 SNO" in validated


def test_unlisted_versions_still_have_a_documented_path():
    # The gate must not strand operators on releases nobody has validated yet.
    gate = _gate_section(_preflight_text())
    assert "not listed" in gate
