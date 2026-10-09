from __future__ import annotations

import json
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
    meta,
    rook_operator,
    run_script,
    write_cluster_oc,
    write_jq_proxy,
    write_oc,
)

CONTEXT_ERROR = "Error in configuration: * context was not found for specified context: nope"
NO_TYPE = 'error: the server doesn\'t have a resource type "cephclusters"'
ODF_GROUPS = {"ocs.openshift.io": [["storageclusters.ocs.openshift.io", True]]}
CSI_GROUPS = {"csi.ceph.io": [["drivers.csi.ceph.io", True]]}


def _classify(bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_script("classify_ceph_ownership.sh", bin_dir, *args)


def _cluster(tmp_path: Path, clusters: list, deployments: list, extra: dict | None = None, **kwargs) -> Path:
    write_jq_proxy(tmp_path)
    write_cluster_oc(
        tmp_path,
        objects={"cephclusters.ceph.rook.io": clusters, "deployments": deployments, **(extra or {})},
        **kwargs,
    )
    return tmp_path


def _assert_refused(result, verdict: str, *fragments: str) -> None:
    assert result.returncode == 1, result.stderr
    assert result.stdout == ""
    assert verdict in result.stderr
    for fragment in fragments:
        assert fragment in result.stderr


def _assert_unknown(result, *fragments: str) -> None:
    _assert_refused(result, "verdict: unknown", *fragments)


def _assert_odf(result, *fragments: str) -> None:
    _assert_refused(result, "verdict: ODF present", "hand off to openshift-odf", *fragments)


def test_classify_reports_rook_only_and_names_the_cluster(tmp_path):
    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()]))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"
    assert f"classifying {SHOW_SERVER}" in result.stderr
    assert "upstream Rook in rook-ceph: CephCluster: rook-ceph" in result.stderr
    assert "verdict: upstream Rook only, in: rook-ceph" in result.stderr


def test_classify_reports_neither_on_an_empty_cluster(tmp_path):
    result = _classify(_cluster(tmp_path, [], []))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "verdict: no Rook or ODF" in result.stderr


def test_classify_treats_a_missing_cephcluster_crd_as_none(tmp_path):
    write_jq_proxy(tmp_path)
    write_cluster_oc(tmp_path, errors={"cephclusters.ceph.rook.io": NO_TYPE})

    result = _classify(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "verdict: no Rook or ODF" in result.stderr


def test_classify_accepts_its_own_ceph_csi_with_the_rook_prefix(tmp_path):
    extra = {
        "drivers.csi.ceph.io": [{"kind": "Driver", "metadata": meta("rook-ceph.rbd.csi.ceph.com", "rook-ceph")}],
        "csidrivers": [{"metadata": meta("rook-ceph.rbd.csi.ceph.com")}],
        "pv": [{"metadata": meta("pvc-1"), "spec": {"csi": {"driver": "rook-ceph.cephfs.csi.ceph.com"}}}],
    }

    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], extra,
                                groups=CSI_GROUPS))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"


def test_classify_honours_a_custom_csi_prefix(tmp_path):
    extra = {"csidrivers": [{"metadata": meta("lab.rbd.csi.ceph.com")}]}
    bin_dir = _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], extra)

    assert _classify(bin_dir, "--csi-prefix", "lab").returncode == 0
    _assert_unknown(_classify(bin_dir), "unknown owner of CSIDriver lab.rbd.csi.ceph.com")


def test_classify_derives_the_csi_prefix_from_the_namespace(tmp_path):
    extra = {"csidrivers": [{"metadata": meta("storage-a.rbd.csi.ceph.com")}]}
    bin_dir = _cluster(tmp_path, [ceph_cluster("a", "storage-a")], [rook_operator("storage-a")], extra)

    result = _classify(bin_dir, "--namespace", "storage-a")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "storage-a\n"


