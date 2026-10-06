from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_uninstall_audit.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_jq_proxy(bin_dir: Path) -> None:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required for post_uninstall_audit.sh tests")
    _write_executable(
        bin_dir / "jq",
        f"""\
        #!/bin/sh
        exec {jq} "$@"
        """,
    )


def _write_oc(bin_dir: Path, body: str) -> None:
    _write_executable(
        bin_dir / "oc",
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json",
                "import sys",
                "",
                textwrap.dedent(body).strip(),
                "",
            ]
        ),
    )


def _run_audit(
    bin_dir: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir)},
    )


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
        if args[0] == "get" and args[1].startswith("secrets") and "-o" in args:
            assert "statefulsets" in args[1], "residue sweep must query statefulsets"
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


# The tests below share one fake cluster: a dict of objects per resource name, the
# API groups it serves, and the namespaces that exist. A resource listed in
# "unserved" fails the way oc does for an unknown type, which also fails every
# comma-joined `oc get` that names it.
_CLUSTER_OC = """\
WORLD = json.loads(__WORLD__)
args = sys.argv[1:]
if args == ["whoami"]:
    print("admin")
    raise SystemExit(0)
if args[:1] == ["api-resources"]:
    group = next((a.split("=", 1)[1] for a in args if a.startswith("--api-group=")), "")
    for name, namespaced in WORLD["groups"].get(group, []):
        if "--namespaced=true" in args and not namespaced:
            continue
        print(name)
    raise SystemExit(0)
if args[:2] == ["get", "namespace"]:
    if args[2] in WORLD["namespaces"]:
        print(args[2])
        raise SystemExit(0)
    print("NotFound", file=sys.stderr)
    raise SystemExit(1)
if args[:1] == ["get"] and "-o" in args:
    if args[1:3] == ["console.operator.openshift.io", "cluster"]:
        print(json.dumps({"spec": {}}))
        raise SystemExit(0)
    if args[1:3] == ["featuregate", "cluster"]:
        print(json.dumps(WORLD["featuregate"]))
        raise SystemExit(0)
    for res in args[1].split(","):
        if res in WORLD["unserved"]:
            print('error: the server doesn\\'t have a resource type "%s"' % res, file=sys.stderr)
            raise SystemExit(1)
    ns = args[args.index("-n") + 1] if "-n" in args else None
    items = []
    for res in args[1].split(","):
        for item in WORLD["objects"].get(res, []):
            if ns is None or item["metadata"].get("namespace") == ns:
                items.append(item)
    print(json.dumps({"items": items}))
    raise SystemExit(0)
raise SystemExit(0)
"""

_DEFAULT_SC = {
    "metadata": {
        "name": "platform-default",
        "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
    },
    "provisioner": "topolvm.io",
}


def _write_cluster_oc(
    bin_dir: Path,
    objects: dict | None = None,
    groups: dict | None = None,
    namespaces: tuple = (),
    unserved: tuple = (),
    featuregate: dict | None = None,
) -> None:
    world_objects = {"sc": [_DEFAULT_SC]}
    for res, items in (objects or {}).items():
        world_objects[res] = world_objects.get(res, []) + items
    world = {
        "objects": world_objects,
        "groups": groups or {},
        "namespaces": list(namespaces),
        "unserved": list(unserved),
        "featuregate": featuregate or {},
    }
    _write_oc(bin_dir, _CLUSTER_OC.replace("__WORLD__", repr(json.dumps(world))))


def _meta(name: str, namespace: str | None = None, **extra) -> dict:
    meta = {"name": name, **extra}
    if namespace is not None:
        meta["namespace"] = namespace
    return meta


def _sa(namespace: str, name: str) -> dict:
    return {"metadata": _meta(name, namespace)}


def _sa_subject(namespace: str, name: str) -> dict:
    return {"kind": "ServiceAccount", "namespace": namespace, "name": name}


def _crb(name: str, role: str, subjects: list, labels: dict | None = None) -> dict:
    return {
        "metadata": _meta(name, labels=labels or {}),
        "roleRef": {"kind": "ClusterRole", "name": role},
        "subjects": subjects,
    }


def _cr(name: str, labels: dict | None = None, aggregation: list | None = None) -> dict:
    role = {"metadata": _meta(name, labels=labels or {})}
    if aggregation is not None:
        role["aggregationRule"] = {"clusterRoleSelectors": aggregation}
    return role


