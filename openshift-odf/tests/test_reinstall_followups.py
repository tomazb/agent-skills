"""ODF-specific regressions for the findings tracked in issue 38."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_runbook_functions import _run, GROUPS, UPSTREAM
from cluster_fake import meta

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_reinstall_defaults_to_metadata_reset():
    result = subprocess.run([sys.executable, str(SCRIPTS / "plan_osd_disk_prep.py")],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["method"] == "bluestore-metadata-reset"
    assert "local-storage-disks.md" in data["runbook"]


def test_sanitization_requires_explicit_intent():
    result = subprocess.run([sys.executable, str(SCRIPTS / "plan_osd_disk_prep.py"), "--sanicap", "2"],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "--intent sanitize" in result.stderr


def test_csi_profiles_finalize_before_their_connection_is_removed(tmp_path):
    kinds = ["cephconnections", "drivers", "operatorconfigs", "clientprofiles", "clientprofilemappings"]
    resources = [k + ".csi.ceph.io" for k in kinds]
    groups = {**GROUPS, "csi.ceph.io": [[k, True] for k in resources]}
    objects = {k: [{"metadata": meta("odf", "openshift-storage", finalizers=["csi.ceph.com/cleanup"])}] for k in resources}
    objects["deployments"] = [{"metadata": meta("ceph-csi-controller-manager", "openshift-storage"),
        "spec": {"replicas": 1}, "status": {"availableReplicas": 1}}]
    result, deletes = _run(tmp_path, "odf_delete_csi_resources", objects=objects, groups=groups,
                           csi_dependencies=True)
    assert "rc=0" in result.stdout, result.stdout + result.stderr
    assert len(deletes) == len(resources)
    assert deletes.index("-n openshift-storage delete clientprofiles.csi.ceph.io --all --ignore-not-found --wait=false") < deletes.index(
        "-n openshift-storage delete cephconnections.csi.ceph.io --all --ignore-not-found --wait=false")
    assert not any("delete deployment" in d or "delete namespace" in d for d in deletes)


def test_csi_teardown_stops_if_temporary_sno_scale_down_was_not_restored(tmp_path):
    objects = {"drivers.csi.ceph.io": [{"metadata": meta("odf", "openshift-storage")}],
               "deployments": [{"metadata": meta("ceph-csi-controller-manager", "openshift-storage"),
                                  "spec": {"replicas": 0}, "status": {"availableReplicas": 0}}]}
    result, deletes = _run(tmp_path, "odf_delete_csi_resources", objects=objects)
    assert "rc=1" in result.stdout
    assert "CSI controller" in result.stderr
    assert deletes == []


def test_live_storagecluster_prevents_manual_csi_cleanup(tmp_path):
    result, deletes = _run(tmp_path, "odf_delete_csi_resources", objects={
        "storageclusters.ocs.openshift.io": [{"metadata": meta("ocs-storagecluster", "openshift-storage")}]})
    assert "rc=1" in result.stdout
    assert deletes == []


def test_manager_workaround_never_authorizes_direct_odf_cephcluster_patches():
    text = (SCRIPTS.parent / "references" / "validation-hardening.md").read_text()
    assert "node_proxy_fullreport" in text
    assert "vendor-supported" in text
    assert "ceph mgr module enable rook" not in text


def test_crd_sweep_refuses_shared_api_owned_by_another_olm_operator(tmp_path):
    result, deletes = _run(tmp_path, "odf_crd_sweep", objects={"crd": [{
        "metadata": meta("objectbucketclaims.objectbucket.io", uid="recorded", labels={
            "operators.coreos.com/lvms-operator.openshift-storage": ""}),
        "spec": {"group": "objectbucket.io"}}]})
    assert "rc=1" in result.stdout
    assert "non-ODF OLM" in result.stderr
    assert not any("delete crd objectbucketclaims.objectbucket.io" in d for d in deletes)


def test_incomplete_olm_owner_is_protected_from_crd_deletion(tmp_path):
    result, deletes = _run(tmp_path, "odf_crd_sweep", objects={"crd": [{
        "metadata": meta("objectbucketclaims.objectbucket.io", labels={"olm.owner": "foreign-operator.v1.0.0"}),
        "spec": {"group": "objectbucket.io"}}]})
    assert "rc=1" in result.stdout
    assert not any("delete crd objectbucketclaims.objectbucket.io" in d for d in deletes)


def test_foreign_olm_api_guard_also_applies_to_bucket_cleanup_next_to_rook(tmp_path):
    result, deletes = _run(tmp_path, "odf_delete_odf_buckets", objects={**UPSTREAM, "crd": [{
        "metadata": meta("objectbucketclaims.objectbucket.io", labels={"operators.coreos.com/lvms-operator.platform": ""}),
        "spec": {"group": "objectbucket.io"}}]})
    assert "rc=1" in result.stdout
    assert deletes == []


def test_shared_ownership_inventory_must_be_an_array(tmp_path):
    result, deletes = _run(tmp_path, '''
oc() {
  if [ "$1 $2" = "get crd" ]; then
    echo '{"items":{}}'
  else
    command oc "$@"
  fi
}
odf_shared_olm_guard objectbucket.io
''')
    assert "rc=1" in result.stdout
    assert "ownership unverified" in result.stderr
    assert deletes == []