@pytest.mark.parametrize(
    ("extra", "groups", "named"),
    [
        ({"storageclusters.ocs.openshift.io": [{"metadata": meta("ocs-storagecluster", "openshift-storage")}]},
         ODF_GROUPS, "ODF: StorageCluster openshift-storage/ocs-storagecluster"),
        ({"subscriptions.operators.coreos.com": [{"metadata": meta("odf-operator", "openshift-storage"),
                                                  "spec": {"name": "odf-operator"}}]},
         None, "ODF: Subscription openshift-storage/odf-operator: ODF package odf-operator"),
        ({"clusterserviceversions.operators.coreos.com": [{"metadata": meta("ocs-operator.v4.20.17-rhodf", "openshift-storage")}]},
         None, "ODF: CSV openshift-storage/ocs-operator.v4.20.17-rhodf"),
        ({"csidrivers": [{"metadata": meta("openshift-storage.rbd.csi.ceph.com")}]},
         None, "ODF: CSIDriver openshift-storage.rbd.csi.ceph.com: ODF Ceph CSI driver"),
        ({"pv": [{"metadata": meta("pvc-odf"), "spec": {"csi": {"driver": "openshift-storage.rbd.csi.ceph.com"}}}]},
         None, "ODF: PV pvc-odf"),
    ],
    ids=["storagecluster", "subscription", "csv", "csidriver", "pv"],
)
def test_classify_hands_off_when_odf_is_present_next_to_rook(tmp_path, extra, groups, named):
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], extra, groups=groups)
    )

    _assert_odf(result, named)


@pytest.mark.parametrize(
    ("cluster", "why"),
    [
        (ceph_cluster("ocs-storagecluster-cephcluster", "openshift-storage"), "in openshift-storage"),
        (ceph_cluster("x", "elsewhere", ownerReferences=[{"kind": "StorageCluster", "name": "ocs-storagecluster"}]),
         "owned by a StorageCluster"),
        (ceph_cluster("ocs-storagecluster-cephcluster", "old"), "carries the ODF CephCluster name"),
    ],
    ids=["namespace", "owner", "name"],
)
def test_classify_hands_off_for_an_odf_cephcluster_without_rook(tmp_path, cluster, why):
    result = _classify(_cluster(tmp_path, [cluster], []))

    _assert_odf(result, why)


def test_classify_hands_off_for_odfs_rook_operator(tmp_path):
    operator = rook_operator("openshift-storage", {"olm.owner": "rook-ceph-operator.v4.20.17-rhodf"})

    result = _classify(_cluster(tmp_path, [], [operator]))

    _assert_odf(result, "Deployment openshift-storage/rook-ceph-operator")


def test_classify_reads_odf_crds_only_when_served(tmp_path):
    # No ocs.openshift.io group: the StorageCluster list is never requested.
    log = tmp_path / "argv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_jq_proxy(bin_dir)
    write_cluster_oc(bin_dir, log=log)

    result = _classify(bin_dir)

    assert result.returncode == 0, result.stderr
    log_text = log.read_text(encoding="utf-8")
    assert '"--api-group=ocs.openshift.io"' in log_text
    assert "storageclusters" not in log_text


@pytest.mark.parametrize(
    "operator",
    [
        rook_operator(labels={"olm.owner": "rook-ceph-operator.v1.20.5"}),
        rook_operator(labels={"operators.coreos.com/rook-ceph.rook-ceph": ""}),
    ],
    ids=["olm-owner", "olm-package-label"],
)
def test_classify_refuses_an_olm_installed_operator(tmp_path, operator):
    result = _classify(_cluster(tmp_path, [], [operator]))

    _assert_unknown(result, "unknown owner of Deployment rook-ceph/rook-ceph-operator: installed by OLM")