ROOK_OWNER = {"olm.owner": "rook-ceph-operator.v4.20.17-rhodf"}
OCS_OWNER = {"olm.owner": "ocs-operator.v4.20.17-rhodf"}

# Cluster shape after an ODF uninstall next to an upstream (non-OLM) Rook cluster in
# rook-ceph: the shared Rook groups, its SCCs, a claim it serves, and RBAC that still
# carries ODF's OLM label while the running Rook uses it.
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
        "cephclusters.ceph.rook.io": [{"metadata": _meta("rook-ceph", "rook-ceph")}],
        "drivers.csi.ceph.io": [
            {"kind": "Driver", "metadata": _meta("rook-ceph.rbd.csi.ceph.com", "rook-ceph")}
        ],
        "scc": [
            {
                "metadata": _meta("rook-ceph"),
                "users": ["system:serviceaccount:rook-ceph:rook-ceph-system"],
            },
            {
                "metadata": _meta("rook-ceph-csi"),
                "users": ["system:serviceaccount:rook-ceph:rook-csi-rbd-plugin-sa"],
            },
        ],
        "sc": [{"metadata": _meta("rook-ceph-bucket"), "provisioner": "rook-ceph.ceph.rook.io/bucket"}],
        "obc": [
            {"metadata": _meta("rook-bucket", "app"), "spec": {"storageClassName": "rook-ceph-bucket"}}
        ],
        "objectbucket": [
            {"metadata": _meta("obc-app-rook-bucket"), "spec": {"storageClassName": "rook-ceph-bucket"}}
        ],
        "configmaps": [
            {
                "kind": "ConfigMap",
                "metadata": _meta("rook-bucket", "app", finalizers=["objectbucket.io/finalizer"]),
            }
        ],
        "secrets": [
            {
                "kind": "Secret",
                "metadata": _meta("rook-bucket", "app", finalizers=["objectbucket.io/finalizer"]),
            }
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


def _merge(*parts: dict) -> dict:
    merged: dict = {}
    for part in parts:
        for res, items in part.items():
            merged[res] = merged.get(res, []) + items
    return merged


def test_audit_reports_deleting_pvc_and_pv_by_deletion_timestamp(tmp_path):
    # A deleting PVC or PV keeps phase Bound/Released; "Terminating" is not a phase.
    # The old `.status.phase == "Terminating"` test could never fire.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "pvc": [
                {
                    "metadata": _meta(
                        "db-noobaa-db-pg-cluster-1",
                        "openshift-storage",
                        deletionTimestamp="2026-08-20T10:00:00Z",
                        finalizers=["kubernetes.io/pvc-protection"],
                    ),
                    "status": {"phase": "Bound"},
                }
            ],
            "pv": [
                {
                    "metadata": _meta(
                        "pvc-released",
                        deletionTimestamp="2026-08-20T10:00:00Z",
                        finalizers=["kubernetes.io/pv-protection"],
                    ),
                    "status": {"phase": "Released"},
                }
            ],
        },
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: Terminating PVCs still exist:" in result.stdout
    assert (
        "openshift-storage/db-noobaa-db-pg-cluster-1 (phase Bound, finalizers: kubernetes.io/pvc-protection)"
        in result.stdout
    )
    assert "WARN: Terminating PVs still exist:" in result.stdout
    assert "pvc-released (phase Released" in result.stdout


def test_audit_passes_on_a_clean_cluster_with_every_new_check(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "pvc": [{"metadata": _meta("data", "app"), "status": {"phase": "Bound"}}],
            "namespaces": [{"metadata": _meta("app"), "status": {"phase": "Active"}}],
            "volumeattachment": [
                {"metadata": _meta("csi-other"), "spec": {"attacher": "topolvm.io"}}
            ],
            "clusterroles": [_cr("admin")],
        },
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 0, result.stdout
    for line in (
        "OK: no Terminating PVCs found",
        "OK: no Terminating PVs found",
        "OK: no Terminating namespaces found",
        "OK: no ODF VolumeAttachments found",
        "OK: no ODF pods in openshift-storage",
        "OK: no Terminating pods in openshift-storage",
        "OK: no ODF ObjectBuckets found",
        "OK: no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim",
        "OK: no replication.storage.openshift.io API resources found",
        "OK: no ramendr.openshift.io API resources found",
        "OK: no groupsnapshot.storage.openshift.io API resources found",
        "OK: no ODF CephClusters found",
        "OK: no dead ODF ClusterRoles or ClusterRoleBindings found",
    ):
        assert line in result.stdout
    assert "WARN:" not in result.stdout
    assert "FAIL:" not in result.stdout


