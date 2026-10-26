import copy
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_object_smoke.py"


def load():
    spec = importlib.util.spec_from_file_location("rook_rgw_smoke_38", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def obj(kind, name, ns=None, **extra):
    return {"apiVersion": "v1", "kind": kind, "metadata": {"name": name, "uid": kind + "-" + name,
            **({"namespace": ns} if ns else {})}, **extra}


class Kube:
    def __init__(self, namespace="openshift-storage", watch="true", fail_exec=False, replace_pod=False, race_delete=False):
        self.events = []
        self.fail_exec = fail_exec
        self.replace_pod = replace_pod
        self.race_delete = race_delete
        self.executed = False
        self.objects = {
            ("openshift-storage", "deployment", "rook-ceph-operator"): obj("Deployment", "rook-ceph-operator", "openshift-storage",
                spec={"template": {"spec": {"containers": [{"env": []}]}}}),
            (None, "namespace", namespace): obj("Namespace", namespace),
            (None, "storageclass", "ocs-storagecluster-ceph-rgw"): obj("StorageClass", "ocs-storagecluster-ceph-rgw",
                provisioner="openshift-storage.ceph.rook.io/bucket", reclaimPolicy="Delete",
                parameters={"objectStoreNamespace": "openshift-storage", "objectStoreName": "store"}),
            ("openshift-storage", "configmap", "rook-ceph-operator-config"): obj("ConfigMap", "rook-ceph-operator-config",
                "openshift-storage", data={"ROOK_OBC_WATCH_OPERATOR_NAMESPACE": watch}),
        }
        self.objects[(None, "namespace", namespace)]["metadata"]["labels"] = {"app.kubernetes.io/part-of": "storage-smoke"}

    def __call__(self, command, input=None, **kwargs):
        assert command[:3] == ["oc", "--context", "target"]
        args = command[4:]
        ns = None
        if "-n" in args:
            i = args.index("-n"); ns = args[i + 1]; args = args[:i] + args[i + 2:]
        self.events.append((ns, args, input))
        data = ""
        rc = 0
        if args[0] == "get":
            if args[1:4] == ["objectbucket", "-o", "json"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps({"items": [v for k, v in self.objects.items() if k[1] == "objectbucket"]}), stderr="")
            kind, name = args[1:3]
            value = self.objects.get((ns, kind, name))
            if value and self.replace_pod and self.executed and kind == "pod":
                value = copy.deepcopy(value); value["metadata"]["uid"] = "replacement"
            if value:
                data = json.dumps(value) if args[-1] == "json" else kind + "/" + name
            elif "--ignore-not-found" not in args:
                rc = 1
        elif args[0] == "create":
            value = json.loads(input)
            kind = {"Pod": "pod", "ObjectBucketClaim": "objectbucketclaim"}[value["kind"]]
            name = value["metadata"]["name"]
            value["metadata"]["uid"] = kind + "-uid"
            value["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
            if kind == "objectbucketclaim":
                value["status"]["phase"] = "Bound"
                value["spec"]["objectBucketName"] = "fake-global-object"
                self.objects[(None, "objectbucket", "fake-global-object")] = obj("ObjectBucket", "fake-global-object",
                    spec={"claimRef": {"namespace": ns, "name": name, "uid": value["metadata"]["uid"]}})
                for companion in ["secret", "configmap"]:
                    self.objects[(ns, companion, name)] = obj(companion, name, ns)
            self.objects[(ns, kind, name)] = value
            data = json.dumps(value)
        elif args[0] == "exec":
            self.executed = True
            assert "AWS_SECRET_ACCESS_KEY" in input  # source code, never a credential value
            rc = int(self.fail_exec)
            data = json.dumps({"status": "passed", "put_get_compare_delete": True})
        elif args[0] == "delete":
            if args[1] == "--raw":
                path = args[2].split("/")
                kind = {"pods": "pod", "objectbucketclaims": "objectbucketclaim"}[path[-2]]
                name = path[-1]
                assert path[-3] == ns
                options = json.loads(input)
                assert options["kind"] == "DeleteOptions"
            else:
                kind, name = args[1:3]
                options = {}
            assert kind != "namespace"
            if self.race_delete and kind == "pod":
                self.objects[(ns, kind, name)]["metadata"]["uid"] = "replacement"
            if options and options["preconditions"]["uid"] != self.objects[(ns, kind, name)]["metadata"]["uid"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="Conflict")
            self.objects.pop((ns, kind, name))
            if kind == "objectbucketclaim":
                self.objects.pop((None, "objectbucket", "fake-global-object"))
                for companion in ["secret", "configmap"]:
                    self.objects.pop((ns, companion, name))
        else:
            raise AssertionError(args)
        return SimpleNamespace(returncode=rc, stdout=data, stderr="private diagnostic" if rc else "")


def args(namespace="openshift-storage"):
    return SimpleNamespace(context="target", namespace=namespace, operator_namespace="openshift-storage",
        storage_class="ocs-storagecluster-ceph-rgw", image="quay.io/ceph/ceph:v20.2.4", allow_http=True,
        tls_ca="public", ca_configmap=None, timeout_seconds=1)


def test_operator_watch_scope_roundtrip_cleans_only_owned_resources():
    module = load(); kube = Kube(); smoke = module.Smoke(args(), runner=kube)
    assert smoke.run()["status"] == "passed"
    assert not any(key[1] in ("pod", "objectbucketclaim", "objectbucket", "secret") for key in kube.objects)
    pod = next(json.loads(payload) for _, command, payload in kube.events if command[0] == "create" and json.loads(payload)["kind"] == "Pod")
    assert pod["spec"]["containers"][0]["envFrom"]
    assert pod["spec"]["containers"][0]["securityContext"]["allowPrivilegeEscalation"] is False


def test_s3_failure_is_preserved_after_successful_cleanup():
    module = load(); kube = Kube(fail_exec=True)
    with pytest.raises(module.Failure):
        module.Smoke(args(), runner=kube).run()
    assert not any(key[1] in ("pod", "objectbucketclaim", "objectbucket", "secret") for key in kube.objects)


def test_watch_scope_mismatch_refuses_without_mutation():
    module = load(); kube = Kube(namespace="object-smoke")
    with pytest.raises(module.Failure, match="watch scope"):
        module.Smoke(args("object-smoke"), runner=kube).run()
    assert not any(command[0] in ("create", "delete") for _, command, _ in kube.events)


def test_cluster_wide_watch_supports_a_labelled_smoke_namespace():
    module = load(); kube = Kube(namespace="object-smoke", watch="false")
    assert module.Smoke(args("object-smoke"), runner=kube).run()["status"] == "passed"


def test_cleanup_refuses_a_replaced_pod_and_reports_failure():
    module = load(); kube = Kube(replace_pod=True)
    with pytest.raises(module.Failure, match="cleanup"):
        module.Smoke(args(), runner=kube).run()
    assert not any(command[0] == "delete" for _, command, _ in kube.events)


def test_explicit_operator_environment_overrides_configmap_watch_scope():
    module = load(); kube = Kube(namespace="object-smoke", watch="false")
    operator = kube.objects[("openshift-storage", "deployment", "rook-ceph-operator")]
    operator["spec"]["template"]["spec"]["containers"][0]["env"] = [
        {"name": "ROOK_OBC_WATCH_OPERATOR_NAMESPACE", "value": "true"}]
    with pytest.raises(module.Failure, match="watch scope"):
        module.Smoke(args("object-smoke"), runner=kube).run()
    assert not any(command[0] in ("create", "delete") for _, command, _ in kube.events)


def test_operator_configmap_key_reference_is_resolved_without_secret_reads():
    module = load(); kube = Kube(namespace="object-smoke", watch="false")
    operator = kube.objects[("openshift-storage", "deployment", "rook-ceph-operator")]
    operator["spec"]["template"]["spec"]["containers"][0]["env"] = [{
        "name": "ROOK_OBC_WATCH_OPERATOR_NAMESPACE", "valueFrom": {"configMapKeyRef": {
            "name": "rook-ceph-operator-config", "key": "ROOK_OBC_WATCH_OPERATOR_NAMESPACE", "optional": True}}}]
    assert module.Smoke(args("object-smoke"), runner=kube).run()["status"] == "passed"
    assert all(command[-1] == "name" for _, command, _ in kube.events if command[:2] == ["get", "secret"])


def test_delete_uid_precondition_preserves_a_pod_replaced_after_the_last_get():
    module = load(); kube = Kube(race_delete=True)
    with pytest.raises(module.Failure, match="cleanup"):
        module.Smoke(args(), runner=kube).run()
    assert any(key[1] == "pod" and value["metadata"]["uid"] == "replacement" for key, value in kube.objects.items())


@pytest.mark.parametrize("kind", ["Pod", "ObjectBucketClaim"])
def test_create_timeout_after_commit_still_cleans_owned_resources(kind):
    module = load(); kube = Kube()
    def runner(command, **kwargs):
        response = kube(command, **kwargs)
        if "create" in command and json.loads(kwargs["input"])["kind"] == kind:
            raise subprocess.TimeoutExpired(command, 30)
        return response
    with pytest.raises(module.Failure, match="smoke failed.*cleanup verified"):
        module.Smoke(args(), runner=runner).run()
    assert not any(key[1] in ("pod", "objectbucketclaim", "objectbucket", "secret") for key in kube.objects)


def test_noobaa_backend_does_not_inherit_rook_obc_watch_restrictions():
    module = load(); kube = Kube(namespace="object-smoke", watch="true")
    sc = kube.objects[(None, "storageclass", "ocs-storagecluster-ceph-rgw")]
    sc["provisioner"] = "openshift-storage.noobaa.io/obc"
    sc["parameters"] = {"bucketclass": "noobaa-default-bucket-class"}
    kube.objects.pop(("openshift-storage", "deployment", "rook-ceph-operator"))
    kube.objects.pop(("openshift-storage", "configmap", "rook-ceph-operator-config"))
    kube.objects[("openshift-storage", "noobaa", "noobaa")] = obj("NooBaa", "noobaa", "openshift-storage", status={"phase": "Ready"})
    assert module.Smoke(args("object-smoke"), runner=kube).run()["status"] == "passed"


def test_cli_accepts_the_actual_dotted_mcg_storageclass(monkeypatch):
    module = load()
    class Passed:
        def __init__(self, a):
            assert a.storage_class == "openshift-storage.noobaa.io"
            assert a.operator_namespace == "openshift-storage"
        def run(self):
            return {"status": "passed"}
    monkeypatch.setattr(module, "Smoke", Passed)
    assert module.main(["--context", "target", "--namespace", "odf-object-smoke", "--storage-class",
        "openshift-storage.noobaa.io", "--image", "example.test/python:1"]) == 0


def test_cli_accepts_the_standard_dotted_service_ca_configmap(monkeypatch):
    module = load()
    class Passed:
        def __init__(self, a):
            assert a.ca_configmap == "openshift-service-ca.crt"
        def run(self):
            return {"status": "passed"}
    monkeypatch.setattr(module, "Smoke", Passed)
    assert module.main(["--context", "target", "--namespace", "openshift-storage", "--image",
        "example.test/python:1", "--tls-ca", "service-ca", "--ca-configmap", "openshift-service-ca.crt"]) == 0


def pruned_reference_runner(kube, *, preserves=False, contradictory=False, pending_orphan=False):
    kube.objects[(None, "customresourcedefinition", "objectbuckets.objectbucket.io")] = obj(
        "CustomResourceDefinition", "objectbuckets.objectbucket.io", spec={"group": "objectbucket.io",
        "names": {"kind": "ObjectBucket"}, "versions": [{"name": "v1alpha1", "served": True,
        "schema": {"openAPIV3Schema": {"type": "object", "properties": {"spec": {"type": "object", "properties": {"claimRef": {
            "type": "object", **({"x-kubernetes-preserve-unknown-fields": True} if preserves else {})}}}}}}}]})
    kube.objects[(None, "customresourcedefinition", "objectbuckets.objectbucket.io")]["apiVersion"] = "apiextensions.k8s.io/v1"
    def runner(command, **kwargs):
        is_obc_create = "create" in command and json.loads(kwargs["input"])["kind"] == "ObjectBucketClaim"
        orphan = None
        if pending_orphan and "delete" in command and "objectbucketclaims" in " ".join(command):
            orphan = copy.deepcopy(kube.objects.get((None, "objectbucket", "fake-global-object")))
        response = kube(command, **kwargs)
        if is_obc_create:
            payload = json.loads(kwargs["input"]);name = payload["metadata"]["name"];ns = payload["metadata"]["namespace"]
            claim = kube.objects[(ns, "objectbucketclaim", name)]
            claim["spec"]["bucketName"] = name + "-generated"
            bucket = kube.objects[(None, "objectbucket", "fake-global-object")]
            bucket["apiVersion"] = "objectbucket.io/v1alpha1"
            bucket["status"] = {"phase": "Bound"}
            bucket["spec"].update({"claimRef": {"name": "other"} if contradictory else {},
                "storageClassName": payload["spec"]["storageClassName"], "reclaimPolicy": "Delete",
                "endpoint": {"bucketName": claim["spec"]["bucketName"]}})
            if pending_orphan:
                claim["status"]["phase"] = "Pending";claim["spec"].pop("objectBucketName")
                raise subprocess.TimeoutExpired(command, 30)
        if orphan:
            kube.objects[(None, "objectbucket", "fake-global-object")] = orphan
        return response
    return runner


def test_schema_pruned_reverse_reference_uses_verified_forward_binding():
    module = load();kube = Kube()
    result = module.Smoke(args(), runner=pruned_reference_runner(kube)).run()
    assert result["status"] == "passed"
    assert result["binding_source"] == "claim-forward-reference"
    assert not any(key[1] in ("pod", "objectbucketclaim", "objectbucket", "secret") for key in kube.objects)


@pytest.mark.parametrize("scenario", ["preserves", "contradictory"])
def test_missing_or_contradictory_unpruned_reference_never_weakens_binding(scenario):
    module = load();kube = Kube()
    with pytest.raises(module.Failure):
        module.Smoke(args(), runner=pruned_reference_runner(kube, **{scenario: True})).run()
    assert not kube.executed


def test_pending_failed_create_cannot_hide_a_pruned_reference_orphan():
    module = load();kube = Kube()
    with pytest.raises(module.Failure, match="cleanup"):
        module.Smoke(args(), runner=pruned_reference_runner(kube, pending_orphan=True)).run()
    assert any(key[1] == "objectbucket" for key in kube.objects)


@pytest.mark.parametrize("scenario", ["preexisting", "bucket-name", "class", "policy", "claim-prefix", "replaced", "schema-change", "schema-properties"])
def test_forward_binding_rejects_identity_intent_and_schema_changes(scenario):
    module = load();kube = Kube()
    if scenario == "preexisting":
        kube.objects[(None, "objectbucket", "fake-global-object")] = obj("ObjectBucket", "fake-global-object", spec={"claimRef": {}})
    base = pruned_reference_runner(kube)
    reads = 0
    def runner(command, **kwargs):
        nonlocal reads
        response = base(command, **kwargs)
        if "create" in command and json.loads(kwargs["input"])["kind"] == "ObjectBucketClaim":
            payload = json.loads(kwargs["input"])
            claim = kube.objects[(payload["metadata"]["namespace"], "objectbucketclaim", payload["metadata"]["name"])]
            bucket = kube.objects[(None, "objectbucket", "fake-global-object")]
            if scenario == "bucket-name": bucket["spec"]["endpoint"]["bucketName"] = "different"
            if scenario == "class": bucket["spec"]["storageClassName"] = "different"
            if scenario == "policy": bucket["spec"]["reclaimPolicy"] = "Retain"
            if scenario == "claim-prefix": claim["spec"]["generateBucketName"] = "different"
            if scenario == "schema-properties":
                crd = kube.objects[(None, "customresourcedefinition", "objectbuckets.objectbucket.io")]
                crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["claimRef"]["properties"] = {"name": {"type": "string"}}
        if "get" in command and "customresourcedefinition" in command:
            reads += 1
            if scenario == "schema-change" and reads > 1:
                value = json.loads(response.stdout);value["metadata"]["uid"] = "replacement"
                response.stdout = json.dumps(value)
        if "get" in command and "objectbucket" in command and "fake-global-object" in command and kube.executed and scenario == "replaced":
            value = json.loads(response.stdout);value["metadata"]["uid"] = "replacement"
            response.stdout = json.dumps(value)
        return response
    with pytest.raises(module.Failure):
        module.Smoke(args(), runner=runner).run()
    if scenario not in ("schema-change", "replaced"):
        assert not kube.executed


@pytest.mark.parametrize("scenario", ["preserve-all", "foreign-orphan"])
def test_pruning_and_orphan_gates_fail_closed(scenario):
    module = load();kube = Kube()
    base = pruned_reference_runner(kube, pending_orphan=scenario == "foreign-orphan")
    if scenario == "preserve-all":
        kube.objects[(None, "customresourcedefinition", "objectbuckets.objectbucket.io")]["spec"]["preserveUnknownFields"] = True
    def runner(command, **kwargs):
        try:
            return base(command, **kwargs)
        finally:
            if scenario == "foreign-orphan":
                bucket = kube.objects.get((None, "objectbucket", "fake-global-object"))
                if bucket:
                    bucket["spec"]["claimRef"] = {"name": "other", "namespace": "other"}
    with pytest.raises(module.Failure, match="cleanup"):
        module.Smoke(args(), runner=runner).run()
    assert not kube.executed


def test_lost_forward_pointer_after_roundtrip_does_not_report_a_pass():
    module = load();kube = Kube()
    base = pruned_reference_runner(kube)
    def runner(command, **kwargs):
        response = base(command, **kwargs)
        if "exec" in command:
            for (ns, kind, name), value in kube.objects.items():
                if kind == "objectbucketclaim":
                    value["spec"].pop("objectBucketName")
        return response
    with pytest.raises(module.Failure, match="cleanup"):
        module.Smoke(args(), runner=runner).run()