@pytest.mark.parametrize(
    "deployments",
    [
        [],
        [{"kind": "Deployment", "metadata": {"name": "rook-ceph-operator-custom", "namespace": "rook-ceph", "labels": {}}}],
        [rook_operator(deletionTimestamp=OLD)],
    ],
    ids=["absent", "renamed", "deleting"],
)
def test_classify_refuses_a_cephcluster_without_a_known_operator(tmp_path, deployments):
    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], deployments))

    _assert_unknown(
        result,
        "unknown owner of CephCluster rook-ceph/rook-ceph: no non-OLM rook-ceph-operator Deployment",
        "ownership of CephCluster rook-ceph/rook-ceph could not be classified",
    )


@pytest.mark.parametrize(
    ("extra", "named"),
    [
        ({"drivers.csi.ceph.io": [{"kind": "Driver", "metadata": meta("other.rbd.csi.ceph.com", "other")}]},
         "unknown owner of csi.ceph.io Driver other/other.rbd.csi.ceph.com"),
        ({"csidrivers": [{"metadata": meta("other.cephfs.csi.ceph.com")}]},
         "unknown owner of CSIDriver other.cephfs.csi.ceph.com"),
        ({"pv": [{"metadata": meta("pvc-2"), "spec": {"csi": {"driver": "other.rbd.csi.ceph.com"}}}]},
         "unknown owner of PV pvc-2"),
    ],
    ids=["csi-driver-object", "csidriver", "pv"],
)
def test_classify_refuses_a_ceph_csi_it_cannot_attribute(tmp_path, extra, named):
    # Even with this Rook running, a Ceph CSI under another prefix may serve volumes.
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], extra, groups=CSI_GROUPS)
    )

    _assert_unknown(result, named)


def test_classify_reports_odf_first_when_both_are_present(tmp_path):
    extra = {"csidrivers": [{"metadata": meta("openshift-storage.rbd.csi.ceph.com")},
                            {"metadata": meta("other.rbd.csi.ceph.com")}]}

    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], extra))

    _assert_odf(result, "unknown owner of CSIDriver other.rbd.csi.ceph.com")


def test_classify_reads_json_despite_stderr_noise(tmp_path):
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], noise=True)
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"


def test_classify_survives_a_nul_byte_on_stderr(tmp_path):
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], noise="warn\x00ing")
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"


@pytest.mark.parametrize(
    ("resource", "message"),
    [
        ("cephclusters.ceph.rook.io", "Error from server (Forbidden): cannot list resource"),
        ("deployments", "Error from server (Forbidden): cannot list resource"),
        ("subscriptions.operators.coreos.com", "Error from server (Forbidden): cannot list resource"),
        ("api-resources:ocs.openshift.io", "Error from server (Forbidden): cannot discover"),
        ("cephclusters.ceph.rook.io", CONTEXT_ERROR),
        ("deployments", CONTEXT_ERROR),
        ("csidrivers", CONTEXT_ERROR),
        # the CRD may be missing; the Deployment kind never is
        ("deployments", NO_TYPE),
        ("deployments", "Error from server (NotFound): the server could not find the requested resource"),
        # only "no such resource type" means "no CephCluster CRD"
        ("cephclusters.ceph.rook.io", "Error from server (NotFound): the server could not find the requested resource"),
    ],
    ids=["clusters-forbidden", "deployments-forbidden", "subscriptions-forbidden", "discovery-forbidden",
         "clusters-context", "deployments-context", "csidrivers-context",
         "deployments-no-type", "deployments-notfound", "clusters-notfound"],
)
def test_classify_stops_on_a_lookup_error(tmp_path, resource, message):
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], errors={resource: message})
    )

    _assert_unknown(result, message)


def test_classify_stops_on_a_failing_served_storagecluster_lookup(tmp_path):
    result = _classify(
        _cluster(tmp_path, [], [], groups=ODF_GROUPS, errors={"storageclusters.ocs.openshift.io": NO_TYPE})
    )

    _assert_unknown(result, "StorageCluster lookup failed")


def test_classify_stops_when_the_cluster_cannot_be_reached(tmp_path):
    result = _classify(_cluster(tmp_path, [], [], errors={"whoami": CONTEXT_ERROR}))

    _assert_unknown(result, "cannot reach the cluster", CONTEXT_ERROR)


