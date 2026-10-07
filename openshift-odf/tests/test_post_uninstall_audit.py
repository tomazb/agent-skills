from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cluster_fake import (  # noqa: E402
    OLD,
    ceph_cluster,
    merge,
    meta,
    recent,
    rook_operator,
    run_script,
    write_cluster_oc,
    write_jq_proxy,
    write_oc,
)

_write_jq_proxy = write_jq_proxy
_write_oc = write_oc
_write_cluster_oc = write_cluster_oc


def _run_audit(
    bin_dir: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return run_script("post_uninstall_audit.sh", bin_dir, *args)


def test_audit_fails_when_oc_is_missing(tmp_path):
    _write_jq_proxy(tmp_path)

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: oc CLI is required but not installed" in result.stdout


def test_audit_reports_api_resource_query_failures(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args[:2] == ["get", "namespace"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:1] == ["api-resources"]:
            print("forbidden", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: ocs.openshift.io API resource discovery failed" in result.stdout
    assert "OK: no ocs.openshift.io API resources found" not in result.stdout


def test_audit_fails_for_leftover_api_groups_and_rook_namespace(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args == ["get", "namespace", "openshift-storage"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args == ["get", "namespace", "rook-ceph"]:
            print("NAME\\nrook-ceph")
            raise SystemExit(0)
        if args[:1] == ["api-resources"]:
            group = next((a.split("=", 1)[1] for a in args if a.startswith("--api-group=")), "")
            if group == "noobaa.io":
                print("noobaas.noobaa.io")
            raise SystemExit(0)
        if args[:1] == ["get"] and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: rook-ceph namespace still exists" in result.stdout
    assert "WARN: noobaa.io API resources still exist:" in result.stdout
    assert "OK: no csi.ceph.io API resources found" in result.stdout
    assert "OK: no local.storage.openshift.io API resources found" in result.stdout


def test_audit_fails_for_leftover_object_bucket_claims(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args[:1] == ["api-resources"]:
            raise SystemExit(0)
        if args[:2] == ["get", "namespace"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:2] == ["get", "obc"] and "-o" in args:
            print(json.dumps({"items": [{"metadata": {"namespace": "app", "name": "bucket"}}]}))
            raise SystemExit(0)
        if args[:1] == ["get"] and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF ObjectBucketClaims still exist:" in result.stdout
    assert "app/bucket" in result.stdout


def test_audit_passes_when_no_odf_residue_remains(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args[:1] == ["api-resources"]:
            raise SystemExit(0)
        if args[:2] == ["get", "namespace"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:2] == ["get", "sc"] and "-o" in args:
            print(
                json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {
                                    "name": "platform-default",
                                    "annotations": {
                                        "storageclass.kubernetes.io/is-default-class": "true"
                                    },
                                },
                                "provisioner": "kubernetes.io/no-provisioner",
                            }
                        ]
                    }
                )
            )
            raise SystemExit(0)
        if args[:1] == ["get"] and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 0
    assert "OK: openshift-storage namespace absent" in result.stdout
    assert "OK: rook-ceph namespace absent" in result.stdout
    assert "OK: no noobaa.io API resources found" in result.stdout
    assert "OK: no csi.ceph.io API resources found" in result.stdout
    assert "OK: no local.storage.openshift.io API resources found" in result.stdout
    assert "OK: no ODF ObjectBucketClaims found" in result.stdout
    assert "OK: exactly one default StorageClass: platform-default" in result.stdout
    assert "WARN:" not in result.stdout
    assert "FAIL:" not in result.stdout


def test_audit_accepts_namespace_kept_for_lvms_but_flags_odf_residue(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args == ["get", "namespace", "openshift-storage"]:
            print("NAME\\nopenshift-storage")
            raise SystemExit(0)
        if args == ["get", "namespace", "rook-ceph"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:1] == ["api-resources"]:
            raise SystemExit(0)
        if args[:2] == ["get", "subscription"] and "-n" in args and "-o" in args:
            print(json.dumps({"items": [
                {"metadata": {"name": "lvms-operator"}, "spec": {"name": "lvms-operator"}},
            ]}))
            raise SystemExit(0)
        if args[:2] == ["get", "subscription"] and "-A" in args and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        if args[0] == "get" and args[1].startswith("secrets") and "-o" in args:
            print(json.dumps({"items": [
                {"kind": "Secret", "metadata": {"name": "rook-ceph-mon"}},
                {"kind": "ConfigMap", "metadata": {"name": "lvms-config"}},
            ]}))
            raise SystemExit(0)
        if args[:1] == ["get"] and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert (
        "OK: openshift-storage namespace kept for non-ODF operators: lvms-operator"
        in result.stdout
    )
    assert "WARN: ODF residue objects in openshift-storage still exist:" in result.stdout
    assert "rook-ceph-mon" in result.stdout
    assert "lvms-config" not in result.stdout


def test_audit_passes_when_namespace_and_lso_are_retained_without_residue(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args == ["get", "namespace", "openshift-storage"]:
            print("NAME\\nopenshift-storage")
            raise SystemExit(0)
        if args == ["get", "namespace", "rook-ceph"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:1] == ["api-resources"]:
            group = next((a.split("=", 1)[1] for a in args if a.startswith("--api-group=")), "")
            if group == "local.storage.openshift.io":
                print("localvolumesets.local.storage.openshift.io")
            raise SystemExit(0)
        if args[:2] == ["get", "subscription"] and "-n" in args and "-o" in args:
            print(json.dumps({"items": [
                {"metadata": {"name": "lvms-operator"}, "spec": {"name": "lvms-operator"}},
                {"metadata": {"name": "local-storage-operator"}, "spec": {"name": "local-storage-operator"}},
            ]}))
            raise SystemExit(0)
        if args[:2] == ["get", "subscription"] and "-A" in args and "-o" in args:
            print(json.dumps({"items": [
                {"metadata": {"name": "local-storage-operator"}, "spec": {"name": "local-storage-operator"}},
            ]}))
            raise SystemExit(0)
        if args[:2] == ["get", "sc"] and "-o" in args:
            print(json.dumps({"items": [
                {
                    "metadata": {
                        "name": "lvms-vg1",
                        "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
                    },
                    "provisioner": "topolvm.io",
                }
            ]}))
            raise SystemExit(0)
        if args[:1] == ["get"] and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 0
    assert "OK: openshift-storage namespace kept for non-ODF operators:" in result.stdout
    assert "OK: no ODF residue objects in openshift-storage" in result.stdout
    assert "OK: local.storage.openshift.io CRDs retained: LSO still installed" in result.stdout
    assert "OK: no odf.openshift.io API resources found" in result.stdout
    assert "OK: no postgresql.cnpg.noobaa.io API resources found" in result.stdout
    assert "OK: no csiaddons.openshift.io API resources found" in result.stdout
    assert "OK: no objectbucket.io API resources found" in result.stdout
    assert "WARN:" not in result.stdout
    assert "FAIL:" not in result.stdout


def test_audit_flags_leftover_odf_subscription_in_a_shared_namespace(tmp_path):
    # A surviving ODF subscription re-creates its CSV and workloads. Reporting the
    # namespace as "kept for lvms-operator" and stopping there hides that.
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args == ["get", "namespace", "openshift-storage"]:
            print("NAME\\nopenshift-storage")
            raise SystemExit(0)
        if args == ["get", "namespace", "rook-ceph"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:1] == ["api-resources"]:
            raise SystemExit(0)
        if args[:2] == ["get", "subscription"] and "-n" in args and "-o" in args:
            print(json.dumps({"items": [
                {"metadata": {"name": "lvms-operator"}, "spec": {"name": "lvms-operator"}},
                {"metadata": {"name": "odf-operator"}, "spec": {"name": "odf-operator"}},
            ]}))
            raise SystemExit(0)
        if args[:2] == ["get", "csv"] and "-o" in args:
            print(json.dumps({"items": [
                {"metadata": {"name": "odf-operator.v4.22.1-rhodf"}},
                {"metadata": {"name": "lvms-operator.v4.22.0"}},
            ]}))
            raise SystemExit(0)
        if args[:1] == ["get"] and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF subscriptions still in openshift-storage" in result.stdout
    assert "odf-operator" in result.stdout
    # the CSV the subscription would re-install from must be flagged too, and the
    # co-tenant's own CSV must not be
    assert "WARN: ODF CSVs still in openshift-storage" in result.stdout
    assert "odf-operator.v4.22.1-rhodf" in result.stdout
    assert "lvms-operator.v4.22.0" not in result.stdout


def test_audit_flags_leftover_odf_statefulset_residue(tmp_path):
    # NooBaa runs as StatefulSets (noobaa-core, noobaa-db-pg); omitting the kind
    # from the residue sweep lets them survive a "clean" audit.
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args == ["get", "namespace", "openshift-storage"]:
            print("NAME\\nopenshift-storage")
            raise SystemExit(0)
        if args == ["get", "namespace", "rook-ceph"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:1] == ["api-resources"]:
            raise SystemExit(0)
        if args[:2] == ["get", "subscription"] and "-n" in args and "-o" in args:
            print(json.dumps({"items": [
                {"metadata": {"name": "lvms-operator"}, "spec": {"name": "lvms-operator"}},
            ]}))
            raise SystemExit(0)
        if args[:2] == ["get", "statefulsets"] and "-n" in args and "-o" in args:
            print(json.dumps({"items": [
                {"kind": "StatefulSet", "metadata": {"name": "noobaa-db-pg"}},
            ]}))
            raise SystemExit(0)
        if args[:1] == ["get"] and "-o" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF residue objects in openshift-storage still exist:" in result.stdout
    assert "noobaa-db-pg" in result.stdout



def test_audit_rejects_unknown_arguments(tmp_path):
    """Regression: the script had no argument parsing at all.

    `--context other-cluster` was silently ignored, so the audit ran against
    whatever context happened to be current and reported those findings as if
    they were the requested cluster's. Unknown arguments must now be fatal.
    """
    result = _run_audit(tmp_path, "--bogus")
    assert result.returncode == 2
    assert "unknown argument: --bogus" in result.stderr


def test_audit_help_exits_zero(tmp_path):
    result = _run_audit(tmp_path, "--help")
    assert result.returncode == 0
    assert "Usage: post_uninstall_audit.sh" in result.stdout


@pytest.mark.parametrize("flag", ["--context", "--kubeconfig"])
def test_audit_rejects_flag_without_value(tmp_path, flag):
    result = _run_audit(tmp_path, flag)
    assert result.returncode == 2
    assert f"{flag} requires a value" in result.stderr


def test_audit_forwards_context_to_oc(tmp_path):
    """--context must reach every `oc` invocation, not just be accepted."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_jq_proxy(bin_dir)
    argv_log = tmp_path / "argv.log"
    _write_oc(
        bin_dir,
        f"""
        with open({str(argv_log)!r}, "a") as fh:
            fh.write(" ".join(sys.argv[1:]) + chr(10))
        sys.exit(1)
        """,
    )
    _run_audit(bin_dir, "--context", "htz2")
    recorded = argv_log.read_text(encoding="utf-8").splitlines()
    assert recorded, "no oc invocation was recorded"
    assert all(line.startswith("--context=htz2 ") for line in recorded), recorded


def test_audit_banner_names_the_requested_context(tmp_path):
    """The banner must report the context that was asked for.

    `oc config current-context` keeps printing the kubeconfig's own current
    context even when --context overrides the request target, so reporting it
    would name the wrong cluster on exactly the runs where it matters.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_jq_proxy(bin_dir)
    _write_oc(
        bin_dir,
        """
        args = sys.argv[1:]
        if "config" in args and "current-context" in args:
            print("some-other-context")
            sys.exit(0)
        if "whoami" in args and "--show-server" in args:
            print("https://api.cluster-under-test.example:6443")
            sys.exit(0)
        if "whoami" in args:
            print("tester")
            sys.exit(0)
        sys.exit(1)
        """,
    )
    result = _run_audit(bin_dir, "--context", "htz2")
    assert "auditing https://api.cluster-under-test.example:6443 (context: htz2)" in result.stdout
    assert "some-other-context" not in result.stdout



@pytest.mark.parametrize("arg", ["--context=", "--kubeconfig="])
def test_audit_rejects_empty_inline_option_values(tmp_path, arg):
    """`--context=` matched the `--context=*` branch and skipped the value check.

    oc treats an empty `--context=` as "no override" rather than an error, so the
    audit would silently run against the current context after being told to use
    a specific one - the same class of failure the argument parsing was added to
    prevent.
    """
    result = _run_audit(tmp_path, arg)
    assert result.returncode == 2
    assert "requires a value" in result.stderr


# The tests below run against cluster_fake's world-driven `oc`.


def _sa(namespace: str, name: str) -> dict:
    return {"metadata": meta(name, namespace)}


def _sa_subject(namespace: str, name: str) -> dict:
    return {"kind": "ServiceAccount", "namespace": namespace, "name": name}


def _crb(name: str, role: str, subjects: list, labels: dict | None = None) -> dict:
    return {
        "metadata": meta(name, labels=labels or {}),
        "roleRef": {"kind": "ClusterRole", "name": role},
        "subjects": subjects,
    }


def _cr(name: str, labels: dict | None = None, aggregation: list | None = None) -> dict:
    role = {"metadata": meta(name, labels=labels or {})}
    if aggregation is not None:
        role["aggregationRule"] = {"clusterRoleSelectors": aggregation}
    return role


ROOK_OWNER = {"olm.owner": "rook-ceph-operator.v4.20.17-rhodf"}
OCS_OWNER = {"olm.owner": "ocs-operator.v4.20.17-rhodf"}

# Cluster shape after an ODF uninstall next to an upstream (non-OLM) Rook cluster in
# rook-ceph: its operator, the shared Rook groups, its SCCs, a claim it serves, and
# RBAC that still carries ODF's OLM label while the running Rook uses it.
ROOK_GROUPS = {
    "ceph.rook.io": [["cephclusters.ceph.rook.io", True]],
    "csi.ceph.io": [["drivers.csi.ceph.io", True]],
    "objectbucket.io": [
        ["objectbucketclaims.objectbucket.io", True],
        ["objectbuckets.objectbucket.io", False],
    ],
}


def _rook_objects() -> dict:
    return {
        "deployments": [rook_operator()],
        "cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")],
        "drivers.csi.ceph.io": [
            {"kind": "Driver", "metadata": meta("rook-ceph.rbd.csi.ceph.com", "rook-ceph")}
        ],
        "objectbucketclaims.objectbucket.io": [
            {"kind": "ObjectBucketClaim", "metadata": meta("rook-bucket", "app")}
        ],
        "scc": [
            {
                "metadata": meta("rook-ceph"),
                "users": ["system:serviceaccount:rook-ceph:rook-ceph-system"],
            },
            {
                "metadata": meta("rook-ceph-csi"),
                "users": ["system:serviceaccount:rook-ceph:rook-csi-rbd-plugin-sa"],
            },
        ],
        "sc": [{"metadata": meta("rook-ceph-bucket"), "provisioner": "rook-ceph.ceph.rook.io/bucket"}],
        "obc": [
            {"metadata": meta("rook-bucket", "app"), "spec": {"storageClassName": "rook-ceph-bucket"}}
        ],
        "objectbucket": [
            {"metadata": meta("obc-app-rook-bucket"), "spec": {"storageClassName": "rook-ceph-bucket"}}
        ],
        "configmaps": [
            {"kind": "ConfigMap", "metadata": meta("rook-bucket", "app", finalizers=["objectbucket.io/finalizer"])}
        ],
        "secrets": [
            {"kind": "Secret", "metadata": meta("rook-bucket", "app", finalizers=["objectbucket.io/finalizer"])}
        ],
        "serviceaccounts": [
            _sa("rook-ceph", "objectstorage-provisioner"),
            _sa("openshift-monitoring", "prometheus-k8s"),
        ],
        "clusterroles": [
            _cr("objectstorage-provisioner-role", ROOK_OWNER),
            _cr("rook-ceph-metrics", ROOK_OWNER),
        ],
        "clusterrolebindings": [
            _crb(
                "objectstorage-provisioner-role-binding",
                "objectstorage-provisioner-role",
                [_sa_subject("rook-ceph", "objectstorage-provisioner")],
                ROOK_OWNER,
            ),
            _crb(
                "rook-ceph-metrics",
                "rook-ceph-metrics",
                [_sa_subject("openshift-monitoring", "prometheus-k8s")],
                ROOK_OWNER,
            ),
        ],
    }


def _assert_clean(result) -> None:
    assert result.returncode == 0, result.stdout
    assert "WARN:" not in result.stdout
    assert "FAIL:" not in result.stdout


def test_audit_reports_stuck_pvc_and_pv_by_deletion_timestamp(tmp_path):
    # A deleting PVC or PV keeps phase Bound/Released; "Terminating" is not a phase.
    # The old `.status.phase == "Terminating"` test could never fire.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "pvc": [
                {
                    "metadata": meta(
                        "db-noobaa-db-pg-cluster-1",
                        "openshift-storage",
                        deletionTimestamp=OLD,
                        finalizers=["kubernetes.io/pvc-protection"],
                    ),
                    "status": {"phase": "Bound"},
                }
            ],
            "pv": [
                {
                    "metadata": meta(
                        "pvc-released",
                        deletionTimestamp=OLD,
                        finalizers=["kubernetes.io/pv-protection"],
                    ),
                    "status": {"phase": "Released"},
                }
            ],
        },
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert (
        "WARN: PVCs Terminating for over 10 minutes (younger deletions ignored) still exist:"
        in result.stdout
    )
    assert (
        "openshift-storage/db-noobaa-db-pg-cluster-1 (phase Bound, finalizers: kubernetes.io/pvc-protection)"
        in result.stdout
    )
    assert (
        "WARN: PVs Terminating for over 10 minutes (younger deletions ignored) still exist:"
        in result.stdout
    )
    assert "pvc-released (phase Released" in result.stdout


def test_audit_ignores_deletions_younger_than_the_threshold(tmp_path):
    _write_jq_proxy(tmp_path)
    just_now = recent()
    _write_cluster_oc(
        tmp_path,
        objects={
            "pvc": [
                {"metadata": meta("data", "app", deletionTimestamp=just_now), "status": {"phase": "Bound"}}
            ],
            "pv": [{"metadata": meta("pv-data", deletionTimestamp=just_now), "status": {"phase": "Bound"}}],
            "namespaces": [
                {"metadata": meta("app", deletionTimestamp=just_now), "status": {"phase": "Terminating"}}
            ],
            "pods": [
                {
                    "metadata": meta("vg-manager-abcde", "openshift-storage", deletionTimestamp=just_now),
                    "status": {"phase": "Running"},
                }
            ],
        },
    )

    result = _run_audit(tmp_path)

    _assert_clean(result)
    for line in (
        "OK: no PVCs Terminating for over 10 minutes (younger deletions ignored)",
        "OK: no PVs Terminating for over 10 minutes (younger deletions ignored)",
        "OK: no namespaces Terminating for over 10 minutes (younger deletions ignored)",
        "OK: no pods in openshift-storage deleting for over 10 minutes (younger deletions ignored)",
    ):
        assert line in result.stdout


def test_audit_passes_on_a_clean_cluster_with_every_new_check(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "pvc": [{"metadata": meta("data", "app"), "status": {"phase": "Bound"}}],
            "namespaces": [{"metadata": meta("app"), "status": {"phase": "Active"}}],
            "volumeattachment": [
                {"metadata": meta("csi-other"), "spec": {"attacher": "topolvm.io"}}
            ],
            "clusterroles": [_cr("admin")],
        },
    )

    result = _run_audit(tmp_path)

    _assert_clean(result)
    for line in (
        "OK: no namespaces Terminating for over 10 minutes (younger deletions ignored)",
        "OK: no ODF VolumeAttachments found",
        "OK: no ODF pods in openshift-storage",
        "OK: no ODF ObjectBuckets found",
        "OK: no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim",
        "OK: no replication.storage.openshift.io API resources found",
        "OK: no ramendr.openshift.io API resources found",
        "OK: no groupsnapshot.storage.openshift.io API resources found",
        "OK: no CephClusters left by ODF or being deleted",
        "OK: no dead ODF ClusterRoles or ClusterRoleBindings found",
    ):
        assert line in result.stdout


