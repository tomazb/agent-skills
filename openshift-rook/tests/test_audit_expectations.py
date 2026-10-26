import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_post_uninstall_audit import SHARED_GROUPS, _audit, _clean
import test_post_uninstall_audit as audit_module
from rook_cluster_fake import SHOW_SERVER, meta

KINDS = ["objectbucketclaims.objectbucket.io", "objectbuckets.objectbucket.io"]


def retention(tmp_path, **changes):
    document = {"apiServer": SHOW_SERVER,
                "crds": [{"name": kind, "uid": "recorded-" + str(i)} for i, kind in enumerate(KINDS)]}
    document.update(changes)
    path = tmp_path / "retained.json"
    path.write_text(json.dumps(document))
    objects = {"crd": [{"metadata": meta(kind, uid="recorded-" + str(i), labels={
        "operators.coreos.com/platform-operator.platform": ""}), "spec": {"group": "objectbucket.io"}}
        for i, kind in enumerate(KINDS)]}
    return path, objects


def test_retained_objectbucket_apis_require_matching_identity_and_ownership(tmp_path):
    path, objects = retention(tmp_path)
    result = _audit(tmp_path, objects=objects, groups={"objectbucket.io": SHARED_GROUPS["objectbucket.io"]},
                    env={"ROOK_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    _clean(result)
    assert "retained: verified OLM-owned CRD inventory" in result.stdout


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
                    env={"ROOK_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)}, errors=errors)
    assert result.returncode != 0, result.stdout


def test_explicit_post_uninstall_default_does_not_overwrite_prior_policy(tmp_path):
    result = _audit(tmp_path, default_sc=False,
                    env={"PRIOR_DEFAULT_STORAGE_CLASS": "rook-ceph-block", "EXPECTED_DEFAULT_STORAGE_CLASS": ""})
    _clean(result)
    assert "matching the expected post-uninstall policy" in result.stdout


def test_wrong_explicit_default_remains_a_failure(tmp_path):
    result = _audit(tmp_path, env={"EXPECTED_DEFAULT_STORAGE_CLASS": "different-default"})
    assert result.returncode == 1
    assert "expected post-uninstall policy" in result.stdout


@pytest.mark.parametrize("items", ["{}", "null"])
def test_malformed_retained_api_list_cannot_look_empty(tmp_path, monkeypatch, items):
    original = audit_module.write_cluster_oc
    def malformed(*args, **kwargs):
        original(*args, **kwargs)
        oc = args[0] / "oc"
        source = oc.read_text()
        source = source.replace('print(json.dumps({"items": items}))',
            'print(json.dumps({"items": ' + items.replace("null", "None") + '} if res in '
            + repr(KINDS) + ' else {"items": items}))')
        oc.write_text(source)
    monkeypatch.setattr(audit_module, "write_cluster_oc", malformed)
    path, objects = retention(tmp_path)
    result = _audit(tmp_path, objects=objects, groups={"objectbucket.io": SHARED_GROUPS["objectbucket.io"]},
                    env={"ROOK_RETAINED_OBJECTBUCKET_CRDS_FILE": str(path)})
    assert result.returncode != 0, result.stdout
