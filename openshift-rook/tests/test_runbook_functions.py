"""Run the shell functions of references/maintenance-uninstall.md against the fake oc.

The functions, and the setup lines the reader pastes before them, are taken
verbatim from the runbook, so a change there is what the tests run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rook_cluster_fake import (  # noqa: E402
    OLD,
    SCRIPTS,
    SHOW_SERVER,
    ceph_cluster,
    merge,
    meta,
    node_calls,
    rook_operator,
    write_cluster_oc,
    write_executable,
    write_jq_proxy,
)

RUNBOOK = Path(__file__).resolve().parents[1] / "references" / "maintenance-uninstall.md"
RUNBOOK_TEXT = RUNBOOK.read_text(encoding="utf-8")
FUNCTIONS = dict(
    (m.group(1), m.group(0))
    for m in re.finditer(r"^(rook_[a-z_]+)\(\) \{\n.*?^\}$", RUNBOOK_TEXT, re.M | re.S)
)
# The setup lines of the ownership gate block, up to its first function.
PRELUDE = re.search(
    r"### Ownership gate\n.*?```bash\n(.*?)^rook_[a-z_]+\(\) \{", RUNBOOK_TEXT, re.M | re.S
).group(1)

GROUPS = {
    "ceph.rook.io": [
        ["cephclusters.ceph.rook.io", True],
        ["cephblockpools.ceph.rook.io", True],
        ["cephfilesystems.ceph.rook.io", True],
        ["cephobjectstores.ceph.rook.io", True],
        ["cephnfses.ceph.rook.io", True],
    ],
    "csi.ceph.io": [["drivers.csi.ceph.io", True], ["clientprofiles.csi.ceph.io", True]],
    "objectbucket.io": [
        ["objectbucketclaims.objectbucket.io", True],
        ["objectbuckets.objectbucket.io", False],
    ],
    "snapshot.storage.k8s.io": [["volumesnapshotclasses.snapshot.storage.k8s.io", False]],
    # not one of Rook's groups; its CRD must survive
    "replication.storage.openshift.io": [["volumereplications.replication.storage.openshift.io", True]],
}
SHARED = ("ceph.rook.io", "csi.ceph.io", "objectbucket.io")
# Groups whose names end like Rook's: an "endswith" match would take their CRDs.
DECOY_CRDS = [
    {"metadata": meta("things.x.ceph.rook.io"), "spec": {"group": "x.ceph.rook.io"}},
    {"metadata": meta("things.foo.csi.ceph.io"), "spec": {"group": "foo.csi.ceph.io"}},
    {"metadata": meta("things.noobaa.objectbucket.io"), "spec": {"group": "noobaa.objectbucket.io"}},
]
CRDS = [
    {"metadata": meta(kind), "spec": {"group": group}}
    for group, kinds in GROUPS.items()
    if group in SHARED or group == "replication.storage.openshift.io"
    for kind, _ in kinds
] + DECOY_CRDS
ROOK = {"deployments": [rook_operator()], "cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")]}
OPERATOR = {"deployments": [rook_operator()]}
ODF = {
    "subscriptions.operators.coreos.com": [
        {"metadata": meta("odf-operator", "openshift-storage"), "spec": {"name": "odf-operator"}}
    ]
}
UNKNOWN_ERRORS = {"deployments": "Error from server (Forbidden): cannot list deployments"}
STALE_ENV = {"ROOK_OWNERSHIP_CLASSIFIED": "yes", "ROOK_NAMESPACES": ""}
DESTRUCTIVE = ("delete", "patch", "debug", "uninstall")
ROOK_CHART = "---\nkind: Deployment\nmetadata:\n  name: rook-ceph-operator\n"
KEPT_CRD = ("---\nkind: CustomResourceDefinition\nmetadata:\n  name: cephclusters.ceph.rook.io\n"
            "  annotations:\n    helm.sh/resource-policy: keep\n")
OWNED_CRD = "---\nkind: CustomResourceDefinition\nmetadata:\n  name: cephblockpools.ceph.rook.io\n"
RELEASES = {"rook-ceph/rook-ceph": ROOK_CHART}


def test_runbook_defines_the_tested_functions():
    assert {
        "rook_need_namespace",
        "rook_classify",
        "rook_only",
        "rook_gone",
        "rook_helm_uninstall",
        "rook_record_data_dir",
        "rook_wait_gone",
        "rook_delete_ceph_crs",
        "rook_delete_operator",
        "rook_clear_finalizers",
        "rook_list_cluster_scoped",
        "rook_wipe_data_dir",
        "rook_delete_crds",
        "rook_set_cleanup_policy",
        "rook_wipe_osd_disk",
        "rook_remove_sccs",
    } <= set(FUNCTIONS)
    assert ". scripts/rook_common.sh" in PRELUDE
    assert "ROOK_NAMESPACE=rook-ceph" in PRELUDE


def _write_helm(bin_dir: Path, log: Path, releases: dict) -> None:
    write_executable(
        bin_dir / "helm",
        f"""\
        #!{sys.executable}
        import json
        import sys
        args = sys.argv[1:]
        with open({str(log)!r}, "a") as fh:
            fh.write(json.dumps(["helm"] + args) + chr(10))
        releases = json.loads({json.dumps(releases)!r})
        ns = args[args.index("-n") + 1] if "-n" in args else "default"
        name = args[2] if args[:2] == ["get", "manifest"] else args[1]
        if ns + "/" + name not in releases:
            print("Error: release: not found", file=sys.stderr)
            raise SystemExit(1)
        if args[:2] == ["get", "manifest"]:
            sys.stdout.write(releases[ns + "/" + name])
        raise SystemExit(0)
        """,
    )


def _run(tmp_path: Path, call: str, objects=None, errors=None, env=None, omit=(), blocking=False, groups=None,
         releases=None, debug="", node=None):
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    for name in ("classify_ceph_ownership.sh", "rook_common.sh"):
        shutil.copy(SCRIPTS / name, skill / "scripts" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_jq_proxy(bin_dir)
    found = shutil.which("bash")
    if found is None:
        pytest.skip("bash is required for the runbook function tests")
    (bin_dir / "bash").symlink_to(found)
    log = tmp_path / "argv.log"
    world = {"objects": {"crd": CRDS, **(objects or {})}, "groups": groups or GROUPS, "errors": errors or {}}
    write_cluster_oc(bin_dir, log=log, blocking_deletes=blocking, debug=debug, node=node, **world)
    _write_helm(bin_dir, log, RELEASES if releases is None else releases)
    script = "\n".join(
        [
            PRELUDE,
            *(body for name, body in FUNCTIONS.items() if name not in omit),
            call,
            'echo "rc=$?"',
        ]
    )
    result = subprocess.run(
        [str(bin_dir / "bash"), "-c", script],
        cwd=skill,
        env={"PATH": str(bin_dir), "ROOK_DELETE_TIMEOUT": "0", **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    mutations = [" ".join(c) for c in calls if any(verb in c for verb in DESTRUCTIVE)]
    return result, mutations


# --- every classified function refuses without the verdict it needs ------------------

WIPE_ENV = {"ROOK_DATA_DIR": "/var/lib/rook", "ROOK_DATA_DIR_SERVER": SHOW_SERVER, "ROOK_DATA_DIR_NAMESPACE": "rook-ceph"}
DISK = "/dev/disk/by-id/wwn-0x5000c500a1b2c3d4"
CLASSIFIED = (
    "rook_delete_ceph_crs",
    "rook_delete_operator",
    "rook_delete_crds",
    "rook_remove_sccs",
    "rook_helm_uninstall",
    "ROOK_CONFIRM_DESTROY_DATA=yes-really-destroy-data rook_set_cleanup_policy",
    f"ROOK_CONFIRM_WIPE_DISK={DISK} rook_wipe_osd_disk node-a {DISK}",
    "rook_wipe_data_dir node-a",
)


@pytest.mark.parametrize("call", CLASSIFIED)
@pytest.mark.parametrize(
    ("objects", "errors", "stderr"),
    [
        (merge(ROOK, ODF), None, "verdict: ODF present"),
        (ODF, None, "verdict: ODF present"),
        (ROOK, UNKNOWN_ERRORS, "verdict: unknown"),
        ({"cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")]}, None, "verdict: unknown"),
    ],
    ids=["odf-and-rook", "odf-only", "lookup-error", "orphaned-cephcluster"],
)
def test_classified_functions_refuse_and_change_nothing(tmp_path, call, objects, errors, stderr):
    result, mutations = _run(tmp_path, call, objects=objects, errors=errors, env={**STALE_ENV, **WIPE_ENV})

    assert "rc=1" in result.stdout, result.stderr
    assert stderr in result.stderr
    assert mutations == []


@pytest.mark.parametrize("call", CLASSIFIED)
@pytest.mark.parametrize("omit", [("rook_classify",), ("rook_only", "rook_gone")], ids=["classify", "gates"])
def test_classified_functions_refuse_when_a_gate_is_undefined(tmp_path, call, omit):
    # A new shell that inherited the flag but never defined the gate.
    result, mutations = _run(tmp_path, call, env={**STALE_ENV, **WIPE_ENV}, omit=omit)

    assert "rc=1" in result.stdout
    assert mutations == []


@pytest.mark.parametrize("namespace", ["", "openshift-storage", "Bad_Name"], ids=["empty", "odf", "invalid"])
@pytest.mark.parametrize("call", [*CLASSIFIED, "rook_clear_finalizers csi.ceph.io", "rook_record_data_dir",
                                  "rook_list_cluster_scoped"])
def test_every_function_refuses_a_namespace_that_is_not_rooks(tmp_path, call, namespace):
    result, mutations = _run(tmp_path, f"ROOK_NAMESPACE='{namespace}'; {call}", objects=ROOK,
                             env={**STALE_ENV, **WIPE_ENV})

    assert "rc=1" in result.stdout
    assert "is not a Rook namespace" in result.stderr
    assert mutations == []


def test_failed_classification_clears_an_inherited_flag(tmp_path):
    result, _ = _run(tmp_path, 'rook_classify; echo "flag=${ROOK_OWNERSHIP_CLASSIFIED:-}"', objects=ODF, env=STALE_ENV)

    assert "flag=\n" in result.stdout


def test_classify_passes_the_namespace_and_prefix(tmp_path):
    objects = merge(ROOK, {"csidrivers": [{"metadata": meta("lab.rbd.csi.ceph.com")}]})

    default, _ = _run(tmp_path / "a", "rook_classify", objects=objects)
    custom, _ = _run(tmp_path / "b", "ROOK_CSI_PREFIX=lab; rook_classify", objects=objects)

    assert "rc=1" in default.stdout
    assert "rc=0" in custom.stdout, custom.stderr


# --- Helm ---------------------------------------------------------------------------


def test_helm_uninstall_runs_for_a_release_whose_crds_are_kept(tmp_path):
    # The manifest and the live CRD both carry the keep annotation.
    kept = [c for c in CRDS if c["metadata"]["name"] != "cephclusters.ceph.rook.io"] + [
        {"metadata": meta("cephclusters.ceph.rook.io", annotations={"helm.sh/resource-policy": "keep"}),
         "spec": {"group": "ceph.rook.io"}}]
    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects={**OPERATOR, "crd": kept},
                             releases={"rook-ceph/rook-ceph": ROOK_CHART + KEPT_CRD})

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == ["helm uninstall rook-ceph -n rook-ceph"]


@pytest.mark.parametrize("manifest", [ROOK_CHART + KEPT_CRD + OWNED_CRD, OWNED_CRD + ROOK_CHART],
                         ids=["last-document", "first-document"])
def test_helm_uninstall_refuses_a_release_that_would_delete_a_crd(tmp_path, manifest):
    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects=OPERATOR,
                             releases={"rook-ceph/rook-ceph": manifest})

    assert "rc=1" in result.stdout
    assert "would delete a CRD without metadata.annotations helm.sh/resource-policy: keep" in result.stderr
    assert mutations == []


@pytest.mark.parametrize(
    ("call", "releases", "stderr"),
    [("ROOK_HELM_RELEASE=; rook_helm_uninstall", RELEASES, "set ROOK_HELM_RELEASE"),
     ("rook_helm_uninstall", {"rook-ceph/other": ROOK_CHART}, "no Helm release rook-ceph in rook-ceph")],
    ids=["no-release-set", "release-missing"],
)
def test_helm_uninstall_refuses_without_the_release(tmp_path, call, releases, stderr):
    result, mutations = _run(tmp_path, call, objects=OPERATOR, releases=releases)

    assert "rc=1" in result.stdout
    assert stderr in result.stderr
    assert mutations == []


@pytest.mark.parametrize(
    "objects",
    [ROOK, merge(OPERATOR, {"cephblockpools.ceph.rook.io": [{"metadata": meta("replicapool", "rook-ceph")}]})],
    ids=["cephcluster", "blockpool"],
)
def test_helm_uninstall_refuses_while_ceph_objects_remain(tmp_path, objects):
    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects=objects,
                             releases={"rook-ceph/rook-ceph": ROOK_CHART + KEPT_CRD})

    assert "rc=1" in result.stdout
    assert "run rook_delete_ceph_crs first; Helm release not uninstalled" in result.stderr
    assert mutations == []


@pytest.mark.parametrize(
    "crd",
    [
        # the annotation text in the wrong block
        "---\nkind: CustomResourceDefinition\nmetadata:\n  name: x.ceph.rook.io\n  labels:\n"
        "    helm.sh/resource-policy: keep\n",
        # under spec, not metadata
        "---\nkind: CustomResourceDefinition\nmetadata:\n  name: x.ceph.rook.io\nspec:\n  annotations:\n"
        "    helm.sh/resource-policy: keep\n",
        # only in a comment
        "---\n# helm.sh/resource-policy: keep\nkind: CustomResourceDefinition\nmetadata:\n  name: x.ceph.rook.io\n",
        # another value
        "---\nkind: CustomResourceDefinition\nmetadata:\n  name: x.ceph.rook.io\n  annotations:\n"
        "    helm.sh/resource-policy: delete\n",
        # a quoted kind
        '---\nkind: "CustomResourceDefinition"\nmetadata:\n  name: x.ceph.rook.io\n',
        # CRDs nested in a List
        "---\nkind: List\nitems:\n- kind: CustomResourceDefinition\n  metadata:\n    name: x.ceph.rook.io\n",
    ],
    ids=["labels", "spec", "comment", "other-value", "quoted-kind", "list"],
)
def test_helm_keep_check_reads_the_metadata_annotation_only(tmp_path, crd):
    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects=OPERATOR,
                             releases={"rook-ceph/rook-ceph": ROOK_CHART + crd})

    assert "rc=1" in result.stdout
    assert "would delete a CRD without metadata.annotations helm.sh/resource-policy: keep" in result.stderr
    assert mutations == []


# A multi-line annotation value can carry the keep line as text; the live CRD shows
# whether the annotation exists.
SPOOFED_KEEP = ("---\nkind: CustomResourceDefinition\nmetadata:\n  name: cephclusters.ceph.rook.io\n"
                "  annotations:\n    note: \"first line\n    helm.sh/resource-policy: keep\n    last line\"\n")


def _live_crd(annotations):
    crds = [c for c in CRDS if c["metadata"]["name"] != "cephclusters.ceph.rook.io"]
    return crds + [_crd("cephclusters.ceph.rook.io", "ceph.rook.io", annotations=annotations)]


def test_helm_uninstall_refuses_when_a_live_crd_of_the_release_is_not_kept(tmp_path):
    objects = {**OPERATOR, "crd": _live_crd({"meta.helm.sh/release-name": "rook-ceph", "meta.helm.sh/release-namespace": "rook-ceph"})}

    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects=objects,
                             releases={"rook-ceph/rook-ceph": ROOK_CHART + SPOOFED_KEEP})

    assert "rc=1" in result.stdout
    assert "live CRDs of release rook-ceph lack metadata.annotations helm.sh/resource-policy: keep: " \
        "cephclusters.ceph.rook.io" in result.stderr
    assert mutations == []


def test_helm_uninstall_checks_a_manifest_crd_by_name_without_ownership_annotations(tmp_path):
    # The live CRD lost its Helm annotations; the manifest still names it.
    objects = {**OPERATOR, "crd": _live_crd({})}

    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects=objects,
                             releases={"rook-ceph/rook-ceph": ROOK_CHART + SPOOFED_KEEP})

    assert "rc=1" in result.stdout
    assert "lack metadata.annotations helm.sh/resource-policy: keep: cephclusters.ceph.rook.io" in result.stderr
    assert mutations == []


def test_helm_uninstall_refuses_a_crd_without_a_readable_name(tmp_path):
    nameless = "---\nkind: CustomResourceDefinition\nmetadata:\n  annotations:\n    helm.sh/resource-policy: keep\n"

    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects=OPERATOR,
                             releases={"rook-ceph/rook-ceph": ROOK_CHART + nameless})

    assert "rc=1" in result.stdout
    assert "has a CRD whose metadata.name cannot be read" in result.stderr
    assert mutations == []


def test_helm_uninstall_runs_when_the_live_crds_of_the_release_are_kept(tmp_path):
    objects = {**OPERATOR, "crd": _live_crd({**{"meta.helm.sh/release-name": "rook-ceph", "meta.helm.sh/release-namespace": "rook-ceph"}, "helm.sh/resource-policy": "keep"})}

    result, mutations = _run(tmp_path, "rook_helm_uninstall", objects=objects,
                             releases={"rook-ceph/rook-ceph": ROOK_CHART + KEPT_CRD})

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == ["helm uninstall rook-ceph -n rook-ceph"]


# --- CR, operator, and CRD deletion -------------------------------------------------


def test_cr_deletion_runs_in_order_without_waiting_and_stops_at_a_kind_that_stays(tmp_path):
    held = {"cephblockpools.ceph.rook.io": [
        {"kind": "CephBlockPool", "metadata": meta("replicapool", "rook-ceph", finalizers=["cephblockpool.ceph.rook.io"])}
    ]}

    result, mutations = _run(tmp_path, "rook_delete_ceph_crs", objects=merge(ROOK, held), blocking=True)

    assert "rc=1" in result.stdout
    assert "still present in rook-ceph: cephblockpools.ceph.rook.io/replicapool" in result.stderr
    assert "Orphans After An Interrupted Uninstall" in result.stderr
    assert mutations == [
        f"-n rook-ceph delete {kind} --all --ignore-not-found --wait=false"
        for kind in ("cephnfses.ceph.rook.io", "cephobjectstores.ceph.rook.io", "cephfilesystems.ceph.rook.io",
                     "cephblockpools.ceph.rook.io")
    ]
    assert "would block" not in result.stderr


def test_cr_deletion_skips_a_kind_whose_crd_is_absent(tmp_path):
    groups = dict(GROUPS, **{"ceph.rook.io": [k for k in GROUPS["ceph.rook.io"] if k[0] != "cephnfses.ceph.rook.io"]})

    result, mutations = _run(tmp_path, "rook_delete_ceph_crs", objects={"deployments": [rook_operator()]},
                             groups=groups)

    assert "rc=0" in result.stdout, result.stderr
    assert "skipping cephnfses.ceph.rook.io: its CRD is not installed" in result.stderr
    assert len(mutations) == 4
    assert not [m for m in mutations if "cephnfses" in m]


def test_operator_deletion_refuses_while_the_cephcluster_exists(tmp_path):
    result, mutations = _run(tmp_path, "rook_delete_operator", objects=ROOK)

    assert "rc=1" in result.stdout
    assert "run rook_delete_ceph_crs first" in result.stderr
    assert mutations == []


def test_operator_deletion_deletes_by_kind_in_its_namespace_only(tmp_path):
    result, mutations = _run(tmp_path, "rook_delete_operator", objects={"deployments": [rook_operator()]},
                             blocking=True)

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == [
        "-n rook-ceph delete drivers.csi.ceph.io --all --ignore-not-found --wait=false",
        "-n rook-ceph delete clientprofiles.csi.ceph.io --all --ignore-not-found --wait=false",
        "-n rook-ceph delete deployments --all --ignore-not-found --wait=false",
        "-n rook-ceph delete daemonsets --all --ignore-not-found --wait=false",
        "-n rook-ceph delete serviceaccounts --all --ignore-not-found --wait=false",
        "-n rook-ceph delete roles --all --ignore-not-found --wait=false",
        "-n rook-ceph delete rolebindings --all --ignore-not-found --wait=false",
        "delete namespace rook-ceph --ignore-not-found --wait=false",
    ]
    assert not [m for m in mutations if " crd" in m or "-f" in m.split() or "--filename" in m]


@pytest.mark.parametrize(
    ("objects", "named"),
    [
        ({"validatingwebhookconfigurations": [{"kind": "ValidatingWebhookConfiguration", "metadata": meta("rook-ceph-webhook"),
           "webhooks": [{"clientConfig": {"service": {"namespace": "rook-ceph", "name": "rook-ceph-admission"}}}]}]},
         "ValidatingWebhookConfiguration/rook-ceph-webhook"),
        ({"mutatingwebhookconfigurations": [{"kind": "MutatingWebhookConfiguration", "metadata": meta("m"),
           "webhooks": [{"clientConfig": {"service": {"namespace": "rook-ceph", "name": "x"}}}]}]},
         "MutatingWebhookConfiguration/m"),
        ({"apiservices": [{"metadata": meta("v1.example.test"), "spec": {"service": {"namespace": "rook-ceph"}}}]},
         "APIService/v1.example.test"),
    ],
    ids=["validating", "mutating", "apiservice"],
)
def test_operator_deletion_refuses_while_the_namespace_serves_the_api(tmp_path, objects, named):
    other = {"validatingwebhookconfigurations": [{"kind": "ValidatingWebhookConfiguration", "metadata": meta("elsewhere"),
             "webhooks": [{"clientConfig": {"service": {"namespace": "other", "name": "x"}}}]}]}

    result, mutations = _run(tmp_path, "rook_delete_operator", objects=merge(OPERATOR, other, objects))

    assert "rc=1" in result.stdout
    assert f"served from rook-ceph: {named}" in result.stderr
    assert "elsewhere" not in result.stderr
    assert mutations == []


@pytest.mark.parametrize(
    "call", ["rook_delete_operator", "rook_delete_ceph_crs", "rook_helm_uninstall",
             "ROOK_CONFIRM_DESTROY_DATA=yes-really-destroy-data rook_set_cleanup_policy"],
)
def test_running_rook_steps_refuse_a_second_rook_namespace(tmp_path, call):
    objects = {"deployments": [rook_operator()], "cephclusters.ceph.rook.io": [ceph_cluster("b", "storage-b")]}

    result, mutations = _run(tmp_path, call, objects=objects)

    assert "rc=1" in result.stdout
    assert "expected upstream Rook in exactly rook-ceph, found: rook-ceph storage-b" in result.stderr
    assert mutations == []


def test_crd_deletion_refuses_while_rook_still_runs(tmp_path):
    # An operator without a CephCluster yet: no instance holds the CRDs, but the
    # operator would lose them under its feet.
    result, mutations = _run(tmp_path, "rook_delete_crds", objects={"deployments": [rook_operator()]})

    assert "rc=1" in result.stdout
    assert "upstream Rook still runs in: rook-ceph" in result.stderr
    assert mutations == []


@pytest.mark.parametrize(
    ("objects", "named"),
    [
        ({"cephblockpools.ceph.rook.io": [{"metadata": meta("pool", "elsewhere")}]}, "cephblockpools.ceph.rook.io/pool"),
        ({"objectbucketclaims.objectbucket.io": [{"metadata": meta("claim", "app")}]}, "objectbucketclaims.objectbucket.io/claim"),
        ({"objectbuckets.objectbucket.io": [{"metadata": meta("obc-app-claim")}]}, "objectbuckets.objectbucket.io/obc-app-claim"),
        ({"clientprofiles.csi.ceph.io": [{"metadata": meta("rook-ceph", "rook-ceph", finalizers=["x"])}]},
         "clientprofiles.csi.ceph.io/rook-ceph"),
    ],
    ids=["pool-in-another-namespace", "bucket-claim", "cluster-scoped-bucket", "held-clientprofile"],
)
def test_crd_deletion_refuses_while_any_instance_remains_anywhere(tmp_path, objects, named):
    result, mutations = _run(tmp_path, "rook_delete_crds", objects=objects)

    assert "rc=1" in result.stdout
    assert f"instances remain: {named}" in result.stderr
    assert "no CRD deleted" in result.stderr
    assert mutations == []


def test_crd_deletion_on_a_clean_cluster_deletes_rooks_groups_only(tmp_path):
    result, mutations = _run(tmp_path, "rook_delete_crds")

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == [
        "delete crd cephclusters.ceph.rook.io cephblockpools.ceph.rook.io cephfilesystems.ceph.rook.io "
        "cephobjectstores.ceph.rook.io cephnfses.ceph.rook.io --wait=false",
        "delete crd drivers.csi.ceph.io clientprofiles.csi.ceph.io --wait=false",
        "delete crd objectbucketclaims.objectbucket.io objectbuckets.objectbucket.io --wait=false",
    ]
    for decoy in DECOY_CRDS:
        assert not [m for m in mutations if decoy["metadata"]["name"] in m]


def _crd(name, group, labels=None, annotations=None):
    return {"metadata": meta(name, labels=labels or {}, annotations=annotations or {}), "spec": {"group": group}}


@pytest.mark.parametrize(
    ("crd", "csvs", "reason"),
    [
        (_crd("objectbucketclaims.objectbucket.io", "objectbucket.io", labels={"olm.managed": "true"}), [], "OLM labels"),
        (_crd("drivers.csi.ceph.io", "csi.ceph.io", labels={"operators.coreos.com/cephcsi-operator.ceph-csi": ""}),
         [], "OLM labels"),
        (_crd("drivers.csi.ceph.io", "csi.ceph.io", annotations={"meta.helm.sh/release-name": "ceph-csi-operator",
                                                                  "meta.helm.sh/release-namespace": "ceph-csi"}),
         [], "Helm release ceph-csi/ceph-csi-operator"),
        # Same release name, another namespace: another product's release.
        (_crd("drivers.csi.ceph.io", "csi.ceph.io", annotations={"meta.helm.sh/release-name": "rook-ceph",
                                                                  "meta.helm.sh/release-namespace": "other-storage"}),
         [], "Helm release other-storage/rook-ceph"),
        # No release namespace recorded: ownership cannot be proven.
        (_crd("drivers.csi.ceph.io", "csi.ceph.io", annotations={"meta.helm.sh/release-name": "rook-ceph"}),
         [], "Helm release /rook-ceph"),
        # Only a release namespace recorded: Helm-owned, and not provably ours.
        (_crd("drivers.csi.ceph.io", "csi.ceph.io", annotations={"meta.helm.sh/release-namespace": "other-storage"}),
         [], "Helm release other-storage/"),
        (_crd("objectbuckets.objectbucket.io", "objectbucket.io"),
         [{"metadata": meta("noobaa-operator.v5.17.0", "noobaa"),
           "spec": {"customresourcedefinitions": {"owned": [{"name": "objectbuckets.objectbucket.io"}]}}}],
         "listed by a ClusterServiceVersion"),
        (_crd("cephclusters.ceph.rook.io", "ceph.rook.io"),
         [{"metadata": meta("other.v1", "x"),
           "spec": {"customresourcedefinitions": {"required": [{"name": "cephclusters.ceph.rook.io"}]}}}],
         "listed by a ClusterServiceVersion"),
    ],
    ids=["olm-managed", "olm-package-label", "other-helm-release", "same-name-other-namespace",
         "no-release-namespace", "release-namespace-only", "csv-owned", "csv-required"],
)
def test_crd_deletion_refuses_crds_another_product_manages(tmp_path, crd, csvs, reason):
    crds = [c for c in CRDS if c["metadata"]["name"] != crd["metadata"]["name"]] + [crd]
    objects = {"crd": crds, "clusterserviceversions.operators.coreos.com": csvs}

    result, mutations = _run(tmp_path, "rook_delete_crds", objects=objects)

    assert "rc=1" in result.stdout
    assert f"{crd['metadata']['name']}: {reason}" in result.stderr
    assert mutations == []


def test_crd_deletion_accepts_crds_of_its_own_helm_release(tmp_path):
    crd = _crd("cephclusters.ceph.rook.io", "ceph.rook.io", annotations={"meta.helm.sh/release-name": "rook-ceph", "meta.helm.sh/release-namespace": "rook-ceph"})
    crds = [c for c in CRDS if c["metadata"]["name"] != "cephclusters.ceph.rook.io"] + [crd]

    result, mutations = _run(tmp_path, "rook_delete_crds", objects={"crd": crds})

    assert "rc=0" in result.stdout, result.stderr
    assert len(mutations) == 3


def test_crd_deletion_fails_closed_on_discovery_errors(tmp_path):
    result, mutations = _run(
        tmp_path, "rook_delete_crds", errors={"api-resources:objectbucket.io": "Error from server: discovery failed"}
    )

    assert "rc=1" in result.stdout
    assert mutations == []


# --- dataDirHostPath --------------------------------------------------------------


def test_record_data_dir_reads_this_clusters_path_mons_and_server(tmp_path):
    cluster = dict(ceph_cluster("rook-ceph", "rook-ceph"), spec={"dataDirHostPath": "/var/lib/rook-lab"})
    other = dict(ceph_cluster("other", "storage-b"), spec={"dataDirHostPath": "/elsewhere"})
    mons = {"metadata": meta("rook-ceph-mon-endpoints", "rook-ceph"),
            "data": {"data": "a=192.0.2.10:6789,b=192.0.2.11:6789"}}

    result, _ = _run(
        tmp_path,
        'rook_record_data_dir; echo "dir=$ROOK_DATA_DIR mons=$ROOK_MON_IDS ns=$ROOK_DATA_DIR_NAMESPACE at=$ROOK_DATA_DIR_SERVER"',
        objects={"cephclusters.ceph.rook.io": [cluster, other], "configmaps": [mons]},
    )

    assert f"dir=/var/lib/rook-lab mons=a b ns=rook-ceph at={SHOW_SERVER}\n" in result.stdout


def test_record_data_dir_defaults_the_path_and_tolerates_missing_mons(tmp_path):
    result, _ = _run(tmp_path, 'rook_record_data_dir; echo "dir=$ROOK_DATA_DIR mons=[$ROOK_MON_IDS]"',
                     objects={"cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")]})

    assert "dir=/var/lib/rook mons=[]\n" in result.stdout


def test_record_data_dir_records_nothing_when_a_lookup_fails(tmp_path):
    result, _ = _run(tmp_path, 'rook_record_data_dir; echo "rc=$? dir=[$ROOK_DATA_DIR]"',
                     objects={"cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")]},
                     errors={"configmaps": "Error from server (Forbidden): configmaps"}, env=WIPE_ENV)

    assert "rc=1 dir=[]\n" in result.stdout


@pytest.mark.parametrize(
    ("path", "stderr"),
    [
        ("", "is not a plain absolute path"),
        ("relative/rook", "is not a plain absolute path"),
        ("/", "is not a plain absolute path"),
        ("/rook", "is not a plain absolute path"),
        ("/var/lib/../rook", "is not a plain absolute path"),
        ("/var/lib/./rook", "is not a plain absolute path"),
        ("/var/lib/rook/.", "is not a plain absolute path"),
        ("/var/lib/rook/", "is not a plain absolute path"),
        ("/var/lib/rook'; rm -rf /", "is not a plain absolute path"),
        ("/var/lib", "is a system directory"),
        ("/var/log", "is a system directory"),
        ("/var/lib/ceph", "does not name rook"),
        ("/srv/data", "does not name rook"),
    ],
)
def test_wipe_refuses_an_unsafe_path(tmp_path, path, stderr):
    result, mutations = _run(tmp_path, f'ROOK_DATA_DIR="{path}" rook_wipe_data_dir node-a',
                             env={"ROOK_DATA_DIR_SERVER": SHOW_SERVER})

    assert "rc=1" in result.stdout
    assert stderr in result.stderr
    assert mutations == []


@pytest.mark.parametrize("path", ["/var/lib", "/var/log", "/bin", "/etc", "/usr", "/var", "/boot"])
def test_wipe_refuses_system_directories_even_with_the_name_override(tmp_path, path):
    result, mutations = _run(tmp_path, f'ROOK_DATA_DIR="{path}" ROOK_DATA_DIR_ANY_NAME=yes rook_wipe_data_dir node-a',
                             env={"ROOK_DATA_DIR_SERVER": SHOW_SERVER})

    assert "rc=1" in result.stdout
    assert mutations == []


def test_wipe_accepts_another_name_only_with_the_override(tmp_path):
    result, mutations = _run(tmp_path, "ROOK_DATA_DIR=/srv/ceph-data ROOK_DATA_DIR_ANY_NAME=yes rook_wipe_data_dir node-a",
                             env=WIPE_ENV)

    assert "rc=0" in result.stdout, result.stderr
    assert len(mutations) == 1


@pytest.mark.parametrize("server", ["", "https://api.other.example.com:6443"], ids=["unrecorded", "other-cluster"])
def test_wipe_refuses_a_path_recorded_on_another_cluster(tmp_path, server):
    result, mutations = _run(tmp_path, "rook_wipe_data_dir node-a",
                             env={"ROOK_DATA_DIR": "/var/lib/rook", "ROOK_DATA_DIR_SERVER": server})

    assert "rc=1" in result.stdout
    assert "you are logged in to" in result.stderr
    assert mutations == []


@pytest.mark.parametrize(
    ("objects", "stderr"),
    [
        (ROOK, "upstream Rook still runs in: rook-ceph"),
        ({"cephclusters.ceph.rook.io": [ceph_cluster("other", "storage-b")]}, "verdict: unknown"),
        ({"storageclusters.ocs.openshift.io": [{"metadata": meta("ocs-storagecluster", "openshift-storage")}]},
         "verdict: ODF present"),
    ],
    ids=["rook-running", "other-cephcluster", "odf-storagecluster"],
)
def test_wipe_refuses_while_another_ceph_may_use_the_path(tmp_path, objects, stderr):
    groups = dict(GROUPS, **{"ocs.openshift.io": [["storageclusters.ocs.openshift.io", True]]})

    result, mutations = _run(tmp_path, "rook_wipe_data_dir node-a", objects=objects, groups=groups, env=WIPE_ENV)

    assert "rc=1" in result.stdout
    assert stderr in result.stderr
    assert mutations == []


def test_wipe_removes_only_this_clusters_directories(tmp_path):
    result, mutations = _run(tmp_path, 'ROOK_MON_IDS="a c"; rook_wipe_data_dir node-a', env=WIPE_ENV)

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == [
        "debug node/node-a -- chroot /host bash -c "
        "rm -rf -- '/var/lib/rook/rook-ceph' '/var/lib/rook/mon-a' '/var/lib/rook/mon-c'; ls -la '/var/lib/rook'/"
    ]
    # an ODF leftover such as /var/lib/rook/openshift-storage is never named
    assert "openshift-storage" not in mutations[0]
    assert "/*" not in mutations[0]


@pytest.mark.parametrize("recorded", ["", "storage-b"], ids=["unrecorded", "other-namespace"])
def test_wipe_refuses_a_path_recorded_for_another_namespace(tmp_path, recorded):
    result, mutations = _run(tmp_path, "rook_wipe_data_dir node-a", env={**WIPE_ENV, "ROOK_DATA_DIR_NAMESPACE": recorded})

    assert "rc=1" in result.stdout
    assert f"ROOK_DATA_DIR was recorded for namespace '{recorded}', not rook-ceph" in result.stderr
    assert mutations == []


def test_wipe_warns_when_no_mon_ids_were_recorded(tmp_path):
    result, mutations = _run(tmp_path, "rook_wipe_data_dir node-a", env=WIPE_ENV)

    assert "rc=0" in result.stdout, result.stderr
    assert "warning: no mon IDs were recorded" in result.stderr
    assert len(mutations) == 1


def test_wipe_refuses_an_invalid_mon_id(tmp_path):
    result, mutations = _run(tmp_path, "ROOK_MON_IDS='a ../x'; rook_wipe_data_dir node-a", env=WIPE_ENV)

    assert "rc=1" in result.stdout
    assert "invalid mon id" in result.stderr
    assert mutations == []


# --- cluster destruction ----------------------------------------------------------


def test_cleanup_policy_needs_the_confirmation(tmp_path):
    result, mutations = _run(tmp_path, "rook_set_cleanup_policy", objects=ROOK)

    assert "rc=1" in result.stdout
    assert "ROOK_CONFIRM_DESTROY_DATA=yes-really-destroy-data" in result.stderr
    assert mutations == []


def test_cleanup_policy_patches_the_cephcluster_of_its_namespace(tmp_path):
    result, mutations = _run(tmp_path, "ROOK_CONFIRM_DESTROY_DATA=yes-really-destroy-data rook_set_cleanup_policy",
                             objects=ROOK)

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == [
        "-n rook-ceph patch cephclusters.ceph.rook.io/rook-ceph --type=merge "
        '-p {"spec":{"cleanupPolicy":{"confirmation":"yes-really-destroy-data"}}}'
    ]


@pytest.mark.parametrize(
    ("call", "stderr"),
    [
        ("rook_wipe_osd_disk node-a /dev/sdb", "is not a /dev/disk/by-id/ path"),
        ("ROOK_CONFIRM_WIPE_DISK=/dev/sdb rook_wipe_osd_disk node-a /dev/sdb", "is not a /dev/disk/by-id/ path"),
        (f"rook_wipe_osd_disk node-a {DISK}", f"set ROOK_CONFIRM_WIPE_DISK={DISK}"),
        (f"ROOK_CONFIRM_WIPE_DISK=/dev/disk/by-id/other rook_wipe_osd_disk node-a {DISK}",
         f"set ROOK_CONFIRM_WIPE_DISK={DISK}"),
        (f"ROOK_CONFIRM_WIPE_DISK='{DISK}; reboot' rook_wipe_osd_disk node-a '{DISK}; reboot'",
         "is not a /dev/disk/by-id/ path"),
        ("rook_wipe_osd_disk node-a", "usage: rook_wipe_osd_disk"),
    ],
    ids=["sdx", "sdx-confirmed", "unconfirmed", "other-disk-confirmed", "injection", "missing-disk"],
)
def test_osd_disk_wipe_refuses_without_a_stable_confirmed_path(tmp_path, call, stderr):
    result, mutations = _run(tmp_path, call)

    assert "rc=1" in result.stdout
    assert stderr in result.stderr
    assert mutations == []


def _wipe(tmp_path, **facts):
    call = f"ROOK_CONFIRM_WIPE_DISK={DISK} rook_wipe_osd_disk node-a {DISK}"
    result, mutations = _run(tmp_path, call, node=facts)
    return result, mutations, node_calls(tmp_path / "bin")


def _wiped(calls):
    return [c for c in calls if c[:2] == ["wipefs", "-af"] or c[0] == "sgdisk"]


@pytest.mark.parametrize(
    "signatures",
    ["", "ceph_bluestore", "gpt\nPMBR", "dos"],
    ids=["blank", "bluestore", "empty-gpt", "empty-dos"],
)
def test_osd_disk_wipe_checks_then_wipes_the_resolved_device_in_one_run(tmp_path, signatures):
    result, mutations, calls = _wipe(tmp_path, signatures=signatures)

    assert "rc=0" in result.stdout, result.stdout + result.stderr
    assert len([m for m in mutations if m.startswith("debug ")]) == 1
    assert mutations[0].endswith(f" _ {DISK}")
    assert _wiped(calls) == [["wipefs", "-af", "/dev/sdb"], ["sgdisk", "--zap-all", "/dev/sdb"]]
    # Every check ran before the first destructive call; the on-disk table is read
    # only when a partition-table signature was found.
    first = calls.index(["wipefs", "-af", "/dev/sdb"])
    checks = {c[0] for c in calls[:first]}
    assert checks >= {"readlink", "lsblk", "ls", "wipefs", "blkid", "findmnt", "swapon", "pvs"}
    assert ("sfdisk" in checks) == any(t in signatures for t in ("gpt", "dos"))
    assert "wiping /dev/sdb" in result.stdout


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        ({"type": "part"}, "type part, not a whole disk"),
        ({"type": "lvm"}, "type lvm, not a whole disk"),
        ({"names": "sdb\nsdb1\nsdb2"}, "partitions or child devices: sdb1 sdb2"),
        ({"holders": "dm-0"}, "holders: dm-0"),
        ({"mounts": "8:0\n8:16"}, "mounted on the host"),
        ({"swaps": "/dev/sdb"}, "active swap"),
        ({"pvs": "  /dev/sdb"}, "LVM physical volume /dev/sdb"),
        ({"signatures": "xfs"}, "signature xfs"),
        ({"signatures": "ext4"}, "signature ext4"),
        ({"signatures": "LVM2_member"}, "signature LVM2_member"),
        ({"signatures": "crypto_LUKS"}, "signature crypto_LUKS"),
        ({"signatures": "swap"}, "signature swap"),
        ({"signatures": "gpt\nPMBR\nxfs"}, "signature xfs"),
        ({"device": "sdb"}, "does not resolve to a device"),
        ({"absent": ["pvs"]}, "pvs is not available"),
        # wipefs saw nothing, the independent blkid probe did
        ({"blkid": "DEVNAME=/dev/sdb\nTYPE=xfs"}, "signature xfs"),
        ({"blkid_rc": 8}, "blkid -p failed with status 8"),
        # the kernel shows no partition, the on-disk table lists one
        ({"signatures": "gpt\nPMBR", "sfdisk": "label: gpt\ndevice: /dev/sdb\n/dev/sdb1 : start=2048, size=4096"},
         "on-disk partitions: /dev/sdb1"),
    ],
    ids=["partition", "lvm-volume", "children", "holders", "mounted", "swap-active", "physical-volume", "xfs",
         "ext4", "lvm-member", "luks", "swap-signature", "fs-after-table", "unresolved", "pvs-missing",
         "blkid-only-xfs", "blkid-error", "on-disk-partition"],
)
def test_osd_disk_wipe_refuses_a_disk_in_use(tmp_path, facts, reason):
    result, _, calls = _wipe(tmp_path, **facts)

    assert "rc=1" in result.stdout
    assert reason in result.stderr, result.stderr
    assert "disk not wiped" in result.stderr
    assert _wiped(calls) == []


@pytest.mark.parametrize(
    ("tool", "status"),
    [("readlink", 1), ("lsblk", 32), ("ls", 2), ("wipefs", 1), ("findmnt", 1), ("swapon", 1), ("pvs", 5),
     ("sfdisk", 1)],
)
def test_osd_disk_wipe_refuses_when_a_check_cannot_run(tmp_path, tool, status):
    # A partition-table signature, so the on-disk table is read too.
    result, _, calls = _wipe(tmp_path, fail={tool: status}, signatures="gpt\nPMBR")

    assert "rc=1" in result.stdout
    assert "a check could not run" in result.stderr, result.stderr
    assert "disk not wiped" in result.stderr
    assert _wiped(calls) == []


def test_osd_disk_wipe_reports_a_partial_wipe_when_a_write_fails(tmp_path):
    result, _, calls = _wipe(tmp_path, fail={"sgdisk": 1})

    assert "rc=1" in result.stdout
    assert ["wipefs", "-af", "/dev/sdb"] in calls
    assert "wipe step failed: sgdisk --zap-all" in result.stderr
    assert "the disk may be partly wiped" in result.stderr
    assert "disk not wiped" not in result.stderr


def test_osd_disk_wipe_refuses_a_partition_link(tmp_path):
    part = DISK + "-part3"
    result, mutations = _run(tmp_path, f"ROOK_CONFIRM_WIPE_DISK={part} rook_wipe_osd_disk node-a {part}", node={})

    assert "rc=1" in result.stdout
    assert "is a partition link" in result.stderr
    assert mutations == []


# --- finalizers, cluster-scoped objects, SCCs -------------------------------------


def test_clear_finalizers_refuses_while_deployments_remain(tmp_path):
    objects = {"deployments": [{"metadata": meta("rook-ceph-operator", "rook-ceph")}],
               "clientprofiles.csi.ceph.io": [{"metadata": meta("rook-ceph", "rook-ceph", finalizers=["x"])}]}

    result, mutations = _run(tmp_path, "rook_clear_finalizers csi.ceph.io", objects=objects)

    assert "rc=1" in result.stdout
    assert "remove the operators first" in result.stderr
    assert mutations == []


@pytest.mark.parametrize("kind", ["daemonsets", "statefulsets"])
def test_clear_finalizers_refuses_while_other_workloads_remain(tmp_path, kind):
    objects = {kind: [{"metadata": meta("csi-rbdplugin", "rook-ceph")}],
               "clientprofiles.csi.ceph.io": [{"metadata": meta("rook-ceph", "rook-ceph", finalizers=["x"], deletionTimestamp=OLD)}]}

    result, mutations = _run(tmp_path, "rook_clear_finalizers csi.ceph.io", objects=objects)

    assert "rc=1" in result.stdout
    assert f"workloads still run in rook-ceph: {kind}/csi-rbdplugin" in result.stderr
    assert mutations == []


def test_clear_finalizers_refuses_while_an_operator_runs_elsewhere(tmp_path):
    # An external-mode CephCluster: no workloads in its namespace, its operator elsewhere.
    objects = {
        "deployments": [rook_operator("rook-ceph")],
        "cephclusters.ceph.rook.io": [{"metadata": meta("external", "ext", finalizers=["cephcluster.ceph.rook.io"],
                                                        deletionTimestamp=OLD)}],
    }

    result, mutations = _run(tmp_path, "ROOK_NAMESPACE=ext; rook_clear_finalizers ceph.rook.io", objects=objects)

    assert "rc=1" in result.stdout
    assert "a Rook operator still runs: rook-ceph/rook-ceph-operator" in result.stderr
    assert mutations == []


def test_clear_finalizers_ignores_an_operator_that_is_being_deleted(tmp_path):
    objects = {
        "deployments": [rook_operator("rook-ceph", deletionTimestamp=OLD)],
        "cephclusters.ceph.rook.io": [{"metadata": meta("external", "ext", finalizers=["x"], deletionTimestamp=OLD)}],
    }

    result, mutations = _run(tmp_path, "ROOK_NAMESPACE=ext; rook_clear_finalizers ceph.rook.io", objects=objects)

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == ['-n ext patch cephclusters.ceph.rook.io/external --type=merge -p {"metadata":{"finalizers":[]}}']


@pytest.mark.parametrize("pod_extra", [{}, {"deletionTimestamp": OLD}], ids=["running", "terminating"])
def test_clear_finalizers_refuses_while_operator_pods_remain(tmp_path, pod_extra):
    objects = {
        "deployments": [rook_operator("rook-ceph", deletionTimestamp=OLD)],
        "pods": [{"metadata": meta("rook-ceph-operator-5d9c7", "rook-ceph", labels={"app": "rook-ceph-operator"},
                                   **pod_extra)}],
        "cephclusters.ceph.rook.io": [{"metadata": meta("external", "ext", finalizers=["x"], deletionTimestamp=OLD)}],
    }

    result, mutations = _run(tmp_path, "ROOK_NAMESPACE=ext; rook_clear_finalizers ceph.rook.io", objects=objects)

    assert "rc=1" in result.stdout
    assert "rook-ceph-operator pods still exist: " in result.stderr
    assert "rook-ceph-operator-5d9c7 - wait until they are gone" in result.stderr
    assert mutations == []


def test_clear_finalizers_patches_only_deleting_objects_in_the_rook_namespace(tmp_path):
    objects = {"clientprofiles.csi.ceph.io": [
        {"metadata": meta("rook-ceph", "rook-ceph", finalizers=["x"], deletionTimestamp=OLD)},
        {"metadata": meta("live", "rook-ceph", finalizers=["x"])},
        {"metadata": meta("ocs", "openshift-storage", finalizers=["x"], deletionTimestamp=OLD)},
    ]}

    result, mutations = _run(tmp_path, "rook_clear_finalizers csi.ceph.io", objects=objects)

    assert "rc=0" in result.stdout, result.stderr
    assert mutations == [
        '-n rook-ceph patch clientprofiles.csi.ceph.io/rook-ceph --type=merge -p {"metadata":{"finalizers":[]}}'
    ]
    assert "live" not in " ".join(mutations)


def test_cluster_scoped_listing_matches_by_provisioner_and_driver_only(tmp_path):
    objects = {
        "storageclasses": [
            {"metadata": meta("fast"), "provisioner": "lab.rbd.csi.ceph.com"},
            {"metadata": meta("buckets"), "provisioner": "lab.ceph.rook.io/bucket"},
            {"metadata": meta("rook-ceph-block"), "provisioner": "topolvm.io"},
            {"metadata": meta("lab-lookalike"), "provisioner": "lab.rbd.csi.ceph.com.example.test"},
            {"metadata": meta("odf"), "provisioner": "openshift-storage.rbd.csi.ceph.com"},
        ],
        "csidrivers": [{"metadata": meta("lab.nvmeof.csi.ceph.com")}, {"metadata": meta("rook-ceph.rbd.csi.ceph.com")}],
        "volumesnapshotclasses.snapshot.storage.k8s.io": [
            {"metadata": meta("snap"), "driver": "lab.cephfs.csi.ceph.com"},
            {"metadata": meta("other-snap"), "driver": "rook-ceph.cephfs.csi.ceph.com"},
        ],
    }

    result, mutations = _run(tmp_path, "ROOK_CSI_PREFIX=lab; rook_list_cluster_scoped", objects=objects)

    assert "rc=0" in result.stdout, result.stderr
    assert result.stdout.splitlines()[:-1] == [
        "StorageClass fast lab.rbd.csi.ceph.com",
        "StorageClass buckets lab.ceph.rook.io/bucket",
        "CSIDriver lab.nvmeof.csi.ceph.com",
        "VolumeSnapshotClass snap lab.cephfs.csi.ceph.com",
    ]
    assert mutations == []


@pytest.mark.parametrize(
    ("users", "deleted", "rc"),
    [
        (["system:serviceaccount:rook-ceph:rook-ceph-system"], True, "rc=0"),
        (["system:serviceaccount:openshift-storage:rook-ceph-system"], False, "rc=1"),
        (["system:serviceaccount:rook-ceph:rook-ceph-system", "system:serviceaccount:other:x"], False, "rc=1"),
        (["system:serviceaccount:rook-ceph-x:rook-ceph-system"], False, "rc=1"),
        ([], False, "rc=1"),
    ],
    ids=["rook", "odf", "mixed", "lookalike-namespace", "empty"],
)
def test_sccs_are_removed_only_when_every_user_is_rooks(tmp_path, users, deleted, rc):
    objects = {"scc": [{"metadata": meta("rook-ceph"), "users": users}]}

    result, mutations = _run(tmp_path, "rook_remove_sccs", objects=objects)

    assert rc in result.stdout, result.stderr
    assert mutations == (["delete scc rook-ceph --ignore-not-found --wait=false"] if deleted else [])


# --- static checks over the runbook -------------------------------------------------


def test_every_delete_in_the_runbook_functions_skips_waiting():
    for name, body in FUNCTIONS.items():
        for line in body.splitlines():
            if re.search(r"\boc\b.*\bdelete\b", line):
                assert "--wait=false" in line, f"{name}: {line.strip()}"


def test_no_runbook_function_deletes_by_file_or_deletes_crds_outside_rook_delete_crds():
    for name, body in FUNCTIONS.items():
        for line in body.splitlines():
            if re.search(r"\boc\b.*\bdelete\b", line):
                assert not re.search(r"\s(-f|--filename)\b", line), f"{name}: {line.strip()}"
                if name != "rook_delete_crds":
                    assert not re.search(r"\bdelete\s+crd\b", line), f"{name}: {line.strip()}"


def test_orphan_section_keeps_the_kubelet_warning_and_order():
    section = RUNBOOK_TEXT.split("## Orphans After An Interrupted Uninstall", 1)[1].split("\n## ", 1)[0]

    assert "restart the kubelet on that node" in section
    assert "never delete the volume directory under a running kubelet" in section
    assert "590 log lines a minute" in section
    order = ["The Pod the kubelet cannot release", "Its PVC", "`VolumeAttachment`s", "PVs of the removed driver",
             "consumer namespaces", "`ObjectBucket`s", "Cluster RBAC"]
    positions = [section.index(step) for step in order]
    assert positions == sorted(positions)
    assert "### Cluster RBAC left by Rook" in section
