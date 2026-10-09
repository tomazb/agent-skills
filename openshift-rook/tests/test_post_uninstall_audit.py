from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rook_cluster_fake import (  # noqa: E402
    FINALIZER_JSONPATH,
    OLD,
    ceph_cluster,
    merge,
    meta,
    recent,
    rook_operator,
    run_script,
    write_cluster_oc,
    write_jq_proxy,
    write_oc,
)

CONTEXT_ERROR = "Error in configuration: * context was not found for specified context: nope"
SHARED_GROUPS = {
    "ceph.rook.io": [["cephclusters.ceph.rook.io", True], ["cephblockpools.ceph.rook.io", True]],
    "csi.ceph.io": [["drivers.csi.ceph.io", True], ["clientprofiles.csi.ceph.io", True]],
    "objectbucket.io": [["objectbucketclaims.objectbucket.io", True], ["objectbuckets.objectbucket.io", False]],
}
SNAPSHOT_GROUP = {"snapshot.storage.k8s.io": [["volumesnapshotclasses", False]]}
ODF_PRESENT = {
    "subscriptions.operators.coreos.com": [
        {"metadata": meta("odf-operator", "openshift-storage"), "spec": {"name": "odf-operator"}}
    ],
    "clusterserviceversions.operators.coreos.com": [
        {"metadata": meta("ocs-operator.v4.20.17-rhodf", "openshift-storage")}
    ],
}
ODF_LABELS = {"olm.owner": "ocs-operator.v4.20.17-rhodf", "olm.owner.namespace": "openshift-storage"}


def _audit(tmp_path: Path, objects=None, groups=None, errors=None, args=(), env=None,
           **kwargs) -> subprocess.CompletedProcess[str]:
    write_jq_proxy(tmp_path)
    write_cluster_oc(tmp_path, objects=objects or {}, groups=groups or {}, errors=errors, **kwargs)
    return run_script("post_uninstall_audit.sh", tmp_path, *args, env=env)


def _ok(result, *lines: str) -> None:
    for line in lines:
        assert f"OK: {line}" in result.stdout, result.stdout


def _warn(result, *lines: str) -> None:
    assert result.returncode == 1, result.stdout
    for line in lines:
        assert line in result.stdout, result.stdout


def _clean(result) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARN:" not in result.stdout
    assert "FAIL:" not in result.stdout


def test_audit_passes_on_a_clean_cluster(tmp_path):
    result = _audit(tmp_path)

    _clean(result)
    _ok(
        result,
        "no upstream Rook operator or CephCluster runs",
        "no ODF present",
        "namespace rook-ceph absent",
        "no ceph.rook.io API resources found",
        "no csi.ceph.io API resources found",
        "no objectbucket.io API resources found",
        "no Rook StorageClasses found",
        "no Rook PVs found",
        "no Rook PVCs found",
        "no Rook VolumeAttachments found",
        "no Rook CSIDrivers found",
        "no node registers a Rook CSI driver",
        "no rook-ceph or rook-ceph-csi SCC found",
        "PriorityClass rook-ceph-default absent",
        "no dead Rook ClusterRoles or ClusterRoleBindings found",
        "no MachineConfigs named for Rook",
        "exactly one default StorageClass: platform-default",
    )
    assert "auditing https://api.cluster.example.com:6443" in result.stdout


def test_audit_fails_when_oc_is_missing(tmp_path):
    write_jq_proxy(tmp_path)

    result = run_script("post_uninstall_audit.sh", tmp_path)

    assert result.returncode == 1
    assert "FAIL: oc CLI is required but not installed" in result.stdout


def test_audit_fails_when_jq_is_missing(tmp_path):
    write_cluster_oc(tmp_path)

    result = run_script("post_uninstall_audit.sh", tmp_path)

    assert result.returncode == 1
    assert "FAIL: jq CLI is required but not installed" in result.stdout


def test_audit_stops_when_the_context_does_not_exist(tmp_path):
    result = _audit(tmp_path, errors={"whoami": CONTEXT_ERROR}, args=("--context", "nope"))

    assert result.returncode == 1
    assert f"FAIL: unable to contact the cluster with oc whoami: {CONTEXT_ERROR}" in result.stdout
    assert "Audit Complete" not in result.stdout


def test_audit_forwards_context_and_rejects_unknown_arguments(tmp_path):
    log = tmp_path / "argv.log"
    result = _audit(tmp_path, log=log, args=("--context=target",))

    _clean(result)
    assert "(context: target)" in result.stdout
    assert all('"--context=target"' in line for line in log.read_text(encoding="utf-8").splitlines())

    bad = run_script("post_uninstall_audit.sh", tmp_path, "--bogus")
    assert bad.returncode == 2
    assert "unknown argument: --bogus" in bad.stderr


def test_audit_never_mutates_and_never_loads_secret_data(tmp_path):
    log = tmp_path / "argv.log"
    objects = {
        "namespaces": [{"metadata": meta("rook-ceph"), "status": {"phase": "Active"}}],
        "secrets": [{"metadata": meta("rook-ceph-mon", "rook-ceph"), "data": {"key": "c2VjcmV0"}}],
    }

    _audit(tmp_path, objects=objects, log=log)

    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls
    assert {c[0] for c in calls} <= {"whoami", "get", "api-resources"}, calls
    secret_calls = [c for c in calls if "secrets" in c]
    assert secret_calls
    assert all(c[c.index("-o") + 1] == FINALIZER_JSONPATH for c in secret_calls), secret_calls