def test_audit_tolerates_absent_new_kinds(tmp_path):
    # Kinds reported as unknown types must read as "none", not as a failed audit.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        unserved=(
            "volumeattachment",
            "cephclusters.ceph.rook.io",
            "deployments",
            "obc",
            "objectbucket",
            "namespaces",
            "pods",
            "clusterroles",
        ),
    )

    result = _run_audit(tmp_path)

    _assert_clean(result)
    assert "OK: no ODF VolumeAttachments found" in result.stdout
    assert "OK: no CephClusters left by ODF or being deleted" in result.stdout
    assert "OK: no ODF ObjectBucketClaims found" in result.stdout
    assert "OK: no dead ODF ClusterRoles or ClusterRoleBindings found" in result.stdout


@pytest.mark.parametrize("noise", [False, True], ids=["quiet", "stderr-noise"])
def test_audit_treats_a_running_upstream_rook_cluster_as_retained(tmp_path, noise):
    # With noise, every oc call also prints a client-side throttling line on
    # stderr. A successful call must still be evaluated from its JSON alone.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_rook_objects(),
        groups=ROOK_GROUPS,
        namespaces=("rook-ceph",),
        noise=noise,
    )

    result = _run_audit(tmp_path)

    _assert_clean(result)
    for line in (
        "OK: namespace rook-ceph retained: part of an upstream (non-OLM) Rook cluster",
        "OK: ceph.rook.io API resources retained for upstream Rook in: rook-ceph",
        "OK: csi.ceph.io API resources retained for upstream Rook in: rook-ceph",
        "OK: objectbucket.io API resources retained for upstream Rook in: rook-ceph",
        "OK: no ceph.rook.io objects outside upstream Rook namespaces",
        "OK: no csi.ceph.io objects outside upstream Rook namespaces",
        # the Rook-served claim in "app" is decided by its StorageClass, not its namespace
        "OK: no objectbucket.io objects outside upstream Rook namespaces",
        "OK: SCC rook-ceph retained: every user is a service account in an upstream Rook namespace",
        "OK: SCC rook-ceph-csi retained: every user is a service account in an upstream Rook namespace",
        "OK: no ODF SCCs found",
        "OK: no ODF ObjectBucketClaims found",
        "OK: no ODF ObjectBuckets found",
        "OK: no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim",
        "OK: no CephClusters left by ODF or being deleted",
    ):
        assert line in result.stdout


