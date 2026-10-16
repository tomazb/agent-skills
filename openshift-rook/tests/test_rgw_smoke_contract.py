from pathlib import Path

REFERENCE = (
    Path(__file__).resolve().parents[1] / "references" / "rgw-object-store.md"
)


def test_rgw_smoke_puts_an_object_before_cleanup():
    text = REFERENCE.read_text()
    put_at = text.index("s3.put_object")
    marker_at = text.index("rook-rgw-smoke-ok")
    cleanup_at = text.index(
        "bash scripts/cleanup_smoke_namespace.sh --namespace rook-rgw-smoke --object"
    )
    assert put_at < marker_at < cleanup_at
    assert 'scheme = "https" if port in ("443", "8443") else "http"' in text
    assert "odf-object-smoke-ok" not in text
    assert "https://https://" not in text