def test_audit_keeps_stderr_noise_out_of_the_json(tmp_path):
    result = _audit(tmp_path, noise=True)

    _clean(result)


# --- ownership --------------------------------------------------------------------


def test_audit_warns_while_rook_still_runs(tmp_path):
    result = _audit(tmp_path, objects={"deployments": [rook_operator()],
                                       "cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")]})

    _warn(result, "WARN: upstream Rook operators or CephClusters still exist:", "rook-ceph (CephCluster: rook-ceph)")


def test_audit_warns_for_an_orphaned_cephcluster_of_unknown_owner(tmp_path):
    result = _audit(
        tmp_path,
        objects={"cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph", deletionTimestamp=OLD,
                                                            finalizers=["cephcluster.ceph.rook.io"])]},
        groups={"ceph.rook.io": SHARED_GROUPS["ceph.rook.io"]},
    )

    _warn(
        result,
        "WARN: Ceph objects whose owner cannot be classified",
        "CephCluster rook-ceph/rook-ceph (no non-OLM rook-ceph-operator",
        "CephCluster/rook-ceph/rook-ceph (deleting, finalizers: cephcluster.ceph.rook.io)",
    )


def test_audit_fails_the_ownership_check_on_a_lookup_error(tmp_path):
    result = _audit(tmp_path, errors={"deployments": "Error from server (Forbidden): cannot list deployments"})

    _warn(result, "FAIL: rook-ceph-operator Deployments query failed")
    assert "OK: no ODF present" not in result.stdout


# --- namespaces -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("namespace", "line"),
    [
        ({"metadata": meta("rook-ceph"), "status": {"phase": "Active"}}, "WARN: namespace rook-ceph still exists"),
        ({"metadata": meta("rook-ceph", deletionTimestamp=OLD), "status": {"phase": "Terminating"}},
         f"WARN: namespace rook-ceph Terminating since {OLD}"),
        ({"metadata": meta("rook-ceph", deletionTimestamp=recent()), "status": {"phase": "Terminating"}},
         "WARN: namespace rook-ceph is being deleted"),
    ],
    ids=["active", "stuck", "deleting"],
)
def test_audit_reports_the_rook_namespace_until_it_is_gone(tmp_path, namespace, line):
    result = _audit(tmp_path, objects={"namespaces": [namespace]})

    _warn(result, line)


def test_audit_lists_residue_in_a_kept_rook_namespace(tmp_path):
    objects = {
        "namespaces": [{"metadata": meta("rook-ceph"), "status": {"phase": "Active"}}],
        "pods": [{"metadata": meta("csi-rbdplugin-abc", "rook-ceph", deletionTimestamp=OLD), "status": {"phase": "Running"}}],
        "deployments": [{"kind": "Deployment", "metadata": meta("rook-ceph-tools", "rook-ceph")}],
        "configmaps": [
            {"metadata": meta("rook-ceph-mon-endpoints", "rook-ceph")},
            {"metadata": meta("kube-root-ca.crt", "rook-ceph")},
        ],
        "secrets": [{"metadata": meta("rook-ceph-admin-keyring", "rook-ceph")}],
    }

    result = _audit(tmp_path, objects=objects)

    _warn(
        result,
        "WARN: pods in rook-ceph still exist:",
        f"csi-rbdplugin-abc (Running, deleting since {OLD})",
        "WARN: Rook objects in rook-ceph still exist:",
        "Deployment/rook-ceph-tools",
        "ConfigMap/rook-ceph-mon-endpoints",
        "Secret/rook-ceph-admin-keyring",
    )
    assert "kube-root-ca.crt" not in result.stdout


def test_audit_reports_consumer_namespaces_stuck_terminating(tmp_path):
    objects = {
        "namespaces": [
            {"metadata": meta("app", deletionTimestamp=OLD), "status": {"phase": "Terminating"}},
            {"metadata": meta("fresh", deletionTimestamp=recent()), "status": {"phase": "Terminating"}},
        ]
    }

    result = _audit(tmp_path, objects=objects)

    _warn(result, "WARN: namespaces Terminating for over 10 minutes (younger deletions ignored) still exist:", "app")
    assert "fresh" not in result.stdout


def test_audit_watches_a_custom_namespace(tmp_path):
    objects = {"namespaces": [{"metadata": meta("storage-a"), "status": {"phase": "Active"}}]}

    _clean(_audit(tmp_path, objects=objects))
    _warn(_audit(tmp_path, objects=objects, args=("--namespace", "storage-a")), "WARN: namespace storage-a still exists")


# --- shared API groups ------------------------------------------------------------


def test_audit_warns_for_shared_groups_and_their_instances_without_odf(tmp_path):
    objects = {
        "clientprofiles.csi.ceph.io": [
            {"kind": "ClientProfile", "metadata": meta("rook-ceph", "rook-ceph", deletionTimestamp=OLD,
                                                        finalizers=["csi.ceph.io/cleanup"])}
        ],
        "cephblockpools.ceph.rook.io": [{"kind": "CephBlockPool", "metadata": meta("replicapool", "elsewhere")}],
    }

    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS)

    _warn(
        result,
        "WARN: ceph.rook.io API resources still exist:",
        "WARN: csi.ceph.io API resources still exist:",
        "WARN: objectbucket.io API resources still exist:",
        "CephBlockPool/elsewhere/replicapool",
        "ClientProfile/rook-ceph/rook-ceph (deleting, finalizers: csi.ceph.io/cleanup)",
    )