def test_audit_counts_a_rook_operator_without_a_ceph_cluster_as_upstream_rook(tmp_path):
    # The operator is up but its CephCluster is not (yet, or again) created: the
    # shared CRDs are still Rook's.
    _write_jq_proxy(tmp_path)
    objects = _rook_objects()
    del objects["cephclusters.ceph.rook.io"]
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    _assert_clean(result)
    assert "OK: namespace rook-ceph retained" in result.stdout
    assert "OK: ceph.rook.io API resources retained for upstream Rook in: rook-ceph" in result.stdout


@pytest.mark.parametrize(
    ("operator", "unknown"),
    [
        (
            rook_operator(labels={"olm.owner": "rook-ceph-operator.v1.20.5"}),
            "rook-ceph/rook-ceph-operator (Deployment installed by OLM",
        ),
        (
            rook_operator(labels={"operators.coreos.com/rook-ceph.rook-ceph": ""}),
            "rook-ceph/rook-ceph-operator (Deployment installed by OLM",
        ),
        (
            rook_operator(deletionTimestamp=OLD),
            "rook-ceph/rook-ceph (no non-OLM rook-ceph-operator Deployment outside openshift-storage",
        ),
        (
            rook_operator(namespace="openshift-storage"),
            "rook-ceph/rook-ceph (no non-OLM rook-ceph-operator Deployment outside openshift-storage",
        ),
    ],
    ids=["olm-owner", "olm-package-label", "deleting", "in-openshift-storage"],
)
def test_audit_does_not_excuse_shared_groups_when_rook_ownership_is_unknown(tmp_path, operator, unknown):
    _write_jq_proxy(tmp_path)
    objects = _rook_objects()
    objects["deployments"] = [operator]
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "retained for upstream Rook" not in result.stdout
    assert "WARN: ceph.rook.io API resources still exist:" in result.stdout
    assert "WARN: rook-ceph namespace still exists" in result.stdout
    assert "WARN: Rook objects whose owner cannot be classified still exist:" in result.stdout
    assert unknown in result.stdout


