from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cluster_fake import (  # noqa: E402
    OLD,
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


def _classify(bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_script("classify_rook_ownership.sh", bin_dir, *args)


def _cluster(tmp_path: Path, clusters: list, deployments: list, extra: dict | None = None, **kwargs) -> Path:
    write_jq_proxy(tmp_path)
    write_cluster_oc(
        tmp_path,
        objects={"cephclusters.ceph.rook.io": clusters, "deployments": deployments, **(extra or {})},
        **kwargs,
    )
    return tmp_path


def _assert_unknown(result, *fragments: str) -> None:
    assert result.returncode == 1, result.stderr
    assert result.stdout == ""
    assert "verdict: unknown" in result.stderr
    for fragment in fragments:
        assert fragment in result.stderr


def test_classify_reports_upstream_rook_and_names_the_cluster(tmp_path):
    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()]))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"
    assert f"classifying {SHOW_SERVER}" in result.stderr
    assert "upstream Rook in rook-ceph: CephCluster: rook-ceph" in result.stderr
    assert "verdict: upstream Rook present in: rook-ceph" in result.stderr


def test_classify_reports_no_upstream_rook_on_an_empty_cluster(tmp_path):
    result = _classify(_cluster(tmp_path, [], []))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "verdict: no upstream Rook" in result.stderr


def test_classify_treats_missing_rook_crds_as_no_upstream_rook(tmp_path):
    write_jq_proxy(tmp_path)
    write_cluster_oc(tmp_path, errors={"cephclusters.ceph.rook.io": NO_TYPE})

    result = _classify(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "verdict: no upstream Rook" in result.stderr


def test_classify_counts_an_operator_without_a_ceph_cluster(tmp_path):
    result = _classify(_cluster(tmp_path, [], [rook_operator()]))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"
    assert "CephCluster: none" in result.stderr


def test_classify_accepts_an_operator_watching_another_namespace(tmp_path):
    # Rook's operator watches all namespaces by default.
    result = _classify(_cluster(tmp_path, [ceph_cluster("b", "storage-b")], [rook_operator("rook-ceph")]))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph storage-b\n"
    assert "upstream Rook in rook-ceph: CephCluster: none" in result.stderr
    assert "upstream Rook in storage-b: CephCluster: b" in result.stderr


def test_classify_reports_none_with_residue_for_odf_signalled_clusters_only(tmp_path):
    clusters = [
        ceph_cluster("ocs-storagecluster-cephcluster", "openshift-storage"),
        ceph_cluster(
            "ocs-storagecluster-cephcluster",
            "ocs-elsewhere",
            ownerReferences=[{"kind": "StorageCluster", "name": "ocs-storagecluster"}],
        ),
        ceph_cluster("ocs-storagecluster-cephcluster", "openshift-storage-old", deletionTimestamp=OLD),
    ]
    odf_operator = rook_operator("openshift-storage", {"olm.owner": "rook-ceph-operator.v4.20.17-rhodf"})
    # ODF's own leftovers in openshift-storage are not a foreign Ceph CSI
    odf_csi = {
        "drivers.csi.ceph.io": [{"kind": "Driver", "metadata": meta("openshift-storage.rbd.csi.ceph.com", "openshift-storage")}],
        "csidrivers": [{"metadata": meta("openshift-storage.rbd.csi.ceph.com")}],
        "pv": [{"metadata": meta("pvc-1"), "spec": {"csi": {"driver": "openshift-storage.rbd.csi.ceph.com"}}}],
    }

    result = _classify(_cluster(tmp_path, clusters, [odf_operator], extra=odf_csi))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "residue CephCluster openshift-storage/ocs-storagecluster-cephcluster: in openshift-storage" in result.stderr
    assert "residue CephCluster ocs-elsewhere/ocs-storagecluster-cephcluster: owned by a StorageCluster" in result.stderr
    assert (
        "residue CephCluster openshift-storage-old/ocs-storagecluster-cephcluster: carries the ODF CephCluster name"
        in result.stderr
    )
    assert "verdict: no upstream Rook" in result.stderr


def test_classify_keeps_a_deleting_cluster_residue_while_its_operator_runs(tmp_path):
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("old", "rook-ceph", deletionTimestamp=OLD)], [rook_operator()])
    )

    assert result.returncode == 0, result.stderr
    assert "residue CephCluster rook-ceph/old: being deleted" in result.stderr


def test_classify_refuses_a_deleting_non_odf_cluster_without_any_operator(tmp_path):
    result = _classify(_cluster(tmp_path, [ceph_cluster("old", "rook-ceph", deletionTimestamp=OLD)], []))

    _assert_unknown(result, "unknown owner of rook-ceph/old: no non-OLM rook-ceph-operator Deployment")