def test_audit_retains_shared_groups_for_odf_and_reports_only_rook_instances(tmp_path):
    objects = merge(
        ODF_PRESENT,
        {
            "cephclusters.ceph.rook.io": [ceph_cluster("ocs-storagecluster-cephcluster", "openshift-storage")],
            "cephblockpools.ceph.rook.io": [
                {"kind": "CephBlockPool", "metadata": meta("ocs-storagecluster-cephblockpool", "openshift-storage")},
                {"kind": "CephBlockPool", "metadata": meta("replicapool", "rook-ceph")},
            ],
        },
    )

    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS)

    _ok(
        result,
        "ceph.rook.io API resources retained: ODF uses them",
        "csi.ceph.io API resources retained: ODF uses them",
        "objectbucket.io API resources retained: ODF uses them",
        "ODF present; its objects are not Rook residue",
        "no csi.ceph.io objects of Rook",
    )
    _warn(result, "CephBlockPool/rook-ceph/replicapool")
    assert "ocs-storagecluster-cephblockpool" not in result.stdout.split("ceph.rook.io API resources retained")[1]


def test_audit_fails_on_group_discovery_errors(tmp_path):
    result = _audit(tmp_path, errors={"api-resources:csi.ceph.io": "Error from server (Forbidden): discovery"})

    _warn(result, "FAIL: csi.ceph.io API resource discovery failed")
    assert "OK: no csi.ceph.io API resources found" not in result.stdout


# --- StorageClasses, PVs, PVCs ----------------------------------------------------


def test_audit_finds_rook_storage_by_provisioner_and_driver_not_by_name(tmp_path):
    objects = {
        "sc": [
            {"metadata": meta("fast-block"), "provisioner": "rook-ceph.rbd.csi.ceph.com"},
            {"metadata": meta("rook-ceph-lookalike"), "provisioner": "topolvm.io"},
        ],
        "pv": [
            {"metadata": meta("pvc-a"), "spec": {"csi": {"driver": "rook-ceph.rbd.csi.ceph.com"}, "storageClassName": "custom-name"},
             "status": {"phase": "Bound"}},
            {"metadata": meta("pvc-lvm"), "spec": {"csi": {"driver": "topolvm.io"}, "storageClassName": "rook-ceph-lookalike"}},
        ],
        "pvc": [
            {"metadata": meta("data", "app"), "spec": {"storageClassName": "custom-name", "volumeName": "pvc-a"}},
            {"metadata": meta("other", "app"), "spec": {"storageClassName": "fast-block"}},
            {"metadata": meta("lvm", "app"), "spec": {"storageClassName": "rook-ceph-lookalike", "volumeName": "pvc-lvm"}},
        ],
    }

    result = _audit(tmp_path, objects=objects)

    _warn(
        result,
        "WARN: Rook StorageClasses still exist:",
        "fast-block (rook-ceph.rbd.csi.ceph.com)",
        "WARN: Rook PVs still exist:",
        "pvc-a (class custom-name, phase Bound)",
        "WARN: Rook PVCs still exist:",
        "app/data",
        "app/other",
    )
    assert "pvc-lvm" not in result.stdout
    assert "app/lvm" not in result.stdout
    assert "rook-ceph-lookalike (" not in result.stdout


def test_audit_honours_a_custom_csi_prefix(tmp_path):
    objects = {"csidrivers": [{"metadata": meta("lab.rbd.csi.ceph.com")}],
               "sc": [{"metadata": meta("lab-block"), "provisioner": "lab.rbd.csi.ceph.com"}]}

    default = _audit(tmp_path, objects=objects)
    custom = _audit(tmp_path, objects=objects, args=("--csi-prefix", "lab"))

    assert "lab-block" not in default.stdout
    _warn(custom, "WARN: Rook CSIDrivers still exist:", "lab.rbd.csi.ceph.com", "lab-block (lab.rbd.csi.ceph.com)")


def test_audit_reports_deleting_pvcs_and_pvs_by_deletion_timestamp_not_phase(tmp_path):
    objects = {
        "pvc": [
            {"metadata": meta("db", "openshift-storage", deletionTimestamp=OLD, finalizers=["kubernetes.io/pvc-protection"]),
             "spec": {}, "status": {"phase": "Bound"}},
            {"metadata": meta("young", "app", deletionTimestamp=recent()), "spec": {}, "status": {"phase": "Bound"}},
        ],
        "pv": [
            {"metadata": meta("pvc-old", deletionTimestamp=OLD,
                              finalizers=["external-provisioner.volume.kubernetes.io/finalizer", "kubernetes.io/pv-protection"]),
             "spec": {}, "status": {"phase": "Released"}},
        ],
    }

    result = _audit(tmp_path, objects=objects)

    _warn(
        result,
        "WARN: PVCs Terminating for over 10 minutes (younger deletions ignored) still exist:",
        "openshift-storage/db (phase Bound, finalizers: kubernetes.io/pvc-protection)",
        "WARN: PVs Terminating for over 10 minutes (younger deletions ignored) still exist:",
        "pvc-old (phase Released, finalizers: external-provisioner.volume.kubernetes.io/finalizer,kubernetes.io/pv-protection)",
    )
    assert "app/young" not in result.stdout


# --- CSI objects ------------------------------------------------------------------