@pytest.mark.parametrize(
    ("cluster", "reason"),
    [
        # orphaned by an interrupted uninstall: no StorageCluster left to own it
        (ceph_cluster("ocs-storagecluster-cephcluster", "openshift-storage"), "in openshift-storage"),
        (
            ceph_cluster(
                "ocs-storagecluster-cephcluster",
                "ocs-elsewhere",
                ownerReferences=[{"kind": "StorageCluster", "name": "ocs-storagecluster"}],
            ),
            "owned by a StorageCluster",
        ),
        # StorageCluster ownerReference stripped by hand, in the Rook namespace
        (ceph_cluster("ocs-storagecluster-cephcluster", "rook-ceph"), "carries the ODF CephCluster name"),
        (ceph_cluster("second", "rook-ceph", deletionTimestamp=OLD), "being deleted"),
    ],
    ids=["openshift-storage", "storagecluster-owned", "odf-name", "deleting"],
)
def test_audit_flags_ceph_clusters_left_by_odf_or_being_deleted(tmp_path, cluster, reason):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=merge(_rook_objects(), {"cephclusters.ceph.rook.io": [cluster]}),
        groups=ROOK_GROUPS,
        namespaces=("rook-ceph",),
    )

    result = _run_audit(tmp_path)
    name = f"{cluster['metadata']['namespace']}/{cluster['metadata']['name']}"

    assert result.returncode == 1
    assert "WARN: CephClusters left by ODF or being deleted still exist:" in result.stdout
    assert f"{name} ({reason})" in result.stdout
    assert "OK: every CephCluster and rook-ceph-operator has a classified owner" in result.stdout
    assert "OK: ceph.rook.io API resources retained for upstream Rook in: rook-ceph\n" in result.stdout
    if cluster["metadata"]["namespace"] != "rook-ceph":
        assert (
            "WARN: ceph.rook.io objects outside upstream Rook namespaces still exist:" in result.stdout
        )
        assert f"CephCluster/{name}" in result.stdout


