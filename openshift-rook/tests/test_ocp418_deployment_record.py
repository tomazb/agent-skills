"""Keep deployment evidence patch-specific and preserve its safety boundaries."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "references" / "ocp-4.18-sno-deployment.md"


def test_deployment_record_is_discoverable_and_preserves_storage_isolation():
    record = RECORD.read_text(encoding="utf-8")
    for entry in ("SKILL.md", "README.md", "references/install-and-preflight.md"):
        assert "ocp-4.18-sno-deployment.md" in (ROOT / entry).read_text(encoding="utf-8")
    for evidence in (
        "/dev/disk/by-id/<osd-disk-id>",
        "The OS disk and the smaller LVMS disk were excluded",
        "lvms-vg1` remains the sole Kubernetes default",
        "requireSafeReplicaSize: false",
        "snapshotPolicy: volumeSnapshot",
        "No off-cluster backup was configured",
    ):
        assert evidence in record


def test_kernel_failure_is_not_a_minor_version_support_claim():
    record = RECORD.read_text(encoding="utf-8")
    for evidence in (
        "OpenShift 4.18.44",
        "Kubernetes v1.31.14",
        "5.14.0-427.130.1.el9_4.x86_64",
        "FIPS disabled",
        "Rook v1.20.10",
        "ceph-csi v3.17.1",
        "rbd: map failed: (524) Unknown error 524",
        "all OpenShift 4.18 patches lack support",
        "does not establish",
        "first fixed kernel",
        "Rook v1.21 requires Kubernetes 1.32",
        "Re-run the live mount/write probe",
    ):
        assert evidence in record


def test_csi_exception_does_not_relax_strict_acceptance():
    record = RECORD.read_text(encoding="utf-8")
    for evidence in (
        "After explicit approval",
        "keepPriorKeyCountMax: 1",
        "Daemon keys remained AES256K",
        "permits classic AES cluster-wide",
        "No downgrade or second disk wipe",
        "AUTH_INSECURE_CLIENT_KEY_TYPE",
        "AUTH_INSECURE_KEYS_ALLOWED",
        "AUTH_INSECURE_KEYS_CREATABLE",
        "No warnings were\nmuted",
        "strict `scripts/check_rook_health.py` correctly failed",
        "122 seconds over nine samples",
        "not a change to the strict checker or a default warning allowlist",
        "Raw-block mode and CephFS recovery were not tested",
    ):
        assert evidence in record