def test_audit_reports_rook_csi_objects_and_ignores_odf_ones(tmp_path):
    objects = {
        "csidrivers": [{"metadata": meta("rook-ceph.cephfs.csi.ceph.com")},
                       {"metadata": meta("openshift-storage.rbd.csi.ceph.com")}],
        "csinodes": [{"metadata": meta("node-a"), "spec": {"drivers": [
            {"name": "rook-ceph.rbd.csi.ceph.com"}, {"name": "topolvm.io"}]}}],
        "volumeattachments": [
            {"metadata": meta("csi-1", finalizers=["external-attacher/rook-ceph-rbd-csi-ceph-com"]),
             "spec": {"attacher": "rook-ceph.rbd.csi.ceph.com", "source": {"persistentVolumeName": "pvc-a"}},
             "status": {"attached": True}},
            {"metadata": meta("csi-2"), "spec": {"attacher": "openshift-storage.rbd.csi.ceph.com"}},
        ],
        "volumesnapshotclasses": [
            {"metadata": meta("custom-snap"), "driver": "rook-ceph.rbd.csi.ceph.com"},
            {"metadata": meta("ocs-snap"), "driver": "openshift-storage.rbd.csi.ceph.com"},
        ],
    }

    result = _audit(tmp_path, objects=objects, groups=SNAPSHOT_GROUP)

    _warn(
        result,
        "WARN: Rook CSIDrivers still exist:",
        "rook-ceph.cephfs.csi.ceph.com",
        "WARN: Rook CSI drivers registered on nodes (CSINode) still exist:",
        "node-a: rook-ceph.rbd.csi.ceph.com",
        "WARN: Rook VolumeAttachments still exist:",
        "csi-1 (pv pvc-a, attached true, finalizers: external-attacher/rook-ceph-rbd-csi-ceph-com)",
        "WARN: Rook VolumeSnapshotClasses still exist:",
        "custom-snap (rook-ceph.rbd.csi.ceph.com)",
    )
    assert "csi-2" not in result.stdout
    assert "ocs-snap" not in result.stdout


def test_audit_tolerates_absent_snapshot_classes(tmp_path):
    result = _audit(tmp_path)

    _ok(result, "no Rook VolumeSnapshotClasses found (resource type not served)")


def test_audit_reports_pods_stuck_deleting_anywhere(tmp_path):
    objects = {"pods": [
        {"metadata": meta("noobaa-db-pg-cluster-1", "openshift-storage", deletionTimestamp=OLD),
         "spec": {"nodeName": "node-a"}, "status": {"phase": "Failed"}},
        {"metadata": meta("young", "app", deletionTimestamp=recent()), "spec": {}, "status": {"phase": "Running"}},
    ]}

    result = _audit(tmp_path, objects=objects)

    _warn(result, "openshift-storage/noobaa-db-pg-cluster-1 (Failed, node node-a, deleting since")
    assert "app/young" not in result.stdout


# --- buckets ----------------------------------------------------------------------

BUCKET_CLASSES = [
    {"metadata": meta("rook-ceph-bucket"), "provisioner": "rook-ceph.ceph.rook.io/bucket"},
    {"metadata": meta("ocs-storagecluster-ceph-rgw"), "provisioner": "openshift-storage.ceph.rook.io/bucket"},
]


def _buckets(*claims):
    return {
        "sc": BUCKET_CLASSES,
        "objectbucketclaims.objectbucket.io": [
            {"metadata": meta(name, ns), "spec": {"storageClassName": sc}} for ns, name, sc in claims
        ],
        "objectbuckets.objectbucket.io": [
            {"metadata": meta(f"obc-{ns}-{name}"), "spec": {"storageClassName": sc}} for ns, name, sc in claims
        ],
    }


def test_audit_reports_rook_buckets_by_storageclass_and_keeps_odf_ones(tmp_path):
    objects = _buckets(("app", "rook-claim", "rook-ceph-bucket"), ("app", "odf-claim", "ocs-storagecluster-ceph-rgw"),
                       ("app", "gone-claim", "deleted-class"))

    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS)

    _warn(
        result,
        "WARN: Rook ObjectBucketClaims still exist:",
        "app/rook-claim (class rook-ceph-bucket: rook-ceph.ceph.rook.io/bucket)",
        "app/gone-claim (class deleted-class: missing)",
        "WARN: Rook ObjectBuckets still exist:",
        "obc-app-rook-claim",
    )
    assert "app/odf-claim" not in result.stdout


def test_audit_marks_classless_buckets_unknown_next_to_odf(tmp_path):
    objects = merge(ODF_PRESENT, _buckets(("app", "gone-claim", "deleted-class")))

    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS)

    _warn(
        result,
        "WARN: bucket claims and buckets of unknown owner (StorageClass gone while ODF is present; review by hand) still exist:",
        "ObjectBucketClaim app/gone-claim (class deleted-class: missing)",
        "ObjectBucket obc-app-gone-claim (class deleted-class: missing)",
    )
    _ok(result, "no Rook ObjectBucketClaims found")


def test_audit_reports_bucket_finalizer_holders_in_terminating_namespaces(tmp_path):
    held = ["objectbucket.io/finalizer"]
    objects = merge(
        _buckets(("app", "odf-claim", "ocs-storagecluster-ceph-rgw")),
        {
            "namespaces": [{"metadata": meta("app", deletionTimestamp=OLD), "status": {"phase": "Terminating"}}],
            "configmaps": [
                {"metadata": meta("rook-claim", "app", finalizers=held)},
                {"metadata": meta("odf-claim", "app", finalizers=held)},
                {"metadata": meta("plain", "app")},
            ],
            "secrets": [{"metadata": meta("rook-claim", "app", finalizers=held)}],
        },
    )

    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS)

    _warn(
        result,
        "WARN: ConfigMaps and Secrets held by objectbucket.io/finalizer without a live claim still exist:",
        "ConfigMap/app/rook-claim",
        "Secret/app/rook-claim",
    )
    assert "ConfigMap/app/odf-claim" not in result.stdout