@pytest.mark.parametrize(
    ("extra", "named"),
    [
        (
            {"drivers.csi.ceph.io": [{"kind": "Driver", "metadata": meta("rook-ceph.rbd.csi.ceph.com", "rook-ceph")}]},
            "unknown owner of csi.ceph.io Driver rook-ceph/rook-ceph.rbd.csi.ceph.com",
        ),
        (
            {"csidrivers": [{"metadata": meta("rook-ceph.rbd.csi.ceph.com")}]},
            "unknown owner of CSIDriver rook-ceph.rbd.csi.ceph.com",
        ),
        (
            {"pv": [{"metadata": meta("pvc-2"), "spec": {"csi": {"driver": "rook-ceph.cephfs.csi.ceph.com"}}}]},
            "unknown owner of PV pvc-2: volume of non-ODF Ceph CSI driver rook-ceph.cephfs.csi.ceph.com",
        ),
    ],
    ids=["csi-driver-object", "csidriver", "pv"],
)
def test_classify_refuses_a_ceph_csi_that_outlived_its_operator(tmp_path, extra, named):
    # No operator, no CephCluster, but a Ceph CSI that may still serve mounted PVs:
    # sweeping drivers.csi.ceph.io would take its deployments away.
    result = _classify(_cluster(tmp_path, [], [], extra=extra))

    _assert_unknown(result, named)


def test_classify_accepts_a_ceph_csi_run_by_an_upstream_operator(tmp_path):
    extra = {
        "drivers.csi.ceph.io": [{"kind": "Driver", "metadata": meta("rook-ceph.rbd.csi.ceph.com", "rook-ceph")}],
        "csidrivers": [{"metadata": meta("rook-ceph.rbd.csi.ceph.com")}],
    }

    result = _classify(_cluster(tmp_path, [], [rook_operator()], extra=extra))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"


@pytest.mark.parametrize(
    "operator",
    [
        rook_operator(labels={"olm.owner": "rook-ceph-operator.v1.20.5"}),
        rook_operator(labels={"operators.coreos.com/rook-ceph.rook-ceph": ""}),
    ],
    ids=["olm-owner", "olm-package-label"],
)
def test_classify_refuses_an_olm_installed_operator(tmp_path, operator):
    # A community Rook bundle and ODF's own operator look alike here.
    result = _classify(_cluster(tmp_path, [], [operator]))

    _assert_unknown(result, "unknown owner of rook-ceph/rook-ceph-operator: Deployment installed by OLM")


@pytest.mark.parametrize(
    "deployments",
    [
        [],
        [{"kind": "Deployment", "metadata": {"name": "rook-ceph-operator-custom", "namespace": "rook-ceph", "labels": {}}}],
        [rook_operator(deletionTimestamp=OLD)],
    ],
    ids=["absent", "renamed", "deleting"],
)
def test_classify_refuses_a_ceph_cluster_without_a_known_operator(tmp_path, deployments):
    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], deployments))

    _assert_unknown(
        result,
        "unknown owner of rook-ceph/rook-ceph: no non-OLM rook-ceph-operator Deployment",
        "ownership of rook-ceph/rook-ceph could not be classified",
    )


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
        ("cephclusters.ceph.rook.io", CONTEXT_ERROR),
        ("deployments", CONTEXT_ERROR),
        # the CRD may be missing; the Deployment kind never is
        ("deployments", NO_TYPE),
        ("deployments", "Error from server (NotFound): the server could not find the requested resource"),
        # only "no such resource type" means "no CephCluster CRD"
        ("cephclusters.ceph.rook.io", "Error from server (NotFound): the server could not find the requested resource"),
    ],
    ids=["clusters-forbidden", "deployments-forbidden", "clusters-context", "deployments-context",
         "deployments-no-type", "deployments-notfound", "clusters-notfound"],
)
def test_classify_stops_on_a_lookup_error(tmp_path, resource, message):
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], errors={resource: message})
    )

    _assert_unknown(result, message)


def test_classify_stops_when_the_cluster_cannot_be_reached(tmp_path):
    result = _classify(_cluster(tmp_path, [], [], errors={"whoami": CONTEXT_ERROR}))

    _assert_unknown(result, "cannot reach the cluster", CONTEXT_ERROR)


def test_classify_stops_when_the_server_url_cannot_be_read(tmp_path):
    result = _classify(_cluster(tmp_path, [], [], errors={"show-server": "error: You must be logged in to the server (Unauthorized)"}))

    _assert_unknown(result, "cannot read the API server URL", "error: You must be logged in to the server (Unauthorized)")


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


def test_classify_forwards_context_and_rejects_unknown_arguments(tmp_path):
    log = tmp_path / "argv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_jq_proxy(bin_dir)
    write_cluster_oc(bin_dir, log=log)

    result = _classify(bin_dir, "--context", "target")

    assert result.returncode == 0, result.stderr
    assert "(context: target)" in result.stderr
    assert all('"--context=target"' in line for line in log.read_text(encoding="utf-8").splitlines())

    bad = _classify(bin_dir, "--bogus")
    assert bad.returncode == 2
    assert "unknown argument: --bogus" in bad.stderr
