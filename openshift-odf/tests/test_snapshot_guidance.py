"""Snapshot setup must respect ODF ownership and verify recovery."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_odf_recovers_managed_snapshot_classes_through_the_operator():
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    assert "operator-managed" in text
    assert "reconciliation" in text
    assert "do not overwrite" in text.lower()
    assert "readyToUse" in text
    assert "dataSource" in text
