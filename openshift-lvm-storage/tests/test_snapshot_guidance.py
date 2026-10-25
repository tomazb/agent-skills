"""Preserve operator ownership and thin-pool snapshot constraints."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lvms_reuses_managed_classes_before_creating_custom_ones():
    text = (ROOT / "references/backup-restore-dr.md").read_text(encoding="utf-8")
    assert "lvms-<device-class>" in text
    assert "operator-managed" in text
    assert "thin" in text
    assert "WaitForFirstConsumer" in text
    assert "readyToUse" in text
    assert "node failure destroys the snapshot" not in text.lower()