def test_audit_treats_a_cluster_watched_from_another_namespace_as_upstream_rook(tmp_path):
    # Rook's operator watches every namespace by default: an operator in rook-ceph
    # and a CephCluster in storage-b are one upstream Rook installation.
    _write_jq_proxy(tmp_path)
    objects = _rook_objects()
    objects["cephclusters.ceph.rook.io"] = [ceph_cluster("b", "storage-b")]
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    _assert_clean(result)
    assert "OK: namespace rook-ceph retained: part of an upstream (non-OLM) Rook cluster" in result.stdout
    assert "OK: namespace storage-b retained: part of an upstream (non-OLM) Rook cluster" in result.stdout
    assert "OK: ceph.rook.io API resources retained for upstream Rook in: rook-ceph storage-b" in result.stdout


def test_audit_does_not_take_a_client_side_error_for_none(tmp_path):
    # `oc --context nope` fails with "context was not found"; that is not "there
    # are none" and must not produce an OK line.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        errors={"pv": "Error in configuration: * context was not found for specified context: nope"},
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: PVs Terminating for over 10 minutes (younger deletions ignored) query failed" in result.stdout
    assert "OK: no PVs Terminating" not in result.stdout
    assert "OK: no ODF PVs found" not in result.stdout


def test_audit_flags_shared_group_objects_outside_rook_namespaces(tmp_path):
    _write_jq_proxy(tmp_path)
    objects = merge(
        _rook_objects(),
        {"drivers.csi.ceph.io": [{"kind": "Driver", "metadata": meta("openshift-storage.rbd.csi.ceph.com", "lvms")}]},
    )
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert (
        "WARN: csi.ceph.io objects outside upstream Rook namespaces still exist:\n"
        "Driver/lvms/openshift-storage.rbd.csi.ceph.com" in result.stdout
    )


def test_audit_reports_a_failed_rook_lookup_and_does_not_excuse_the_groups(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_rook_objects(),
        groups=ROOK_GROUPS,
        namespaces=("rook-ceph",),
        errors={"cephclusters.ceph.rook.io": "Error from server (InternalError): etcd timeout"},
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: CephClusters query failed: Error from server (InternalError): etcd timeout" in result.stdout
    assert "retained for upstream Rook" not in result.stdout
    assert "WARN: ceph.rook.io API resources still exist:" in result.stdout


def test_audit_flags_rook_shared_groups_without_upstream_rook(tmp_path):
    # Without a running Rook cluster nothing excuses these groups or the namespace.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(tmp_path, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: rook-ceph namespace still exists" in result.stdout
    assert "WARN: ceph.rook.io API resources still exist:" in result.stdout
    assert "WARN: objectbucket.io API resources still exist:" in result.stdout
    assert "retained for upstream Rook" not in result.stdout


@pytest.mark.parametrize(
    ("scc", "retained"),
    [
        (
            {
                "metadata": meta("rook-ceph-mixed"),
                "users": [
                    "system:serviceaccount:rook-ceph:rook-ceph-system",
                    "system:serviceaccount:openshift-storage:rook-ceph-system",
                ],
            },
            False,
        ),
        ({"metadata": meta("rook-ceph-empty"), "users": []}, False),
        (
            {
                "metadata": meta("rook-ceph-grouped"),
                "users": ["system:serviceaccount:rook-ceph:rook-ceph-system"],
                "groups": ["system:serviceaccounts:rook-ceph"],
            },
            True,
        ),
        (
            {
                "metadata": meta("rook-ceph-wide"),
                "users": ["system:serviceaccount:rook-ceph:rook-ceph-system"],
                "groups": ["system:authenticated"],
            },
            False,
        ),
    ],
    ids=["users-elsewhere", "empty-users", "rook-groups", "foreign-group"],
)
def test_audit_retains_only_sccs_used_solely_by_upstream_rook(tmp_path, scc, retained):
    _write_jq_proxy(tmp_path)
    objects = _rook_objects()
    objects["scc"].append(scc)
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)
    name = scc["metadata"]["name"]

    assert "OK: SCC rook-ceph retained" in result.stdout
    if retained:
        _assert_clean(result)
        assert f"OK: SCC {name} retained" in result.stdout
    else:
        assert result.returncode == 1
        assert f"WARN: ODF SCCs still exist:\n{name}" in result.stdout
        assert f"SCC {name} retained" not in result.stdout