def test_audit_tolerates_absent_new_kinds(tmp_path):
    # VolumeAttachments, CephClusters, OBCs and the RBAC/ServiceAccount lists
    # reported as unknown types must read as "none", not as a failed audit.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        unserved=(
            "volumeattachment",
            "cephclusters.ceph.rook.io",
            "obc",
            "objectbucket",
            "namespaces",
            "pods",
            "clusterroles",
        ),
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "OK: no ODF VolumeAttachments found" in result.stdout
    assert "OK: no ODF CephClusters found" in result.stdout
    assert "OK: no ODF ObjectBucketClaims found" in result.stdout
    assert "OK: no dead ODF ClusterRoles or ClusterRoleBindings found" in result.stdout


def test_audit_treats_a_running_upstream_rook_cluster_as_retained(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_rook_objects(),
        groups=ROOK_GROUPS,
        namespaces=("rook-ceph",),
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 0, result.stdout
    for line in (
        "OK: namespace rook-ceph retained: an upstream Rook CephCluster runs there",
        "OK: ceph.rook.io API resources retained for upstream Rook in: rook-ceph",
        "OK: csi.ceph.io API resources retained for upstream Rook in: rook-ceph",
        "OK: objectbucket.io API resources retained for upstream Rook in: rook-ceph",
        "OK: no ceph.rook.io objects in openshift-storage",
        "OK: no csi.ceph.io objects in openshift-storage",
        "OK: SCC rook-ceph retained: every user is a service account in an upstream Rook namespace",
        "OK: SCC rook-ceph-csi retained: every user is a service account in an upstream Rook namespace",
        "OK: no ODF SCCs found",
        "OK: no ODF ObjectBucketClaims found",
        "OK: no ODF ObjectBuckets found",
        "OK: no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim",
        "OK: no ODF CephClusters found",
    ):
        assert line in result.stdout
    assert "WARN:" not in result.stdout
    assert "FAIL:" not in result.stdout


@pytest.mark.parametrize(
    ("namespace", "owners"),
    [
        # orphaned by an interrupted uninstall: no StorageCluster left to own it
        ("openshift-storage", []),
        ("ocs-elsewhere", [{"kind": "StorageCluster", "name": "ocs-storagecluster"}]),
    ],
)
def test_audit_still_flags_an_odf_ceph_cluster_next_to_upstream_rook(tmp_path, namespace, owners):
    _write_jq_proxy(tmp_path)
    odf_cluster = {
        "kind": "CephCluster",
        "metadata": _meta("ocs-storagecluster-cephcluster", namespace, ownerReferences=owners),
    }
    _write_cluster_oc(
        tmp_path,
        objects=_merge(_rook_objects(), {"cephclusters.ceph.rook.io": [odf_cluster]}),
        groups=ROOK_GROUPS,
        namespaces=("rook-ceph",),
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF CephClusters still exist:" in result.stdout
    assert f"{namespace}/ocs-storagecluster-cephcluster" in result.stdout
    # the ODF cluster's namespace must not be mistaken for an upstream Rook one
    assert f"namespace {namespace} retained" not in result.stdout
    assert "OK: ceph.rook.io API resources retained for upstream Rook in: rook-ceph\n" in result.stdout
    if namespace == "openshift-storage":
        assert "WARN: ceph.rook.io objects in openshift-storage still exist:" in result.stdout


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


def test_audit_flags_an_scc_with_users_outside_the_rook_namespace(tmp_path):
    _write_jq_proxy(tmp_path)
    objects = _rook_objects()
    objects["scc"].append(
        {
            "metadata": _meta("rook-ceph-mixed"),
            "users": [
                "system:serviceaccount:rook-ceph:rook-ceph-system",
                "system:serviceaccount:openshift-storage:rook-ceph-system",
            ],
        }
    )
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF SCCs still exist:\nrook-ceph-mixed" in result.stdout
    assert "SCC rook-ceph-mixed retained" not in result.stdout
    assert "OK: SCC rook-ceph retained" in result.stdout


def test_audit_classifies_odf_cluster_rbac_by_liveness(tmp_path):
    _write_jq_proxy(tmp_path)
    objects = _merge(
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
                # unlabelled ODF name with a Group subject: cannot be proven dead
                _crb(
                    "ocs-metrics-exporter",
                    "unrelated-role",
                    [{"kind": "Group", "name": "system:authenticated"}],
                ),
            ],
        },
    )
    _write_cluster_oc(tmp_path, objects=objects, groups=ROOK_GROUPS, namespaces=("rook-ceph",))

    result = _run_audit(tmp_path)
    out = result.stdout

    assert result.returncode == 1
    assert "WARN: dead ODF cluster RBAC still exists:" in out
    assert (
        "ClusterRoleBinding/odf-prometheus: none of its ServiceAccount subjects exists" in out
    )
    assert (
        "ClusterRoleBinding/ceph-csi-rbd-ctrlplugin-rb: its ClusterRole ceph-csi-rbd-ctrlplugin-role is missing"
        in out
    )
    assert (
        "ClusterRole/odf-prometheus: referenced only by dead ClusterRoleBinding/odf-prometheus" in out
    )
    assert "ClusterRole/ocs-metrics-reader: no binding references it" in out
    assert (
        "OK: ClusterRoleBinding/rook-ceph-metrics retained: bound to live ServiceAccount "
        "openshift-monitoring/prometheus-k8s" in out
    )
    assert (
        "OK: ClusterRole/rook-ceph-metrics retained: referenced by live ClusterRoleBinding/rook-ceph-metrics"
        in out
    )
    assert (
        "OK: ClusterRoleBinding/ocs-metrics-exporter retained: has a User/Group subject" in out
    )
    assert (
        "OK: ClusterRole/csi-addons-csiaddons-networkfenceclass-viewer-role retained: "
        "aggregated into another ClusterRole" in out
    )
    assert "ClusterRole/unrelated-role" not in out
    assert "ClusterRole/view" not in out