def test_audit_names_a_forbidden_secret_listing(tmp_path):
    objects = merge(
        _buckets(),
        {"namespaces": [{"metadata": meta("app", deletionTimestamp=OLD), "status": {"phase": "Terminating"}}]},
    )

    result = _audit(tmp_path, objects=objects, groups=SHARED_GROUPS,
                    errors={"secrets": "Error from server (Forbidden): secrets is forbidden"})

    _warn(result, "FAIL: could not check secrets in app for objectbucket.io/finalizer: listing secrets is forbidden")


# --- SCCs, PriorityClass, MachineConfigs ------------------------------------------


@pytest.mark.parametrize(
    ("users", "line"),
    [
        (["system:serviceaccount:rook-ceph:rook-ceph-system", "system:serviceaccount:rook-ceph:rook-ceph-osd"],
         "WARN: SCC rook-ceph is Rook residue: every user is a service account in rook-ceph"),
        (["system:serviceaccount:openshift-storage:rook-ceph-system"],
         "OK: SCC rook-ceph retained: every user is a service account in openshift-storage, so it is ODF's"),
        (["system:serviceaccount:rook-ceph:rook-ceph-system", "system:serviceaccount:openshift-storage:rook-ceph-system"],
         "WARN: SCC rook-ceph has users outside rook-ceph - decide by hand"),
        ([], "WARN: SCC rook-ceph has no users or groups"),
    ],
    ids=["rook", "odf", "mixed", "empty"],
)
def test_audit_judges_rook_sccs_by_their_users(tmp_path, users, line):
    objects = {"scc": [{"metadata": meta("rook-ceph"), "users": users},
                       {"metadata": meta("restricted-v2"), "users": []}]}

    result = _audit(tmp_path, objects=objects)

    assert line in result.stdout
    assert "restricted-v2" not in result.stdout
    assert result.returncode == (0 if line.startswith("OK") else 1), result.stdout


def test_audit_tolerates_an_absent_scc_kind(tmp_path):
    core = tuple(k for k in __import__("rook_cluster_fake").CORE_KINDS if k not in ("scc", "machineconfigs"))

    result = _audit(tmp_path, core=core)

    _clean(result)
    _ok(result, "no rook-ceph or rook-ceph-csi SCC (resource type not served)",
        "no MachineConfigs named for Rook (resource type not served)")


def test_audit_warns_for_the_priority_class(tmp_path):
    result = _audit(tmp_path, objects={"priorityclasses": [{"metadata": meta("rook-ceph-default")}]})

    _warn(result, "WARN: PriorityClass rook-ceph-default still exists")


def test_audit_reports_rook_machineconfigs_without_failing(tmp_path):
    result = _audit(tmp_path, objects={"machineconfigs": [{"metadata": meta("99-worker-rook-ceph-udev")}]})

    _clean(result)
    _ok(result, "MachineConfig 99-worker-rook-ceph-udev is named for Rook: report only")


# --- cluster RBAC -----------------------------------------------------------------


def _rbac(roles=(), bindings=(), rolebindings=(), accounts=()):
    return {
        "clusterroles": list(roles),
        "clusterrolebindings": list(bindings),
        "rolebindings": list(rolebindings),
        "serviceaccounts": [{"metadata": meta(name, ns)} for ns, name in accounts],
    }


def _role(name, labels=None, selectors=None):
    item = {"metadata": meta(name, labels=labels or {})}
    if selectors is not None:
        item["aggregationRule"] = {"clusterRoleSelectors": selectors}
    return item


def _binding(name, role, subjects, labels=None):
    return {"metadata": meta(name, labels=labels or {}), "roleRef": {"kind": "ClusterRole", "name": role}, "subjects": subjects}


def _sa(ns, name):
    return {"kind": "ServiceAccount", "namespace": ns, "name": name}


def test_audit_classifies_rook_rbac_by_liveness(tmp_path):
    objects = _rbac(
        roles=[_role("rook-ceph-global"), _role("rook-ceph-osd"), _role("rbd-csi-nodeplugin"), _role("rook-ceph-system")],
        bindings=[
            _binding("rook-ceph-global", "rook-ceph-global", [_sa("rook-ceph", "rook-ceph-system")]),
            _binding("rook-ceph-osd", "rook-ceph-osd", [_sa("storage-b", "rook-ceph-osd")]),
            _binding("rook-ceph-user", "rook-ceph-system", [{"kind": "User", "name": "someone"}]),
            _binding("custom-binding", "missing-role", [_sa("rook-ceph", "anything")]),
        ],
        accounts=[("storage-b", "rook-ceph-osd")],
    )

    result = _audit(tmp_path, objects=objects)

    _warn(
        result,
        "WARN: dead Rook cluster RBAC still exists:",
        "ClusterRoleBinding/rook-ceph-global: none of its ServiceAccount subjects exists",
        "ClusterRole/rook-ceph-global: referenced only by dead ClusterRoleBinding/rook-ceph-global",
        "ClusterRole/rbd-csi-nodeplugin: no binding references it",
        "ClusterRoleBinding/custom-binding: its ClusterRole missing-role is missing",
    )
    _ok(
        result,
        "ClusterRoleBinding/rook-ceph-osd retained: bound to live ServiceAccount storage-b/rook-ceph-osd",
        "ClusterRole/rook-ceph-osd retained: referenced by live ClusterRoleBinding/rook-ceph-osd",
        "ClusterRoleBinding/rook-ceph-user retained: has a User/Group subject",
        "ClusterRole/rook-ceph-system retained: referenced by live ClusterRoleBinding/rook-ceph-user",
    )


