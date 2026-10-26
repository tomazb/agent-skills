"""Reproduce the CSI operator's live ClientProfile cleanup dependency."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_runbook_functions import GROUPS, OPERATOR, _run, meta


def test_profiles_finalize_before_their_connection_is_deleted(tmp_path):
    kinds = ["cephconnections", "operatorconfigs", "drivers", "clientprofiles",
             "clientprofilemappings"]
    resources = [kind + ".csi.ceph.io" for kind in kinds]
    groups = {**GROUPS, "csi.ceph.io": [[kind, True] for kind in resources]}
    objects = {**OPERATOR, **{kind: [{"metadata": meta("rook-ceph", "rook-ceph",
               finalizers=["csi.ceph.com/cleanup"])}] for kind in resources}}
    # Driver names encode the driver prefix for the ownership classifier.
    objects["drivers.csi.ceph.io"][0]["metadata"]["name"] = "rook-ceph.rbd.csi.ceph.com"
    result, mutations = _run(tmp_path, "rook_delete_operator", objects=objects,
                             groups=groups, csi_dependencies=True)
    assert "rc=0" in result.stdout, result.stdout + result.stderr
    assert mutations[-1] == "delete namespace rook-ceph --ignore-not-found --wait=false"
    calls = [json.loads(line) for line in (tmp_path / "argv.log").read_text().splitlines()]
    profile_delete = calls.index(["-n", "rook-ceph", "delete", "clientprofiles.csi.ceph.io",
                                 "--all", "--ignore-not-found", "--wait=false"])
    connection_delete = calls.index(["-n", "rook-ceph", "delete", "cephconnections.csi.ceph.io",
                                    "--all", "--ignore-not-found", "--wait=false"])
    assert ["-n", "rook-ceph", "get", "clientprofiles.csi.ceph.io", "-o", "name"] in calls[profile_delete:connection_delete]


def test_unknown_csi_resource_refuses_before_deleting_anything(tmp_path):
    groups = {**GROUPS, "csi.ceph.io": [["futureprofiles.csi.ceph.io", True]]}
    result, mutations = _run(tmp_path, "rook_delete_operator", objects=OPERATOR, groups=groups)
    assert "rc=1" in result.stdout
    assert "unverified CSI deletion dependency" in result.stderr
    assert mutations == []
