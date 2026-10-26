"""Health reporting must expose unconfigured storage recovery features."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_readiness_is_in_the_storage_phase_and_output():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    storage_phase = skill.split("### Phase 8", 1)[1].split("### Phase 9", 1)[0]
    assert "VolumeSnapshotClass" in storage_phase
    assert "Warning" in storage_phase
    assert "| Snapshot readiness |" in skill
    assert "| Snapshot readiness |" in (ROOT / "references/output-contract.md").read_text(encoding="utf-8")