def test_audit_classifies_odf_cluster_rbac_by_liveness(tmp_path):
    _write_jq_proxy(tmp_path)
    objects = merge(
        _rook_objects(),
        {
            "clusterroles": [
                _cr("odf-prometheus", OCS_OWNER),
                # unlabelled name ODF creates
                _cr("ocs-metrics-reader"),
                _cr(
                    "csi-addons-csiaddons-networkfenceclass-viewer-role",
                    {
                        "olm.owner": "odf-csi-addons-operator.v4.20.17-rhodf",
                        "example.test/aggregate-to-view": "true",
                    },
                ),
                _cr("view", aggregation=[{"matchLabels": {"example.test/aggregate-to-view": "true"}}]),
                # an empty selector must not keep every role alive
                _cr("odf-operator-metrics-reader", {"olm.owner": "odf-operator.v4.20.17-rhodf"}),
                _cr("catch-all", aggregation=[{"matchLabels": {}}]),
                _cr("ocs-client-operator-metrics-reader", {"olm.owner": "ocs-client-operator.v4.20.17-rhodf"}),
                # not ODF's: never reported
                _cr("unrelated-role"),
            ],
            "clusterrolebindings": [
                # subject namespace does not exist
                _crb(
                    "odf-prometheus",
                    "odf-prometheus",
                    [_sa_subject("odf-storage", "prometheus-k8s")],
                    OCS_OWNER,
                ),
                # role gone, even though the subject lives
                _crb(
                    "ceph-csi-rbd-ctrlplugin-rb",
                    "ceph-csi-rbd-ctrlplugin-role",
                    [_sa_subject("openshift-monitoring", "prometheus-k8s")],
                    {"operators.coreos.com/cephcsi-operator.openshift-storage": ""},
                ),
                # role gone: a Group subject does not save it
                _crb(
                    "ocs-metrics-exporter-hostnetwork",
                    "ocs-metrics-exporter-hostnetwork",
                    [{"kind": "Group", "name": "system:authenticated"}],
                    OCS_OWNER,
                ),
                # unlabelled ODF name with a Group subject: cannot be proven dead
                _crb(
                    "ocs-metrics-exporter",
                    "unrelated-role",
                    [{"kind": "Group", "name": "system:authenticated"}],
                ),
                # a User subject cannot be proven absent either
                _crb(
                    "ocs-client-operator-metrics-reader",
                    "ocs-client-operator-metrics-reader",
                    [{"kind": "User", "name": "metrics-scraper"}],
                    {"olm.owner": "ocs-client-operator.v4.20.17-rhodf"},
                ),
            ],
        },
    )
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)
    out = result.stdout

    assert result.returncode == 1
    assert "WARN: dead ODF cluster RBAC still exists:" in out
    assert "ClusterRoleBinding/odf-prometheus: none of its ServiceAccount subjects exists" in out
    assert (
        "ClusterRoleBinding/ceph-csi-rbd-ctrlplugin-rb: its ClusterRole ceph-csi-rbd-ctrlplugin-role is missing"
        in out
    )
    assert (
        "ClusterRoleBinding/ocs-metrics-exporter-hostnetwork: its ClusterRole "
        "ocs-metrics-exporter-hostnetwork is missing" in out
    )
    assert "ClusterRole/odf-prometheus: referenced only by dead ClusterRoleBinding/odf-prometheus" in out
    assert "ClusterRole/ocs-metrics-reader: no binding references it" in out
    assert "ClusterRole/odf-operator-metrics-reader: no binding references it" in out
    assert (
        "OK: ClusterRoleBinding/rook-ceph-metrics retained: bound to live ServiceAccount "
        "openshift-monitoring/prometheus-k8s" in out
    )
    assert (
        "OK: ClusterRole/rook-ceph-metrics retained: referenced by live ClusterRoleBinding/rook-ceph-metrics"
        in out
    )
    assert "OK: ClusterRoleBinding/ocs-metrics-exporter retained: has a User/Group subject" in out
    assert "OK: ClusterRoleBinding/ocs-client-operator-metrics-reader retained: has a User/Group subject" in out
    assert (
        "OK: ClusterRole/ocs-client-operator-metrics-reader retained: referenced by live "
        "ClusterRoleBinding/ocs-client-operator-metrics-reader" in out
    )
    assert (
        "OK: ClusterRole/csi-addons-csiaddons-networkfenceclass-viewer-role retained: "
        "aggregated into another ClusterRole" in out
    )
    assert "ClusterRole/unrelated-role" not in out
    assert "ClusterRole/view" not in out
    assert "ClusterRole/catch-all" not in out


def test_audit_keeps_a_cluster_role_bound_by_a_live_role_binding(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "clusterroles": [_cr("rook-ceph-monitor", ROOK_OWNER)],
            "rolebindings": [
                {
                    "metadata": meta("rook-ceph-monitor", "rook-ceph"),
                    "roleRef": {"kind": "ClusterRole", "name": "rook-ceph-monitor"},
                    # namespace omitted: it defaults to the RoleBinding's own
                    "subjects": [{"kind": "ServiceAccount", "name": "rook-ceph-mgr"}],
                }
            ],
            "serviceaccounts": [_sa("rook-ceph", "rook-ceph-mgr")],
        },
    )

    result = _run_audit(tmp_path)

    _assert_clean(result)
    assert (
        "OK: ClusterRole/rook-ceph-monitor retained: referenced by live RoleBinding rook-ceph/rook-ceph-monitor"
        in result.stdout
    )


def _stuck_consumer_objects() -> dict:
    finalizer = ["objectbucket.io/finalizer"]
    return {
        "namespaces": [
            {"metadata": meta("consumer", deletionTimestamp=OLD), "status": {"phase": "Terminating"}},
            {"metadata": meta("busy"), "status": {"phase": "Active"}},
        ],
        "sc": [
            {
                "metadata": meta("ocs-storagecluster-ceph-rgw"),
                "provisioner": "openshift-storage.ceph.rook.io/bucket",
            }
        ],
        "obc": [
            {
                "metadata": meta("noobaa-claim", "consumer", deletionTimestamp=OLD, finalizers=finalizer),
                "spec": {"storageClassName": "openshift-storage.noobaa.io"},
            },
            {
                "metadata": meta("rgw-claim", "consumer", deletionTimestamp=OLD, finalizers=finalizer),
                "spec": {"storageClassName": "ocs-storagecluster-ceph-rgw"},
            },
        ],
        "objectbucket": [
            {
                "metadata": meta("obc-consumer-rgw-claim"),
                "spec": {"storageClassName": "ocs-storagecluster-ceph-rgw"},
            }
        ],
        "configmaps": [
            {"kind": "ConfigMap", "metadata": meta("noobaa-claim", "consumer", finalizers=finalizer)},
            {"kind": "ConfigMap", "metadata": meta("plain", "consumer")},
            # not Terminating and not openshift-storage: out of scope
            {"kind": "ConfigMap", "metadata": meta("held", "busy", finalizers=finalizer)},
        ],
        "secrets": [
            {"kind": "Secret", "metadata": meta("rgw-claim", "consumer", finalizers=finalizer)},
        ],
    }


def test_audit_flags_bucket_finalizer_residue_in_a_stuck_consumer_namespace(tmp_path):
    # Interrupted uninstall: the claims' StorageClasses and provisioners are gone, so
    # objectbucket.io/finalizer on the claims' ConfigMaps and Secrets is never
    # removed and the consumer namespace stays Terminating.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_jq_proxy(bin_dir)
    log = tmp_path / "argv.log"
    _write_cluster_oc(bin_dir, objects=_stuck_consumer_objects(), log=log)

    result = _run_audit(bin_dir)
    out = result.stdout

    assert result.returncode == 1
    assert (
        "WARN: namespaces Terminating for over 10 minutes (younger deletions ignored) still exist:\nconsumer"
        in out
    )
    assert "WARN: ODF ObjectBucketClaims still exist:" in out
    assert "consumer/noobaa-claim (class openshift-storage.noobaa.io: missing)" in out
    assert (
        "consumer/rgw-claim (class ocs-storagecluster-ceph-rgw: openshift-storage.ceph.rook.io/bucket)"
        in out
    )
    assert "WARN: ODF ObjectBuckets still exist:\nobc-consumer-rgw-claim" in out
    assert (
        "WARN: ConfigMaps and Secrets held by objectbucket.io/finalizer without a live claim still exist:"
        in out
    )
    assert "ConfigMap/consumer/noobaa-claim" in out
    assert "Secret/consumer/rgw-claim" in out
    assert "consumer/plain" not in out
    assert "busy/held" not in out

    # Secrets are read only in openshift-storage and Terminating namespaces, and
    # only as names and finalizers.
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    secret_calls = [c for c in calls if c[:2] == ["get", "secrets"]]
    assert secret_calls
    for call in secret_calls:
        assert "-A" not in call
        assert call[call.index("-n") + 1] in ("openshift-storage", "consumer")
        assert any(a.startswith("jsonpath=") for a in call)