def test_audit_keeps_a_cluster_role_bound_by_a_live_role_binding(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "clusterroles": [_cr("rook-ceph-monitor", ROOK_OWNER)],
            "rolebindings": [
                {
                    "metadata": _meta("rook-ceph-monitor", "rook-ceph"),
                    "roleRef": {"kind": "ClusterRole", "name": "rook-ceph-monitor"},
                    # namespace omitted: it defaults to the RoleBinding's own
                    "subjects": [{"kind": "ServiceAccount", "name": "rook-ceph-mgr"}],
                }
            ],
            "serviceaccounts": [_sa("rook-ceph", "rook-ceph-mgr")],
        },
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 0, result.stdout
    assert (
        "OK: ClusterRole/rook-ceph-monitor retained: referenced by live RoleBinding rook-ceph/rook-ceph-monitor"
        in result.stdout
    )


def test_audit_flags_bucket_finalizer_residue_in_a_stuck_consumer_namespace(tmp_path):
    # Interrupted uninstall: the claims' StorageClasses and provisioners are gone, so
    # objectbucket.io/finalizer on the claims' ConfigMaps and Secrets is never
    # removed and the consumer namespace stays Terminating.
    _write_jq_proxy(tmp_path)
    finalizer = ["objectbucket.io/finalizer"]
    deleting = "2026-08-20T10:00:00Z"
    _write_cluster_oc(
        tmp_path,
        objects={
            "namespaces": [{"metadata": _meta("consumer"), "status": {"phase": "Terminating"}}],
            "sc": [{"metadata": _meta("ocs-storagecluster-ceph-rgw"), "provisioner": "openshift-storage.ceph.rook.io/bucket"}],
            "obc": [
                {
                    "metadata": _meta("noobaa-claim", "consumer", deletionTimestamp=deleting, finalizers=finalizer),
                    "spec": {"storageClassName": "openshift-storage.noobaa.io"},
                },
                {
                    "metadata": _meta("rgw-claim", "consumer", deletionTimestamp=deleting, finalizers=finalizer),
                    "spec": {"storageClassName": "ocs-storagecluster-ceph-rgw"},
                },
            ],
            "objectbucket": [
                {"metadata": _meta("obc-consumer-rgw-claim"), "spec": {"storageClassName": "ocs-storagecluster-ceph-rgw"}}
            ],
            "configmaps": [
                {"kind": "ConfigMap", "metadata": _meta("noobaa-claim", "consumer", finalizers=finalizer)},
                {"kind": "ConfigMap", "metadata": _meta("plain", "consumer")},
            ],
            "secrets": [
                {"kind": "Secret", "metadata": _meta("rgw-claim", "consumer", finalizers=finalizer)},
            ],
        },
    )

    result = _run_audit(tmp_path)
    out = result.stdout

    assert result.returncode == 1
    assert "WARN: Terminating namespaces still exist:\nconsumer" in out
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