def test_audit_does_not_report_odf_named_rook_ceph_objects_as_rook_residue(tmp_path):
    # ODF 4.20 creates these rook-ceph-* objects, labelled by OLM for ocs-operator.
    objects = merge(
        ODF_PRESENT,
        _rbac(
            roles=[_role("rook-ceph-metrics", ODF_LABELS), _role("rook-ceph-monitor", ODF_LABELS),
                   _role("rook-ceph-monitor-mgr", ODF_LABELS)],
            bindings=[_binding("rook-ceph-metrics", "rook-ceph-metrics",
                               [_sa("openshift-monitoring", "prometheus-k8s")], ODF_LABELS)],
        ),
        {
            "poddisruptionbudgets": [{"kind": "PodDisruptionBudget",
                                      "metadata": meta("rook-ceph-mon-pdb", "openshift-storage", labels=ODF_LABELS)}],
            "roles": [{"kind": "Role", "metadata": meta("rook-ceph-metrics", "openshift-storage", labels=ODF_LABELS)}],
        },
    )

    result = _audit(tmp_path, objects=objects)

    _clean(result)
    _ok(
        result,
        "ClusterRole/rook-ceph-metrics retained: carries OLM labels of installed operator CSV ocs-operator.v4.20.17-rhodf",
        "ClusterRole/rook-ceph-monitor-mgr retained",
        "ClusterRoleBinding/rook-ceph-metrics retained",
    )
    assert "rook-ceph-mon-pdb" not in result.stdout


def test_audit_reports_stale_olm_labels_as_another_operators_leftover(tmp_path):
    objects = _rbac(roles=[_role("rook-ceph-monitor", {"operators.coreos.com/ocs-operator.openshift-storage": ""})])

    result = _audit(tmp_path, objects=objects)

    _clean(result)
    _ok(result, "ClusterRole/rook-ceph-monitor: carries OLM labels of package ocs-operator, which is not installed; "
                "not Rook residue")


@pytest.mark.parametrize(
    ("selector", "verdict"),
    [
        ({"matchLabels": {"rbac.ceph.rook.io/aggregate-to-rook-ceph-mgr": "true"}}, "retained: aggregated into aggregate"),
        ({"matchExpressions": [{"key": "rbac.ceph.rook.io/aggregate-to-rook-ceph-mgr", "operator": "Exists"}]},
         "retained: aggregated into aggregate"),
        ({"matchExpressions": [{"key": "tier", "operator": "In", "values": ["storage"]}]},
         "retained: aggregated into aggregate"),
        ({"matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["storage"]}]}, "dead"),
        # NotIn holds when the key is absent
        ({"matchExpressions": [{"key": "absent", "operator": "NotIn", "values": ["x"]}]},
         "retained: aggregated into aggregate"),
        ({"matchExpressions": [{"key": "absent", "operator": "DoesNotExist"}]}, "retained: aggregated into aggregate"),
        ({"matchExpressions": [{"key": "tier", "operator": "Exists"}], "matchLabels": {"other": "x"}}, "dead"),
        # Kubernetes reads a non-nil empty selector as "everything"
        ({}, "retained: aggregated by a select-all rule into aggregate"),
        ({"matchLabels": {}}, "retained: aggregated by a select-all rule into aggregate"),
        ({"matchExpressions": [{"key": "tier", "operator": "Gt", "values": ["1"]}]},
         "retained: aggregation selector could not be evaluated"),
        ({"matchExpressions": [{"key": 5, "operator": "Exists"}]}, "retained: aggregation selector could not be evaluated"),
        ({"matchExpressions": [{"key": "tier", "operator": "In"}]},
         "retained: aggregation selector could not be evaluated"),
    ],
    ids=["match-labels", "exists", "in", "not-in", "not-in-key-absent", "does-not-exist", "and-not-met", "empty",
         "empty-match-labels", "unknown-operator", "malformed-key", "in-without-values"],
)
def test_audit_evaluates_aggregation_selectors_in_full(tmp_path, selector, verdict):
    labels = {"rbac.ceph.rook.io/aggregate-to-rook-ceph-mgr": "true", "tier": "storage"}
    objects = _rbac(roles=[_role("rook-ceph-mgr-cluster", labels), _role("aggregate", selectors=[selector])])

    result = _audit(tmp_path, objects=objects)

    if verdict == "dead":
        _warn(result, "ClusterRole/rook-ceph-mgr-cluster: no binding references it")
    else:
        _ok(result, f"ClusterRole/rook-ceph-mgr-cluster {verdict}")
        _clean(result)


def test_audit_keeps_a_role_used_by_a_live_rolebinding(tmp_path):
    objects = _rbac(
        roles=[_role("rook-ceph-object-bucket")],
        rolebindings=[{"metadata": meta("uses", "app"), "roleRef": {"kind": "ClusterRole", "name": "rook-ceph-object-bucket"},
                       "subjects": [{"kind": "ServiceAccount", "name": "worker"}]}],
        accounts=[("app", "worker")],
    )

    result = _audit(tmp_path, objects=objects)

    _clean(result)
    _ok(result, "ClusterRole/rook-ceph-object-bucket retained: referenced by live RoleBinding app/uses")


PROMETHEUS_ONLY = (
    "only the platform ServiceAccount openshift-monitoring/prometheus-k8s remains, "
    "which is not a Ceph consumer"
)


def _prometheus_metrics_rbac():
    return _rbac(
        roles=[_role("rook-ceph-metrics")],
        bindings=[_binding("rook-ceph-metrics", "rook-ceph-metrics", [_sa("openshift-monitoring", "prometheus-k8s")])],
        accounts=[("openshift-monitoring", "prometheus-k8s")],
    )


def test_audit_treats_prometheus_metrics_rbac_as_residue_once_no_ceph_runs(tmp_path):
    result = _audit(tmp_path, objects=_prometheus_metrics_rbac())

    _warn(
        result,
        "WARN: dead Rook cluster RBAC still exists:",
        f"ClusterRoleBinding/rook-ceph-metrics: {PROMETHEUS_ONLY}",
        "ClusterRole/rook-ceph-metrics: referenced only by dead ClusterRoleBinding/rook-ceph-metrics",
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"deployments": [rook_operator()], "cephclusters.ceph.rook.io": [ceph_cluster("rook-ceph", "rook-ceph")]},
        ODF_PRESENT,
    ],
    ids=["upstream-rook", "odf"],
)
def test_audit_keeps_prometheus_metrics_rbac_while_ceph_runs(tmp_path, extra):
    result = _audit(tmp_path, objects=merge(_prometheus_metrics_rbac(), extra))

    _ok(
        result,
        "ClusterRoleBinding/rook-ceph-metrics retained: bound to live ServiceAccount openshift-monitoring/prometheus-k8s",
        "ClusterRole/rook-ceph-metrics retained: referenced by live ClusterRoleBinding/rook-ceph-metrics",
    )
    assert PROMETHEUS_ONLY not in result.stdout