@pytest.mark.parametrize(
    "output",
    ["", "{not json", "I1007 throttling\n{\"items\": []}"],
    ids=["empty", "unparseable", "stderr-merged-into-stdout"],
)
def test_classify_stops_when_a_successful_call_is_not_usable_json(tmp_path, output):
    write_jq_proxy(tmp_path)
    write_oc(
        tmp_path,
        f"""
        if sys.argv[1:2] == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if sys.argv[1:2] == ["api-resources"]:
            raise SystemExit(0)
        sys.stdout.write({output!r})
        raise SystemExit(0)
        """,
    )

    result = _classify(tmp_path)

    _assert_unknown(result)


def test_classify_stops_without_jq(tmp_path):
    write_cluster_oc(tmp_path)

    result = _classify(tmp_path)

    _assert_unknown(result, "verdict: unknown - jq CLI is required but not installed")


@pytest.mark.parametrize(
    "args",
    [("--bogus",), ("--namespace", "Bad_Name"), ("--csi-prefix", "a b"), ("--namespace",), ("--context=",)],
    ids=["unknown", "bad-namespace", "bad-prefix", "missing-value", "empty-context"],
)
def test_classify_rejects_bad_arguments(tmp_path, args):
    write_jq_proxy(tmp_path)
    write_cluster_oc(tmp_path)

    result = _classify(tmp_path, *args)

    assert result.returncode == 2
    assert result.stdout == ""


def test_classify_forwards_context(tmp_path):
    log = tmp_path / "argv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_jq_proxy(bin_dir)
    write_cluster_oc(bin_dir, log=log)

    result = _classify(bin_dir, "--context", "target")

    assert result.returncode == 0, result.stderr
    assert "(context: target)" in result.stderr
    assert all('"--context=target"' in line for line in log.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize(
    "args",
    [("--namespace", "openshift-storage"), ("--csi-prefix", "openshift-storage"), ("--csi-prefix=openshift-storage",)],
    ids=["namespace", "prefix", "prefix-equals"],
)
def test_classify_refuses_odfs_namespace_and_prefix(tmp_path, args):
    write_jq_proxy(tmp_path)
    write_cluster_oc(tmp_path, objects={"csidrivers": [{"metadata": meta("openshift-storage.rbd.csi.ceph.com")}]})

    result = _classify(tmp_path, *args)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "openshift-storage is ODF's namespace and CSI driver prefix" in result.stderr


def test_ownership_rule_checks_the_odf_prefix_before_the_rook_prefix(tmp_path):
    # Even if a caller handed the rule ODF's prefix as Rook's, ODF's drivers stay ODF's.
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required")
    empty = '{"items":[]}'
    csidrivers = json.dumps({"items": [{"metadata": {"name": "openshift-storage.rbd.csi.ceph.com"}}]})
    script = (
        f'. "{SCRIPTS / "rook_common.sh"}"; '
        f"jq_slurp \"$ROOK_CEPH_OWNERSHIP_JQ\" '{empty}' '{empty}' '{empty}' '{empty}' '{empty}' '{empty}' "
        f"'{csidrivers}' '{empty}' '\"^openshift-storage[.](rbd|cephfs|nfs|nvmeof)[.]csi[.]ceph[.]com$\"'"
    )

    result = subprocess.run([bash, "-c", script], capture_output=True, text=True, check=False,
                            env={"PATH": str(Path(jq).parent)})

    assert result.returncode == 0, result.stderr
    assert result.stdout == "odf\tCSIDriver openshift-storage.rbd.csi.ceph.com\tODF Ceph CSI driver\n"


def test_classify_attributes_nvmeof_drivers_to_rook(tmp_path):
    extra = {"csidrivers": [{"metadata": meta("rook-ceph.nvmeof.csi.ceph.com")}]}

    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], extra))

    assert result.returncode == 0, result.stderr