def test_audit_flags_odf_volume_attachments_and_stuck_storage_pods(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects={
            "volumeattachment": [
                {
                    "metadata": _meta("csi-odf"),
                    "spec": {
                        "attacher": "openshift-storage.rbd.csi.ceph.com",
                        "source": {"persistentVolumeName": "pvc-odf"},
                    },
                    "status": {"attached": True},
                },
                {
                    "metadata": _meta("csi-rook"),
                    "spec": {
                        "attacher": "rook-ceph.rbd.csi.ceph.com",
                        "source": {"persistentVolumeName": "pvc-rook"},
                    },
                    "status": {"attached": True},
                },
            ],
            "pods": [
                {
                    "metadata": _meta(
                        "noobaa-db-pg-cluster-1",
                        "openshift-storage",
                        deletionTimestamp="2026-08-20T10:00:00Z",
                    ),
                    "status": {"phase": "Failed"},
                },
                {
                    "metadata": _meta("vg-manager-abcde", "openshift-storage", deletionTimestamp="2026-08-20T10:00:00Z"),
                    "status": {"phase": "Running"},
                },
                {"metadata": _meta("lvms-operator-12345", "openshift-storage"), "status": {"phase": "Running"}},
            ],
        },
    )

    result = _run_audit(tmp_path)
    out = result.stdout

    assert result.returncode == 1
    assert "WARN: ODF VolumeAttachments still exist:\ncsi-odf (pv pvc-odf, attached true)" in out
    assert "csi-rook" not in out
    assert "WARN: ODF pods in openshift-storage still exist:\nnoobaa-db-pg-cluster-1 (Failed)\n" in out
    assert "WARN: Terminating pods in openshift-storage still exist:" in out
    assert "vg-manager-abcde (Running, deleting since" in out
    assert "lvms-operator-12345" not in out


def _kept_namespace_objects() -> dict:
    return {
        "subscription": [
            {"metadata": _meta("lvms-operator", "openshift-storage"), "spec": {"name": "lvms-operator"}}
        ],
        "poddisruptionbudgets": [
            {"kind": "PodDisruptionBudget", "metadata": _meta("rook-ceph-mon-pdb", "openshift-storage")}
        ],
        "roles": [{"kind": "Role", "metadata": _meta("ocs-status-reporter", "openshift-storage")}],
        "rolebindings": [
            {
                "kind": "RoleBinding",
                "metadata": _meta("odf-operator-controller-manager-metrics-service", "openshift-storage"),
                "roleRef": {"kind": "Role", "name": "odf-operator-controller-manager-metrics-service"},
            }
        ],
        "serviceaccounts": [
            {"kind": "ServiceAccount", "metadata": _meta("ocs-status-reporter", "openshift-storage")},
            {"kind": "ServiceAccount", "metadata": _meta("vg-manager", "openshift-storage")},
        ],
        "prometheusrules.monitoring.coreos.com": [
            {"kind": "PrometheusRule", "metadata": _meta("ocs-prometheus-rules", "openshift-storage")}
        ],
    }


def test_audit_flags_rbac_pdb_and_monitoring_residue_in_a_kept_namespace(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_kept_namespace_objects(),
        groups={
            "monitoring.coreos.com": [
                ["servicemonitors.monitoring.coreos.com", True],
                ["prometheusrules.monitoring.coreos.com", True],
            ]
        },
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


def test_audit_omits_monitoring_kinds_the_api_does_not_serve(tmp_path):
    # oc fails a whole comma-joined get on one unknown type, and that error reads as
    # NotFound, so naming an absent CRD would turn real residue into a false OK.
    _write_jq_proxy(tmp_path)
    _write_cluster_oc(
        tmp_path,
        objects=_kept_namespace_objects(),
        namespaces=("openshift-storage",),
        unserved=(
            "servicemonitors.monitoring.coreos.com",
            "prometheusrules.monitoring.coreos.com",
        ),
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "WARN: ODF residue objects in openshift-storage still exist:" in result.stdout
    assert "PodDisruptionBudget/rook-ceph-mon-pdb" in result.stdout
    assert "PrometheusRule/ocs-prometheus-rules" not in result.stdout


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
        "metadata": _meta(GROUPSNAPSHOT_KIND, labels=labels or {}, annotations=annotations or {}),
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
            [{"metadata": _meta("snap", "app")}],
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
        assert result.returncode == 0, result.stdout
        assert f"OK: {GROUPSNAPSHOT} API resources retained: {verdict}" in result.stdout
