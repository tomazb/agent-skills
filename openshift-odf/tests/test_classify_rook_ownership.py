from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cluster_fake import (  # noqa: E402
    OLD,
    ceph_cluster,
    rook_operator,
    run_script,
    write_cluster_oc,
    write_jq_proxy,
    write_oc,
)


def _classify(bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_script("classify_rook_ownership.sh", bin_dir, *args)


def _cluster(tmp_path: Path, clusters: list, deployments: list, **kwargs) -> Path:
    write_jq_proxy(tmp_path)
    write_cluster_oc(
        tmp_path,
        objects={"cephclusters.ceph.rook.io": clusters, "deployments": deployments},
        **kwargs,
    )
    return tmp_path


def test_classify_reports_upstream_rook(tmp_path):
    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()]))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"
    assert "upstream Rook in rook-ceph: non-OLM rook-ceph-operator Deployment, CephCluster: rook-ceph" in result.stderr
    assert "verdict: upstream Rook present in: rook-ceph" in result.stderr


def test_classify_reports_no_upstream_rook_on_an_empty_cluster(tmp_path):
    result = _classify(_cluster(tmp_path, [], []))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "verdict: no upstream Rook" in result.stderr


def test_classify_treats_missing_rook_crds_as_no_upstream_rook(tmp_path):
    write_jq_proxy(tmp_path)
    write_cluster_oc(tmp_path, unserved=("cephclusters.ceph.rook.io",))

    result = _classify(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "verdict: no upstream Rook" in result.stderr


def test_classify_counts_an_operator_without_a_ceph_cluster(tmp_path):
    result = _classify(_cluster(tmp_path, [], [rook_operator()]))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"
    assert "CephCluster: none" in result.stderr


def test_classify_does_not_count_odf_in_openshift_storage(tmp_path):
    result = _classify(
        _cluster(
            tmp_path,
            [ceph_cluster("ocs-storagecluster-cephcluster", "openshift-storage")],
            [rook_operator("openshift-storage", {"olm.owner": "rook-ceph-operator.v4.20.17-rhodf"})],
        )
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "residue CephCluster openshift-storage/ocs-storagecluster-cephcluster: in openshift-storage" in result.stderr
    assert "verdict: no upstream Rook" in result.stderr


def test_classify_does_not_count_a_storagecluster_owned_ceph_cluster_elsewhere(tmp_path):
    owned = ceph_cluster(
        "ocs-storagecluster-cephcluster",
        "ocs-elsewhere",
        ownerReferences=[{"kind": "StorageCluster", "name": "ocs-storagecluster"}],
    )

    result = _classify(_cluster(tmp_path, [owned], []))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert "residue CephCluster ocs-elsewhere/ocs-storagecluster-cephcluster: owned by a StorageCluster" in result.stderr


@pytest.mark.parametrize(
    "operator",
    [
        rook_operator(labels={"olm.owner": "rook-ceph-operator.v1.20.5"}),
        rook_operator(deletionTimestamp=OLD),
    ],
    ids=["olm-installed", "deleting"],
)
def test_classify_ignores_an_olm_or_deleting_operator(tmp_path, operator):
    result = _classify(_cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [operator]))

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert (
        "residue CephCluster rook-ceph/rook-ceph: no upstream rook-ceph-operator Deployment in its namespace"
        in result.stderr
    )


def test_classify_reads_json_despite_stderr_noise(tmp_path):
    result = _classify(
        _cluster(tmp_path, [ceph_cluster("rook-ceph", "rook-ceph")], [rook_operator()], noise=True)
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rook-ceph\n"


@pytest.mark.parametrize("resource", ["cephclusters.ceph.rook.io", "deployments"])
def test_classify_stops_on_an_oc_error(tmp_path, resource):
    result = _classify(
        _cluster(
            tmp_path,
            [ceph_cluster("rook-ceph", "rook-ceph")],
            [rook_operator()],
            errors={resource: 'Error from server (Forbidden): cannot list resource'},
        )
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "verdict: unknown" in result.stderr
    assert "Forbidden" in result.stderr


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
        sys.stdout.write({output!r})
        raise SystemExit(0)
        """,
    )

    result = _classify(tmp_path)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "verdict: unknown" in result.stderr


def test_classify_stops_without_jq(tmp_path):
    write_cluster_oc(tmp_path)

    result = _classify(tmp_path)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "verdict: unknown - jq CLI is required but not installed" in result.stderr


def test_classify_forwards_context_and_rejects_unknown_arguments(tmp_path):
    log = tmp_path / "argv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_jq_proxy(bin_dir)
    write_cluster_oc(bin_dir, log=log)

    result = _classify(bin_dir, "--context", "target")

    assert result.returncode == 0, result.stderr
    assert all('"--context=target"' in line for line in log.read_text(encoding="utf-8").splitlines())

    bad = _classify(bin_dir, "--bogus")
    assert bad.returncode == 2
    assert "unknown argument: --bogus" in bad.stderr
