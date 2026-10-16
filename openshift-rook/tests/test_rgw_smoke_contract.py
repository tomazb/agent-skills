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


def test_rgw_smoke_runs_a_pod_in_the_smoke_namespace_before_cleanup():
    text = REFERENCE.read_text()
    cleanup_at = text.index(
        "bash scripts/cleanup_smoke_namespace.sh --namespace rook-rgw-smoke --object"
    )
    pod_at = text.index("kind: Pod")
    assert pod_at < text.index("s3.put_object") < cleanup_at
    pod = text[pod_at:cleanup_at]
    assert "namespace: rook-rgw-smoke" in pod
    envfrom_at = pod.index("envFrom:")
    assert "name: rook-ceph-obc" in pod[envfrom_at:]
    assert "configMapRef:" in pod[envfrom_at:]
    assert "secretRef:" in pod[envfrom_at:]
    for setting in (
        "allowPrivilegeEscalation: false",
        "runAsNonRoot: true",
        'drop: ["ALL"]',
        "type: RuntimeDefault",
    ):
        assert setting in pod