def test_audit_explains_when_it_may_not_list_secrets(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_stuck_consumer_objects(),
        errors={
            "secrets": 'Error from server (Forbidden): secrets is forbidden: User "viewer" cannot list resource "secrets"'
        },
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert (
        "FAIL: could not check secrets in consumer for objectbucket.io/finalizer: listing secrets "
        "is forbidden for this user" in result.stdout
    )
    # what could be checked is still reported
    assert "ConfigMap/consumer/noobaa-claim" in result.stdout


def test_audit_flags_odf_volume_attachments_and_stuck_storage_pods(tmp_path):
    _write_jq_proxy(tmp_path)

    def attachment(name: str, attacher: str) -> dict:
        return {
            "metadata": meta(name),
            "spec": {"attacher": attacher, "source": {"persistentVolumeName": f"pv-{name}"}},
            "status": {"attached": True},
        }

    _write_cluster_oc(
        tmp_path,
        objects={
            "volumeattachment": [
                attachment("csi-odf", "openshift-storage.rbd.csi.ceph.com"),
                attachment("csi-rook", "rook-ceph.rbd.csi.ceph.com"),
                # the driver pattern is anchored at both ends
                attachment("csi-prefixed", "x-openshift-storage.rbd.csi.ceph.com"),
                attachment("csi-suffixed", "openshift-storage.rbd.csi.ceph.com.example"),
            ],
            "pods": [
                {
                    "metadata": meta("noobaa-db-pg-cluster-1", "openshift-storage", deletionTimestamp=OLD),
                    "status": {"phase": "Failed"},
                },
                {
                    "metadata": meta("vg-manager-abcde", "openshift-storage", deletionTimestamp=OLD),
                    "status": {"phase": "Running"},
                },
                {"metadata": meta("lvms-operator-12345", "openshift-storage"), "status": {"phase": "Running"}},
            ],
        },
    )

    result = _run_audit(tmp_path)
    out = result.stdout

    assert result.returncode == 1
    assert "WARN: ODF VolumeAttachments still exist:\ncsi-odf (pv pv-csi-odf, attached true)\n" in out
    for name in ("csi-rook", "csi-prefixed", "csi-suffixed"):
        assert name not in out
    assert "WARN: ODF pods in openshift-storage still exist:\nnoobaa-db-pg-cluster-1 (Failed)\n" in out
    assert (
        "WARN: pods in openshift-storage deleting for over 10 minutes (younger deletions ignored) still exist:"
        in out
    )
    assert "vg-manager-abcde (Running, deleting since" in out
    assert "lvms-operator-12345" not in out


def _kept_namespace_objects() -> dict:
    return {
        "subscription": [
            {"metadata": meta("lvms-operator", "openshift-storage"), "spec": {"name": "lvms-operator"}}
        ],
        "poddisruptionbudgets": [
            {"kind": "PodDisruptionBudget", "metadata": meta("rook-ceph-mon-pdb", "openshift-storage")}
        ],
        "roles": [{"kind": "Role", "metadata": meta("ocs-status-reporter", "openshift-storage")}],
        "rolebindings": [
            {
                "kind": "RoleBinding",
                "metadata": meta("odf-operator-controller-manager-metrics-service", "openshift-storage"),
                "roleRef": {"kind": "Role", "name": "odf-operator-controller-manager-metrics-service"},
            }
        ],
        "serviceaccounts": [
            {"kind": "ServiceAccount", "metadata": meta("ocs-status-reporter", "openshift-storage")},
            {"kind": "ServiceAccount", "metadata": meta("vg-manager", "openshift-storage")},
        ],
        "prometheusrules.monitoring.coreos.com": [
            {"kind": "PrometheusRule", "metadata": meta("ocs-prometheus-rules", "openshift-storage")}
        ],
    }


MONITORING_GROUP = {
    "monitoring.coreos.com": [
        ["servicemonitors.monitoring.coreos.com", True],
        ["prometheusrules.monitoring.coreos.com", True],
    ]
}


def test_audit_flags_rbac_pdb_and_monitoring_residue_in_a_kept_namespace(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_kept_namespace_objects(),
        groups=MONITORING_GROUP,
        namespaces=("openshift-storage",),
    )

    result = _run_audit(tmp_path)
    out = result.stdout

    assert result.returncode == 1
    assert "WARN: ODF residue objects in openshift-storage still exist:" in out
    for residue in (
        "PodDisruptionBudget/rook-ceph-mon-pdb",
        "Role/ocs-status-reporter",
        "RoleBinding/odf-operator-controller-manager-metrics-service",
        "ServiceAccount/ocs-status-reporter",
        "PrometheusRule/ocs-prometheus-rules",
    ):
        assert residue in out
    assert "vg-manager" not in out


def test_audit_skips_one_unknown_kind_without_hiding_the_others(tmp_path):
    # A comma-joined get fails outright when one kind is unknown, and that error
    # reads as "not found": every other kind's residue would vanish with it.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_kept_namespace_objects(),
        groups=MONITORING_GROUP,
        namespaces=("openshift-storage",),
        unserved=("servicemonitors.monitoring.coreos.com", "cronjobs"),
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF residue objects in openshift-storage still exist:" in result.stdout
    assert "PodDisruptionBudget/rook-ceph-mon-pdb" in result.stdout
    assert "PrometheusRule/ocs-prometheus-rules" in result.stdout
    assert "FAIL:" not in result.stdout


def test_audit_fails_when_one_kind_cannot_be_listed(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_kept_namespace_objects(),
        namespaces=("openshift-storage",),
        errors={"secrets": "Error from server (InternalError): an error on the server"},
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert (
        "FAIL: ODF residue objects in openshift-storage (secrets) query failed: "
        "Error from server (InternalError)" in result.stdout
    )
    # the kinds that could be read are still reported; "none found" is never claimed
    assert "PodDisruptionBudget/rook-ceph-mon-pdb" in result.stdout
    assert "OK: no ODF residue objects in openshift-storage" not in result.stdout


def test_audit_claims_no_residue_only_after_reading_every_kind(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={"subscription": _kept_namespace_objects()["subscription"]},
        namespaces=("openshift-storage",),
        errors={"secrets": "Error from server (InternalError): an error on the server"},
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: ODF residue objects in openshift-storage (secrets) query failed" in result.stdout
    assert "ODF residue objects in openshift-storage" not in result.stdout.replace(
        "FAIL: ODF residue objects in openshift-storage (secrets)", ""
    )


@pytest.mark.parametrize(
    ("group", "resource"),
    [
        ("replication.storage.openshift.io", "volumereplications.replication.storage.openshift.io"),
        ("ramendr.openshift.io", "recipes.ramendr.openshift.io"),
    ],
)
def test_audit_flags_leftover_odf_dr_crd_groups(tmp_path, group, resource):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(tmp_path, groups={group: [[resource, True]]})

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert f"WARN: {group} API resources still exist:\n{resource}" in result.stdout


GROUPSNAPSHOT = "groupsnapshot.storage.openshift.io"
GROUPSNAPSHOT_KIND = "volumegroupsnapshots.groupsnapshot.storage.openshift.io"


def _groupsnapshot_crd(labels=None, annotations=None) -> dict:
    return {
        "metadata": meta(GROUPSNAPSHOT_KIND, labels=labels or {}, annotations=annotations or {}),
        "spec": {"group": GROUPSNAPSHOT},
    }


ODF_SNAPSHOTTER_LABEL = {
    "operators.coreos.com/odf-external-snapshotter-operator.openshift-storage": ""
}


@pytest.mark.parametrize(
    ("crd", "instances", "featuregate", "verdict"),
    [
        (_groupsnapshot_crd(ODF_SNAPSHOTTER_LABEL), [], {}, None),
        (
            _groupsnapshot_crd(ODF_SNAPSHOTTER_LABEL),
            [{"metadata": meta("snap", "app")}],
            {},
            "1 instances exist",
        ),
        (
            _groupsnapshot_crd(
                ODF_SNAPSHOTTER_LABEL,
                {"include.release.openshift.io/self-managed-high-availability": "true"},
            ),
            [],
            {},
            "its CRDs are not all ODF-labelled, or carry release-payload annotations",
        ),
        (
            _groupsnapshot_crd(),
            [],
            {},
            "its CRDs are not all ODF-labelled, or carry release-payload annotations",
        ),
        (
            _groupsnapshot_crd(ODF_SNAPSHOTTER_LABEL),
            [],
            {"status": {"featureGates": [{"enabled": [{"name": "VolumeGroupSnapshot"}]}]}},
            "the VolumeGroupSnapshot feature gate is enabled",
        ),
    ],
    ids=["odf-unused", "in-use", "release-payload", "unlabelled", "feature-gate"],
)
def test_audit_reports_groupsnapshot_crds_as_residue_only_when_provably_odf_and_unused(
    tmp_path, crd, instances, featuregate, verdict
):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={"crd": [crd], GROUPSNAPSHOT_KIND: instances},
        groups={GROUPSNAPSHOT: [[GROUPSNAPSHOT_KIND, True]]},
        featuregate=featuregate,
    )

    result = _run_audit(tmp_path)

    if verdict is None:
        assert result.returncode == 1
        assert f"WARN: {GROUPSNAPSHOT} API resources are ODF residue" in result.stdout
    else:
        _assert_clean(result)
        assert f"OK: {GROUPSNAPSHOT} API resources retained: {verdict}" in result.stdout


def test_audit_reads_json_despite_stderr_noise_on_success(tmp_path):
    # A throttling line on stderr used to be merged into the JSON and reported as
    # "jq filter failed"; residue must still be found.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={"csidriver": [{"metadata": meta("openshift-storage.rbd.csi.ceph.com")}]},
        noise=True,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF CSIDrivers still exist:\nopenshift-storage.rbd.csi.ceph.com" in result.stdout
    assert "FAIL:" not in result.stdout


def test_audit_keeps_finalizers_of_a_live_rook_claim_in_a_terminating_namespace(tmp_path):
    # The running Rook bucket provisioner puts objectbucket.io/finalizer on its own
    # claims' ConfigMaps and Secrets; a namespace being deleted is not a reason to
    # call them ODF residue.
    _write_jq_proxy(tmp_path)
    objects = _rook_objects()
    objects["namespaces"] = [
        {"metadata": meta("app", deletionTimestamp=recent()), "status": {"phase": "Terminating"}}
    ]
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    _assert_clean(result)
    assert "OK: no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim" in result.stdout


def test_audit_does_not_call_an_unserved_shared_group_retained(tmp_path):
    _write_jq_proxy(tmp_path)
    groups = dict(ROOK_GROUPS)
    del groups["csi.ceph.io"]
    _write_cluster_oc(tmp_path, objects=_rook_objects(), groups=groups, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    _assert_clean(result)
    assert "OK: no csi.ceph.io API resources found" in result.stdout
    assert "csi.ceph.io API resources retained" not in result.stdout


def test_audit_flags_only_storage_classes_with_odf_provisioners(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "sc": [
                {"metadata": meta("ocs-storagecluster-ceph-rbd"), "provisioner": "openshift-storage.rbd.csi.ceph.com"},
                {"metadata": meta("openshift-storage.noobaa.io"), "provisioner": "openshift-storage.noobaa.io/obc"},
                {"metadata": meta("rook-ceph-block"), "provisioner": "rook-ceph.rbd.csi.ceph.com"},
            ]
        },
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert (
        "WARN: ODF StorageClasses still exist:\nocs-storagecluster-ceph-rbd\nopenshift-storage.noobaa.io\n"
        in result.stdout
    )
    assert "rook-ceph-block" not in result.stdout


def test_audit_flags_stale_odf_console_plugin_names(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(tmp_path, console_plugins=("monitoring-plugin", "odf-console"))

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: stale ODF names still in console.operator spec.plugins:\nodf-console\n" in result.stdout
    assert "monitoring-plugin" not in result.stdout


@pytest.mark.parametrize(
    ("extra", "named"),
    [
        (
            {"drivers.csi.ceph.io": [{"kind": "Driver", "metadata": meta("rook-ceph.rbd.csi.ceph.com", "rook-ceph")}]},
            "csi.ceph.io Driver rook-ceph/rook-ceph.rbd.csi.ceph.com (non-ODF Ceph CSI without a Rook operator",
        ),
        (
            {"csidrivers": [{"metadata": meta("rook-ceph.rbd.csi.ceph.com")}]},
            "CSIDriver rook-ceph.rbd.csi.ceph.com (non-ODF Ceph CSI driver without a Rook operator",
        ),
        (
            {"pv": [{"metadata": meta("pvc-2"), "spec": {"csi": {"driver": "rook-ceph.cephfs.csi.ceph.com"}}}]},
            "PV pvc-2 (volume of non-ODF Ceph CSI driver rook-ceph.cephfs.csi.ceph.com",
        ),
    ],
    ids=["csi-driver-object", "csidriver", "pv"],
)
def test_audit_reports_a_ceph_csi_that_outlived_its_operator_as_unknown(tmp_path, extra, named):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(tmp_path, objects=extra, groups=ROOK_GROUPS)

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: Rook objects whose owner cannot be classified still exist:" in result.stdout
    assert named in result.stdout
    assert "retained for upstream Rook" not in result.stdout
