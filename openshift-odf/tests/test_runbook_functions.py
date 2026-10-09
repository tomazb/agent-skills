"""Run the shell functions of references/maintenance-uninstall.md against the fake oc.

The functions are taken verbatim from the runbook, so a change there is what the
tests run.
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

from cluster_fake import (  # noqa: E402
    SCRIPTS,
    ceph_cluster,
    meta,
    rook_operator,
    write_cluster_oc,
    write_jq_proxy,
)

RUNBOOK = Path(__file__).resolve().parents[1] / "references" / "maintenance-uninstall.md"
FUNCTIONS = dict(
    (m.group(1), m.group(0))
    for m in re.finditer(r"^(odf_[a-z_]+)\(\) \{\n.*?^\}$", RUNBOOK.read_text(encoding="utf-8"), re.M | re.S)
)

GROUPS = {
    "ocs.openshift.io": [["storageclusters.ocs.openshift.io", True]],
    # a group whose name is a suffix of another group's name
    "noobaa.io": [["noobaas.noobaa.io", True]],
    "postgresql.cnpg.noobaa.io": [["clusters.postgresql.cnpg.noobaa.io", True]],
    "ceph.rook.io": [["cephclusters.ceph.rook.io", True]],
    "csi.ceph.io": [["drivers.csi.ceph.io", True]],
    "objectbucket.io": [
        ["objectbucketclaims.objectbucket.io", True],
        ["objectbuckets.objectbucket.io", False],
    ],
    "local.storage.openshift.io": [["localvolumes.local.storage.openshift.io", True]],
    "groupsnapshot.storage.openshift.io": [["volumegroupsnapshots.groupsnapshot.storage.openshift.io", True]],
}
CRDS = [
    {"metadata": meta(kind), "spec": {"group": group}}
    for group, kinds in GROUPS.items()
    for kind, _ in kinds
]
UPSTREAM = {"deployments": [rook_operator()], "cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")]}
UNKNOWN_ERRORS = {"deployments": "Error from server (Forbidden): cannot list deployments"}
SHARED = ("ceph.rook.io", "csi.ceph.io", "objectbucket.io")


def test_runbook_defines_the_tested_functions():
    assert {
        "odf_classify",
        "odf_remove_rook_sccs",
        "odf_list_shared_instances",
        "odf_delete_odf_buckets",
        "odf_crd_sweep",
        "odf_find_odf_labelled",
    } <= set(FUNCTIONS)


def _run(
    tmp_path: Path, call: str, objects=None, errors=None, env=None, source_common=True, omit=(), blocking=False,
    tools=("bash", "grep"),
):
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    for name in ("classify_rook_ownership.sh", "odf_common.sh"):
        shutil.copy(SCRIPTS / name, skill / "scripts" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_jq_proxy(bin_dir)
    for tool in tools:
        found = shutil.which(tool)
        if found is None:
            pytest.skip(f"{tool} is required for the runbook function tests")
        (bin_dir / tool).symlink_to(found)
    log = tmp_path / "argv.log"
    world = {"objects": {"crd": CRDS, **(objects or {})}, "groups": GROUPS, "errors": errors or {}}
    write_cluster_oc(bin_dir, log=log, blocking_deletes=blocking, **world)
    script = "\n".join(
        [
            ". scripts/odf_common.sh" if source_common else "",
            *(body for name, body in FUNCTIONS.items() if name not in omit),
            call,
            'echo "rc=$?"',
        ]
    )
    result = subprocess.run(
        [str(bin_dir / "bash"), "-c", script],
        cwd=skill,
        env={"PATH": str(bin_dir), "ODF_DELETE_WAIT": "0", **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    deletes = [" ".join(c) for c in calls if "delete" in c]
    return result, deletes


def test_sweep_refuses_and_deletes_nothing_when_classification_fails(tmp_path):
    result, deletes = _run(tmp_path, "odf_crd_sweep", objects=UPSTREAM, errors=UNKNOWN_ERRORS)

    assert "rc=1" in result.stdout
    assert "nothing deleted" in result.stderr
    assert deletes == []


def test_sweep_refreshes_a_stale_classification_from_an_earlier_run(tmp_path):
    # The shell still says "classified, no upstream Rook" from an earlier cluster or
    # context; the classification for the current one fails.
    result, deletes = _run(
        tmp_path,
        "odf_crd_sweep",
        objects=UPSTREAM,
        errors=UNKNOWN_ERRORS,
        env={"ODF_OWNERSHIP_CLASSIFIED": "yes", "ROOK_NAMESPACES": ""},
    )

    assert "rc=1" in result.stdout
    assert deletes == []


def test_sweep_never_touches_the_shared_groups_next_to_upstream_rook(tmp_path):
    result, deletes = _run(tmp_path, "odf_crd_sweep", objects=UPSTREAM)

    assert "rc=0" in result.stdout, result.stderr
    assert "delete storageclusters.ocs.openshift.io --all -A --ignore-not-found --wait=false" in deletes
    assert "delete crd storageclusters.ocs.openshift.io --wait=false" in deletes
    for group in SHARED:
        assert not [d for d in deletes if group in d], deletes


def test_sweep_without_upstream_rook_deletes_odf_groups_only(tmp_path):
    result, deletes = _run(tmp_path, "odf_crd_sweep")

    assert "rc=0" in result.stdout, result.stderr
    assert "delete cephclusters.ceph.rook.io --all -A --ignore-not-found --wait=false" in deletes
    assert "delete crd cephclusters.ceph.rook.io --wait=false" in deletes
    assert "delete crd objectbucketclaims.objectbucket.io objectbuckets.objectbucket.io --wait=false" in deletes
    assert not [d for d in deletes if "local.storage" in d or "groupsnapshot" in d], deletes


def test_sweep_deletes_only_odf_bucket_claims_and_keeps_the_crds_for_others(tmp_path):
    objects = {
        "sc": [{"metadata": meta("standalone-buckets"), "provisioner": "noobaa.io/obc"}],
        "objectbucketclaims.objectbucket.io": [
            {"metadata": meta("odf-claim", "app"), "spec": {"storageClassName": "openshift-storage.noobaa.io"}},
            {"metadata": meta("other-claim", "app"), "spec": {"storageClassName": "standalone-buckets"}},
        ],
        "objectbuckets.objectbucket.io": [
            {"metadata": meta("obc-app-odf-claim"), "spec": {"storageClassName": "openshift-storage.noobaa.io"}},
        ],
    }

    result, deletes = _run(tmp_path, "odf_crd_sweep", objects=objects)

    assert "-n app delete objectbucketclaims.objectbucket.io odf-claim --wait=false" in deletes
    assert "delete objectbuckets.objectbucket.io obc-app-odf-claim --wait=false" in deletes
    assert not [d for d in deletes if "other-claim" in d]
    assert not [d for d in deletes if d.startswith("delete crd objectbucket")], deletes
    assert "keeping objectbucketclaims.objectbucket.io app/other-claim" in result.stderr


@pytest.mark.parametrize(
    ("objects", "errors", "deleted", "rc"),
    [(UPSTREAM, None, False, "rc=0"), ({}, None, True, "rc=0"), (UPSTREAM, UNKNOWN_ERRORS, False, "rc=1")],
    ids=["upstream", "none", "unknown"],
)
def test_rook_sccs_are_removed_only_on_a_fresh_no_rook_verdict(tmp_path, objects, errors, deleted, rc):
    result, deletes = _run(
        tmp_path,
        "odf_remove_rook_sccs",
        objects=objects,
        errors=errors,
        env={"ODF_OWNERSHIP_CLASSIFIED": "yes", "ROOK_NAMESPACES": ""},
    )

    assert rc in result.stdout, result.stderr
    assert (deletes == ["delete scc rook-ceph rook-ceph-csi --ignore-not-found"]) is deleted
    if not deleted:
        assert deletes == []


def test_shared_instances_are_listed_in_every_namespace_outside_rook(tmp_path):
    objects = dict(UPSTREAM)
    objects["drivers.csi.ceph.io"] = [
        {"kind": "Driver", "metadata": meta("rook-ceph.rbd.csi.ceph.com", "rook-ceph")},
        {"kind": "Driver", "metadata": meta("openshift-storage.rbd.csi.ceph.com", "lvms")},
    ]
    objects["objectbucketclaims.objectbucket.io"] = [{"kind": "ObjectBucketClaim", "metadata": meta("claim", "app")}]

    result, deletes = _run(tmp_path, "odf_list_shared_instances", objects=objects)

    assert "rc=0" in result.stdout, result.stderr
    assert "Driver lvms/openshift-storage.rbd.csi.ceph.com" in result.stdout
    assert "rook-ceph/rook-ceph.rbd.csi.ceph.com" not in result.stdout
    assert "claim" not in result.stdout
    assert deletes == []


def test_labelled_object_search_refuses_without_the_odf_patterns(tmp_path):
    objects = {"clusterroles": [{"kind": "ClusterRole", "metadata": meta("anything", labels={"olm.owner": "x.v1"})}]}

    result, _ = _run(tmp_path, "odf_find_odf_labelled", objects=objects, source_common=False)

    assert "rc=1" in result.stdout
    assert "ODF patterns not loaded" in result.stderr
    assert "anything" not in result.stdout


def test_labelled_object_search_finds_odf_labels_and_reports_unreadable_kinds(tmp_path):
    objects = {
        "clusterroles": [
            {"kind": "ClusterRole", "metadata": meta("odf-prometheus", labels={"olm.owner": "ocs-operator.v4.20.17-rhodf"})},
            {"kind": "ClusterRole", "metadata": meta("other", labels={"olm.owner": "lvms-operator.v4.20.0"})},
        ],
        "crd": [
            {
                "kind": "CustomResourceDefinition",
                "metadata": meta("recipes.ramendr.openshift.io", labels={"operators.coreos.com/recipe.elsewhere": ""}),
            }
        ],
    }

    result, _ = _run(
        tmp_path,
        "odf_find_odf_labelled",
        objects=objects,
        errors={"prometheusrules": 'error: the server doesn\'t have a resource type "prometheusrules"'},
    )

    assert "ClusterRole -/odf-prometheus" in result.stdout
    assert "CustomResourceDefinition -/recipes.ramendr.openshift.io" in result.stdout
    assert "other" not in result.stdout
    assert "could not check prometheusrules" in result.stderr
    assert "rc=1" in result.stdout


STALE_ENV = {"ODF_OWNERSHIP_CLASSIFIED": "yes", "ROOK_NAMESPACES": ""}


@pytest.mark.parametrize(
    "call",
    ["odf_crd_sweep", "odf_remove_rook_sccs", "odf_list_shared_instances", "odf_delete_odf_buckets"],
)
def test_gated_functions_refuse_when_odf_classify_is_undefined(tmp_path, call):
    # A new shell that inherited the flag but never defined odf_classify.
    objects = {
        "objectbucketclaims.objectbucket.io": [
            {"metadata": meta("odf-claim", "app"), "spec": {"storageClassName": "openshift-storage.noobaa.io"}}
        ]
    }

    result, deletes = _run(tmp_path, call, objects=objects, env=STALE_ENV, omit=("odf_classify",))

    assert "rc=1" in result.stdout
    assert deletes == []
    assert "odf-claim" not in result.stdout


def test_bucket_cleanup_called_alone_lists_classless_claims_next_to_upstream_rook(tmp_path):
    objects = dict(UPSTREAM)
    objects["sc"] = [{"metadata": meta("odf-buckets"), "provisioner": "openshift-storage.noobaa.io/obc"}]
    objects["objectbucketclaims.objectbucket.io"] = [
        {"metadata": meta("odf-claim", "app"), "spec": {"storageClassName": "odf-buckets"}},
        {"metadata": meta("classless-claim", "app"), "spec": {"storageClassName": "gone"}},
    ]

    result, deletes = _run(tmp_path, "odf_delete_odf_buckets", objects=objects)

    assert "-n app delete objectbucketclaims.objectbucket.io odf-claim --wait=false" in deletes
    assert not [d for d in deletes if "classless-claim" in d]
    assert "keeping objectbucketclaims.objectbucket.io app/classless-claim: its StorageClass is gone" in result.stderr
    # a kept claim means the objectbucket.io CRDs must stay; the status says so
    assert "rc=1" in result.stdout


def test_failed_classification_clears_an_inherited_flag(tmp_path):
    result, _ = _run(
        tmp_path,
        'odf_classify; echo "flag=${ODF_OWNERSHIP_CLASSIFIED:-}"',
        objects=UPSTREAM,
        errors=UNKNOWN_ERRORS,
        env=STALE_ENV,
    )

    assert "flag=\n" in result.stdout


def test_bucket_cleanup_called_alone_refuses_when_classification_fails(tmp_path):
    objects = {
        "objectbucketclaims.objectbucket.io": [
            {"metadata": meta("odf-claim", "app"), "spec": {"storageClassName": "openshift-storage.noobaa.io"}}
        ]
    }

    result, deletes = _run(tmp_path, "odf_delete_odf_buckets", objects=objects, errors=UNKNOWN_ERRORS, env=STALE_ENV)

    assert "rc=1" in result.stdout
    assert deletes == []


@pytest.mark.parametrize(
    ("objects", "group", "crd"),
    [
        (
            {
                "objectbucketclaims.objectbucket.io": [
                    {
                        "metadata": meta("held-claim", "app", finalizers=["objectbucket.io/finalizer"]),
                        "spec": {"storageClassName": "openshift-storage.noobaa.io"},
                    }
                ]
            },
            "objectbucket.io",
            "crd objectbucketclaims.objectbucket.io",
        ),
        (
            {"storageclusters.ocs.openshift.io": [{"metadata": meta("ocs-storagecluster", "openshift-storage", finalizers=["x"])}]},
            "ocs.openshift.io",
            "crd storageclusters.ocs.openshift.io",
        ),
    ],
    ids=["bucket-claim", "storagecluster"],
)
def test_sweep_keeps_a_groups_crds_while_an_instance_remains(tmp_path, objects, group, crd):
    # The fake never removes what it is asked to delete, like an object held by a
    # finalizer whose controller is gone.
    result, deletes = _run(tmp_path, "odf_crd_sweep", objects=objects)

    assert f"instances of {group} remain:" in result.stderr
    assert "Orphans After An Interrupted Uninstall" in result.stderr
    assert not [d for d in deletes if crd in d], deletes


def test_sweep_never_waits_on_finalizers_and_still_refuses_held_instances(tmp_path):
    # With blocking_deletes the fake fails any waiting delete of a finalizer-held
    # object, as a real oc would block on it forever after an interrupted uninstall.
    skill = tmp_path / "run"
    skill.mkdir()
    objects = {
        "storageclusters.ocs.openshift.io": [
            {"metadata": meta("ocs-storagecluster", "openshift-storage", finalizers=["storagecluster.ocs.openshift.io"])}
        ],
        "cephclusters.ceph.rook.io": [
            {"metadata": meta("ocs-storagecluster-cephcluster", "openshift-storage", finalizers=["cephcluster.ceph.rook.io"])}
        ],
    }
    result, deletes = _run(skill, "odf_crd_sweep", objects=objects, blocking=True)

    assert deletes, result.stderr
    assert all("--wait=false" in d for d in deletes), deletes
    assert "would block" not in result.stderr
    assert "instances of ocs.openshift.io remain:" in result.stderr
    assert "instances of ceph.rook.io remain:" in result.stderr
    assert "Orphans After An Interrupted Uninstall" in result.stderr
    assert not [d for d in deletes if d.startswith("delete crd storageclusters") or d.startswith("delete crd cephclusters")]


def test_sweep_selects_crds_by_exact_group_not_by_name_suffix(tmp_path):
    # "noobaa.io" is a suffix of "postgresql.cnpg.noobaa.io". The noobaa.io pass
    # must not take the CNPG CRDs, whose instance is still there.
    objects = {
        "clusters.postgresql.cnpg.noobaa.io": [
            {"metadata": meta("noobaa-db-pg-cluster", "openshift-storage", finalizers=["cnpg.io/cluster"])}
        ]
    }

    result, deletes = _run(tmp_path, "odf_crd_sweep", objects=objects)

    assert "delete crd noobaas.noobaa.io --wait=false" in deletes
    assert not [d for d in deletes if d.startswith("delete crd") and "postgresql.cnpg.noobaa.io" in d], deletes
    assert "instances of postgresql.cnpg.noobaa.io remain:" in result.stderr


def test_sweep_returns_nonzero_when_a_crd_delete_fails_and_still_tries_the_other_groups(tmp_path):
    result, deletes = _run(
        tmp_path, "odf_crd_sweep", errors={"delete crd": "Error from server (Forbidden): cannot delete crds"}
    )

    assert "rc=1" in result.stdout
    assert "CRD deletion failed for ocs.openshift.io" in result.stderr
    # it kept going: every ODF group was attempted
    assert [d for d in deletes if d.startswith("delete crd noobaas.noobaa.io")]
    assert [d for d in deletes if d.startswith("delete crd cephclusters.ceph.rook.io")]


def test_sweep_waits_a_bounded_time_for_instances_before_counting_them(tmp_path):
    log = tmp_path / "run" / "argv.log"
    objects = {
        "storageclusters.ocs.openshift.io": [
            {"metadata": meta("ocs-storagecluster", "openshift-storage", finalizers=["storagecluster.ocs.openshift.io"])}
        ]
    }

    result, _ = _run(tmp_path / "run", "odf_crd_sweep", objects=objects, env={"ODF_DELETE_WAIT": "3"},
                     tools=("bash", "grep", "sleep"))

    polls = [line for line in log.read_text(encoding="utf-8").splitlines()
             if '"get", "storageclusters.ocs.openshift.io", "-A", "-o", "name"' in line]
    assert len(polls) >= 2, polls
    assert "instances of ocs.openshift.io remain:" in result.stderr


def test_sweep_removes_odf_buckets_next_to_upstream_rook(tmp_path):
    objects = dict(UPSTREAM)
    objects["sc"] = [
        {"metadata": meta("odf-buckets"), "provisioner": "openshift-storage.noobaa.io/obc"},
        {"metadata": meta("rook-buckets"), "provisioner": "rook-ceph.ceph.rook.io/bucket"},
    ]
    objects["objectbucketclaims.objectbucket.io"] = [
        {"metadata": meta("odf-claim", "app"), "spec": {"storageClassName": "odf-buckets"}},
        {"metadata": meta("rook-claim", "app"), "spec": {"storageClassName": "rook-buckets"}},
    ]

    result, deletes = _run(tmp_path, "odf_crd_sweep", objects=objects)

    assert "-n app delete objectbucketclaims.objectbucket.io odf-claim --wait=false" in deletes
    assert not [d for d in deletes if "rook-claim" in d]
    assert not [d for d in deletes if d.startswith("delete crd objectbucket")]
    assert "keeping objectbucketclaims.objectbucket.io app/rook-claim" in result.stderr
