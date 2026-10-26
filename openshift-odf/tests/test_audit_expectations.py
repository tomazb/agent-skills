import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cluster_fake import SHOW_SERVER, meta, write_cluster_oc, write_jq_proxy, run_script


def _audit(tmp_path, objects=None, groups=None, errors=None, env=None, default_sc=True):
    write_jq_proxy(tmp_path)
    write_cluster_oc(tmp_path, objects=objects, groups=groups, errors=errors,
                     storage_classes=None if default_sc else [])
    return run_script("post_uninstall_audit.sh", tmp_path, extra_env=env)


def _clean(result):
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARN:" not in result.stdout and "FAIL:" not in result.stdout


SHARED_GROUPS = {"objectbucket.io": [["objectbucketclaims.objectbucket.io", True], ["objectbuckets.objectbucket.io", False]]}

KINDS = ["objectbucketclaims.objectbucket.io", "objectbuckets.objectbucket.io"]


def retention(tmp_path, **changes):
    document = {"apiServer": SHOW_SERVER,
                "crds": [{"name": kind, "uid": "recorded-" + str(i), "ownerPackage": "lvms-operator",
                          "ownerNamespace": "platform", "ownerCSV": "lvms-operator.v1.0.0"} for i, kind in enumerate(KINDS)]}
    document.update(changes)
    path = tmp_path / "retained.json"
    path.write_text(json.dumps(document))
    objects = {"crd": [{"metadata": meta(kind, uid="recorded-" + str(i), labels={
        "operators.coreos.com/lvms-operator.platform": ""}), "spec": {"group": "objectbucket.io"}}
        for i, kind in enumerate(KINDS)]}
    objects["subscription"] = [{"metadata": meta("lvms", "platform"), "spec": {"name": "lvms-operator"},
                                "status": {"installedCSV": "lvms-operator.v1.0.0"}}]
    objects["csv"] = [{"metadata": meta("lvms-operator.v1.0.0", "platform"), "status": {"phase": "Succeeded"}}]
    return path, objects


def test_retained_objectbucket_apis_require_matching_identity_and_ownership(tmp_path):
    path, objects = retention(tmp_path)
    result = _audit(tmp_path, objects=objects, groups={"objectbucket.io": SHARED_GROUPS["objectbucket.io"]},
                    env={"ODF_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    _clean(result)
    assert "retained: verified OLM-owned CRD inventory" in result.stdout


def test_large_olm_owner_lists_use_stdin_instead_of_large_argv(tmp_path):
    path, objects = retention(tmp_path)
    # Larger than Linux MAX_ARG_STRLEN (128 KiB) for either --argjson.
    objects["subscription"][0]["metadata"]["annotations"] = {"large": "s" * 160_000}
    objects["csv"][0]["metadata"]["annotations"] = {"large": "c" * 160_000}
    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS,
                    env={"ODF_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    _clean(result)


@pytest.mark.parametrize("failure", ["server", "uid", "owner", "owner-empty", "missing", "instance", "access", "malformed", "discovery"])
def test_retention_expectations_fail_closed(tmp_path, failure):
    path, objects = retention(tmp_path)
    errors = {}
    if failure == "server":
        d = json.loads(path.read_text()); d["apiServer"] = "https://other.example.com:6443"; path.write_text(json.dumps(d))
    if failure == "uid":
        objects["crd"][0]["metadata"]["uid"] = "replacement"
    if failure == "owner":
        objects["crd"][0]["metadata"]["labels"] = {}
    if failure == "owner-empty":
        objects["crd"][0]["metadata"]["labels"] = {"olm.owner": "", "olm.owner.namespace": ""}
    if failure == "missing":
        objects["crd"] = objects["crd"][1:]
    if failure == "instance":
        objects[KINDS[0]] = [{"metadata": meta("orphan", "team")}]
    if failure == "access":
        errors["crd"] = "Forbidden"
    if failure == "malformed":
        path.write_text("{}")
    groups = {"objectbucket.io": SHARED_GROUPS["objectbucket.io"][:1] if failure == "discovery" else SHARED_GROUPS["objectbucket.io"]}
    result = _audit(tmp_path, objects=objects, groups=groups,
                    env={"ODF_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)}, errors=errors)
    assert result.returncode != 0, result.stdout


def test_explicit_post_uninstall_default_does_not_overwrite_prior_policy(tmp_path):
    result = _audit(tmp_path, default_sc=False,
                    env={"PRIOR_DEFAULT_STORAGE_CLASS": "ocs-storagecluster-ceph-rbd", "EXPECTED_DEFAULT_STORAGE_CLASS": ""})
    _clean(result)
    assert "matching the expected post-uninstall policy" in result.stdout


def test_wrong_explicit_default_remains_a_failure(tmp_path):
    result = _audit(tmp_path, env={"EXPECTED_DEFAULT_STORAGE_CLASS": "different-default"})
    assert result.returncode == 1
    assert "expected post-uninstall policy" in result.stdout


def test_inventory_cannot_excuse_crds_labelled_only_for_odf(tmp_path):
    path, objects = retention(tmp_path)
    for crd in objects["crd"]:
        crd["metadata"]["labels"] = {"operators.coreos.com/ocs-operator.openshift-storage": ""}
    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS,
                    env={"ODF_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    assert result.returncode != 0


def test_unknown_olm_package_cannot_be_assumed_non_odf(tmp_path):
    path, objects = retention(tmp_path)
    for crd in objects["crd"]:
        crd["metadata"]["labels"] = {"operators.coreos.com/odf-future-operator.openshift-storage": ""}
    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS,
                    env={"ODF_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    assert result.returncode != 0


@pytest.mark.parametrize("kind", ["subscription", "csv"])
def test_retention_requires_the_recorded_live_operator(kind, tmp_path):
    path, objects = retention(tmp_path)
    objects[kind] = []
    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS,
                    env={"ODF_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    assert result.returncode != 0


@pytest.mark.parametrize("items", ["{}", "null"])
def test_malformed_retained_api_list_cannot_look_empty(tmp_path, monkeypatch, items):
    original = write_cluster_oc
    def malformed(*args, **kwargs):
        original(*args, **kwargs)
        oc = args[0] / "oc"
        source = oc.read_text()
        source = source.replace('print(json.dumps({"items": items}))',
            'print(json.dumps({"items": ' + items.replace("null", "None") + '} if res in '
            + repr(KINDS) + ' else {"items": items}))')
        oc.write_text(source)
    monkeypatch.setitem(_audit.__globals__, "write_cluster_oc", malformed)
    path, objects = retention(tmp_path)
    result = _audit(tmp_path, objects=objects, groups={"objectbucket.io": SHARED_GROUPS["objectbucket.io"]},
                    env={"ODF_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    assert result.returncode != 0, result.stdout
