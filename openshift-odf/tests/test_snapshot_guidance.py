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

def test_standalone_smoke_cleanup_pins_target_context():
    """Standalone filesystem and object cleanup must not use the current context."""
    guide = (ROOT / "references/validation-hardening.md").read_text(encoding="utf-8")
    assert 'cleanup_smoke_namespace.sh --namespace odf-smoke --context "<target-context>"' in guide
    assert 'cleanup_smoke_namespace.sh --namespace odf-object-smoke --object --context "<target-context>"' in guide