def test_audit_keeps_a_metrics_binding_with_another_live_subject(tmp_path):
    objects = _rbac(
        roles=[_role("rook-ceph-metrics")],
        bindings=[_binding("rook-ceph-metrics", "rook-ceph-metrics",
                           [_sa("openshift-monitoring", "prometheus-k8s"), _sa("monitoring", "prometheus")])],
        accounts=[("openshift-monitoring", "prometheus-k8s"), ("monitoring", "prometheus")],
    )

    result = _audit(tmp_path, objects=objects)

    _ok(result, "ClusterRoleBinding/rook-ceph-metrics retained: bound to live ServiceAccount")
    assert PROMETHEUS_ONLY not in result.stdout


# --- default StorageClass ---------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "line"),
    [
        ([{"metadata": meta("second", annotations={"storageclass.kubernetes.io/is-default-class": "true"}),
           "provisioner": "x"}], "WARN: multiple default StorageClasses found:"),
    ],
)
def test_audit_requires_exactly_one_default_storageclass(tmp_path, extra, line):
    _warn(_audit(tmp_path, objects={"sc": extra}), line)


def test_audit_warns_without_a_default_storageclass(tmp_path):
    write_jq_proxy(tmp_path)
    write_oc(
        tmp_path,
        """
        args = [a for a in sys.argv[1:]]
        if args[:1] == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args[:1] == ["api-resources"]:
            raise SystemExit(0)
        if args[:2] == ["get", "namespaces"] and len(args) > 2 and not args[2].startswith("-"):
            print("Error from server (NotFound): not found", file=sys.stderr)
            raise SystemExit(1)
        if args[:2] == ["get", "priorityclasses"]:
            print("Error from server (NotFound): not found", file=sys.stderr)
            raise SystemExit(1)
        if any(a.startswith("jsonpath=") for a in args):
            raise SystemExit(0)
        print(json.dumps({"items": []}))
        """,
    )

    result = run_script("post_uninstall_audit.sh", tmp_path)

    _warn(result, "WARN: no default StorageClass found")


def test_audit_accepts_no_default_storageclass_when_that_was_the_prior_policy(tmp_path):
    result = _audit(tmp_path, default_sc=False, env={"PRIOR_DEFAULT_STORAGE_CLASS": ""})

    _clean(result)
    _ok(result, "no default StorageClass, matching the pre-install policy")


def test_audit_warns_when_a_default_appeared_although_there_was_none(tmp_path):
    result = _audit(tmp_path, env={"PRIOR_DEFAULT_STORAGE_CLASS": ""})

    _warn(result, "WARN: default StorageClass is 'platform-default', pre-install policy had none")


def test_audit_accepts_the_recorded_prior_default_storageclass(tmp_path):
    result = _audit(tmp_path, env={"PRIOR_DEFAULT_STORAGE_CLASS": "platform-default"})

    _clean(result)
    _ok(result, "exactly one default StorageClass: platform-default")


def test_audit_warns_when_the_prior_default_storageclass_changed(tmp_path):
    result = _audit(tmp_path, env={"PRIOR_DEFAULT_STORAGE_CLASS": "other-class"})

    _warn(result, "WARN: default StorageClass is 'platform-default', pre-install policy was other-class")


# --- argument validation, empty output, strict lookups ------------------------------


@pytest.mark.parametrize(
    "args",
    [("--namespace", "openshift-storage"), ("--csi-prefix", "openshift-storage"), ("--namespace=openshift-storage",)],
    ids=["namespace", "prefix", "namespace-equals"],
)
def test_audit_refuses_odfs_namespace_and_prefix(tmp_path, args):
    result = _audit(tmp_path, args=args)

    assert result.returncode == 2
    assert "openshift-storage is ODF's namespace and CSI driver prefix" in result.stderr
    assert "OK:" not in result.stdout


@pytest.mark.parametrize(
    ("resource", "label", "ok_line"),
    [
        ("pv", "PersistentVolumes", "no Rook PVs found"),
        ("sc", "Rook StorageClasses", "no Rook StorageClasses found"),
        ("csidrivers", "CSIDrivers", "every CephCluster, rook-ceph-operator, and Ceph CSI driver"),
        ("clusterroles", "ClusterRoles", "no dead Rook ClusterRoles or ClusterRoleBindings found"),
    ],
    ids=["pv", "sc", "csidrivers", "clusterroles"],
)
def test_audit_fails_when_a_successful_call_prints_nothing(tmp_path, resource, label, ok_line):
    result = _audit(tmp_path, empty=(resource,))

    _warn(result, f"FAIL: {label} query returned nothing")
    assert f"OK: {ok_line}" not in result.stdout


@pytest.mark.parametrize(
    ("resource", "error", "line"),
    [
        ("subscriptions.operators.coreos.com", "Error from server (NotFound): the server could not find the requested resource",
         "FAIL: Subscriptions lookup failed"),
        ("clusterserviceversions.operators.coreos.com", 'error: the server doesn\'t have a resource type "csv"',
         "FAIL: ClusterServiceVersions lookup failed"),
        ("cephclusters.ceph.rook.io", "Error from server (NotFound): the server could not find the requested resource",
         "FAIL: CephClusters lookup failed"),
        ("cephclusters.ceph.rook.io", "Error from server (Forbidden): cannot list cephclusters",
         "FAIL: CephClusters query failed"),
    ],
    ids=["subscription-notfound", "csv-no-type", "cephcluster-notfound", "cephcluster-forbidden"],
)
def test_audit_ownership_lookups_are_strict(tmp_path, resource, error, line):
    result = _audit(tmp_path, errors={resource: error})

    _warn(result, line)
    assert "OK: no ODF present" not in result.stdout
    # the failed lookup stops the classification; it is not fed on to jq
    assert "Ceph ownership jq filter failed" not in result.stdout


def test_audit_reads_a_missing_cephcluster_crd_as_none(tmp_path):
    result = _audit(tmp_path, errors={"cephclusters.ceph.rook.io": 'error: the server doesn\'t have a resource type "cephclusters"'})

    _clean(result)
    _ok(result, "no ODF present")


def test_audit_gives_no_ok_line_for_a_namespace_kind_it_could_not_read(tmp_path):
    objects = {"namespaces": [{"metadata": meta("rook-ceph"), "status": {"phase": "Active"}}]}

    result = _audit(tmp_path, objects=objects, errors={"deployments": "Error from server (Forbidden): deployments"})

    _warn(result, "FAIL: Rook objects in rook-ceph (deployments) query failed")
    assert "OK: no Rook objects in rook-ceph" not in result.stdout


def test_audit_names_bucket_finalizer_holders_after_the_crds_are_gone(tmp_path):
    held = ["objectbucket.io/finalizer"]
    objects = {
        "namespaces": [{"metadata": meta("app", deletionTimestamp=OLD), "status": {"phase": "Terminating"}}],
        "configmaps": [{"metadata": meta("lost-claim", "app", finalizers=held)}],
        "secrets": [{"metadata": meta("lost-claim", "app", finalizers=held)}],
    }

    result = _audit(tmp_path, objects=objects)

    _ok(result, "no ObjectBucketClaims or ObjectBuckets (resource type not served)")
    _warn(result, "WARN: ConfigMaps and Secrets held by objectbucket.io/finalizer without a live claim still exist:",
          "ConfigMap/app/lost-claim", "Secret/app/lost-claim")


@pytest.mark.parametrize(
    ("scc", "line"),
    [
        ({"users": [], "groups": ["system:serviceaccounts:rook-ceph"]},
         "WARN: SCC rook-ceph-csi is Rook residue: every user is a service account in rook-ceph"),
        ({"users": [], "groups": ["system:serviceaccounts:openshift-storage"]},
         "OK: SCC rook-ceph-csi retained: every user is a service account in openshift-storage"),
        ({"users": ["system:serviceaccount:rook-ceph:x"], "groups": ["system:authenticated"]},
         "WARN: SCC rook-ceph-csi has users outside rook-ceph"),
        ({"users": ["system:serviceaccount:rook-ceph-x:rook-ceph-system"]},
         "WARN: SCC rook-ceph-csi has users outside rook-ceph"),
    ],
    ids=["rook-group", "odf-group", "foreign-group", "lookalike-namespace"],
)
def test_audit_judges_scc_groups_and_lookalike_namespaces(tmp_path, scc, line):
    result = _audit(tmp_path, objects={"scc": [{"metadata": meta("rook-ceph-csi"), **scc}]})

    assert line in result.stdout, result.stdout


def test_audit_matches_nvmeof_drivers(tmp_path):
    result = _audit(tmp_path, objects={"csidrivers": [{"metadata": meta("rook-ceph.nvmeof.csi.ceph.com")}]})

    _warn(result, "WARN: Rook CSIDrivers still exist:", "rook-ceph.nvmeof.csi.ceph.com")
