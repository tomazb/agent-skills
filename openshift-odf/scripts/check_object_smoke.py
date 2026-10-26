#!/usr/bin/env python3
"""Create a disposable OBC and client pod, verify S3 data, and verify cleanup.

Never deletes a namespace or reads Secret data. Run only as an authorized smoke
test. The supplied namespace must be the operator namespace or a labelled smoke
namespace compatible with the ODF RGW watch scope; MCG uses its NooBaa provisioner.
"""
import argparse
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.parse import quote

PART_OF = "app.kubernetes.io/part-of"
RUN = "storage-smoke/run"


class Failure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Failure(message)


class Smoke:
    def __init__(self, args, runner=subprocess.run):
        self.args = args
        self.runner = runner
        self.run_id = secrets.token_hex(8)
        self.name = "rgw-" + self.run_id + "-smoke"
        self.created = []
        self.bucket = None
        self.buckets = {}
        self.namespace_uid = None
        self.baseline_buckets = None
        self.reference_schema = None
        self.binding_source = "reverse-reference"

    def oc(self, *command, namespace=None, payload=None):
        argv = ["oc", "--context", self.args.context, "--request-timeout=5s"]
        if namespace:
            argv += ["-n", namespace]
        argv += list(command)
        try:
            result = self.runner(argv, input=payload, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise Failure("oc unavailable or timed out; operation unverified") from None
        require(result.returncode == 0, "oc/API/exec operation failed; result unverified")
        return result.stdout.strip()

    def get(self, kind, name, namespace=None, optional=False):
        raw = self.oc("get", kind, name, *(["--ignore-not-found"] if optional else []),
                      "-o", "json", namespace=namespace)
        if not raw and optional:
            return None
        try:
            obj = json.loads(raw)
            require(isinstance(obj["metadata"]["uid"], str) and bool(obj["metadata"]["uid"]),
                    "object identity unverified")
            return obj
        except (ValueError, KeyError, TypeError):
            raise Failure("object response or identity unverified") from None

    def wait(self, description, probe):
        deadline = time.monotonic() + self.args.timeout_seconds
        while True:
            value = probe()
            if value:
                return value
            remaining = deadline - time.monotonic()
            require(remaining > 0, "timed out: " + description)
            time.sleep(min(0.5, remaining))

    def preflight(self):
        a = self.args
        ns = self.get("namespace", a.namespace)
        self.namespace_uid = ns["metadata"]["uid"]
        require(not ns["metadata"].get("deletionTimestamp"), "namespace is terminating")
        if a.namespace != a.operator_namespace:
            require(a.namespace.endswith("-smoke") and ns["metadata"].get("labels", {}).get(PART_OF) == "storage-smoke",
                    "use a labelled disposable smoke namespace")
        sc = self.get("storageclass", a.storage_class)
        provisioner = sc.get("provisioner")
        rgw = a.operator_namespace + ".ceph.rook.io/bucket"
        mcg = a.operator_namespace + ".noobaa.io/obc"
        require(provisioner in (rgw, mcg), "StorageClass is not an ODF RGW/MCG provisioner")
        require(sc.get("reclaimPolicy", "Delete") == "Delete", "use a disposable Delete-policy bucket class")
        if provisioner == rgw:
            config = self.get("configmap", "rook-ceph-operator-config", a.operator_namespace, optional=True)
            watch = (config or {}).get("data", {}).get("ROOK_OBC_WATCH_OPERATOR_NAMESPACE", "true").lower()
            operator = self.get("deployment", "rook-ceph-operator", a.operator_namespace)
            for container in operator.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
                for variable in container.get("env", []):
                    if variable.get("name") == "ROOK_OBC_WATCH_OPERATOR_NAMESPACE":
                        if "value" in variable:
                            watch = variable["value"].lower()
                        else:
                            ref = variable.get("valueFrom", {}).get("configMapKeyRef", {})
                            require(ref.get("name") and ref.get("key"), "operator watch scope override is unresolved")
                            source = (config if ref["name"] == "rook-ceph-operator-config" else
                                      self.get("configmap", ref["name"], a.operator_namespace, optional=ref.get("optional", False)))
                            value = (source or {}).get("data", {}).get(ref["key"])
                            require(value is not None or ref.get("optional", False), "operator watch scope key is missing")
                            watch = value.lower() if value is not None else "true"
            require(watch in ("true", "false"), "OBC watch scope is unverified")
            require(watch == "false" or a.namespace == a.operator_namespace,
                    "namespace does not match the configured OBC watch scope")
            require(sc.get("parameters", {}).get("objectStoreNamespace") == a.operator_namespace,
                    "bucket store namespace mismatch")
        else:
            noobaa = self.get("noobaa", "noobaa", a.operator_namespace)
            require(noobaa.get("status", {}).get("phase") == "Ready", "NooBaa is not Ready")
        for kind in ("objectbucketclaim", "pod", "configmap"):
            require(self.get(kind, self.name, a.namespace, optional=True) is None,
                    "smoke object name already exists")
        # Names only: never load credential data into the local process.
        require(not self.oc("get", "secret", self.name, "--ignore-not-found", "-o", "name", namespace=a.namespace),
                "smoke credential name already exists")
        if a.ca_configmap:
            self.get("configmap", a.ca_configmap, a.namespace)
        self.scan_buckets()  # Prove global cleanup inventory access before creating anything.

    def track_bucket(self, bucket):
        metadata = bucket["metadata"]
        name, uid = metadata["name"], metadata["uid"]
        require(name not in self.baseline_buckets and uid not in self.baseline_buckets.values(),
                "ObjectBucket existed before this run")
        require(self.buckets.get(name, uid) == uid, "ObjectBucket identity changed")
        self.buckets[name] = uid

    def scan_buckets(self):
        try:
            items = json.loads(self.oc("get", "objectbucket", "-o", "json"))["items"]
            require(isinstance(items, list), "ObjectBucket inventory unverified")
            inventory = {}
            for bucket in items:
                metadata = bucket["metadata"]
                name, uid = metadata["name"], metadata["uid"]
                require(isinstance(name, str) and name and isinstance(uid, str) and uid
                        and name not in inventory, "ObjectBucket identity missing or duplicated")
                inventory[name] = uid
            if self.baseline_buckets is None:
                self.baseline_buckets = inventory
                return
            for bucket in items:
                metadata = bucket["metadata"]
                if metadata["name"] in self.baseline_buckets:
                    require(self.baseline_buckets[metadata["name"]] == metadata["uid"],
                            "baseline ObjectBucket identity changed")
                    continue
                spec = bucket.get("spec", {})
                ref = spec.get("claimRef")
                require(isinstance(ref, dict), "new ObjectBucket reference unverified")
                endpoint_name = spec.get("endpoint", {}).get("bucketName")
                run_bucket = isinstance(endpoint_name, str) and endpoint_name.startswith(self.name + "-")
                require(not run_bucket or ref == {} or (ref.get("name") == self.name
                        and ref.get("namespace") == self.args.namespace),
                        "run-prefixed ObjectBucket has a contradictory reference")
                if ref.get("name") == self.name and ref.get("namespace") == self.args.namespace:
                    expected_uid = self.created[0]["uid"] if self.created else None
                    require(not expected_uid or ref.get("uid", expected_uid) == expected_uid,
                            "ObjectBucket claim UID mismatch")
                    self.track_bucket(bucket)
                elif ref == {}:
                    endpoint = spec.get("endpoint", {})
                    bucket_name = endpoint.get("bucketName")
                    require(isinstance(bucket_name, str) and bucket_name,
                            "new empty-reference ObjectBucket identity unverified")
                    if bucket_name.startswith(self.name + "-"):
                        self.track_bucket(bucket)
                else:
                    require(ref.get("name") and ref.get("namespace"),
                            "new ObjectBucket reference incomplete")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise Failure("ObjectBucket inventory unverified") from None

    def verify_pruned_schema(self, bucket):
        crd = self.get("customresourcedefinition", "objectbuckets.objectbucket.io")
        spec = crd.get("spec", {})
        identity = (crd["metadata"]["uid"], spec)
        require(self.reference_schema is None or self.reference_schema == identity,
                "ObjectBucket schema changed")
        require(spec.get("group") == "objectbucket.io" and spec.get("names", {}).get("kind") == "ObjectBucket",
                "ObjectBucket schema identity unverified")
        require(crd.get("apiVersion") == "apiextensions.k8s.io/v1"
                and spec.get("preserveUnknownFields", False) is False
                and not any(c.get("type") == "NonStructuralSchema" and c.get("status") == "True"
                            for c in crd.get("status", {}).get("conditions", [])),
                "ObjectBucket structural pruning unverified")
        version = bucket.get("apiVersion", "").split("/")
        require(len(version) == 2 and version[0] == "objectbucket.io", "ObjectBucket API version unverified")
        versions = [v for v in spec.get("versions", []) if v.get("name") == version[1] and v.get("served") is True]
        require(len(versions) == 1, "ObjectBucket served schema unverified")
        root = versions[0].get("schema", {}).get("openAPIV3Schema", {})
        parent = root.get("properties", {}).get("spec", {})
        ref = parent.get("properties", {}).get("claimRef", {})
        require(root.get("type") == "object" and parent.get("type") == "object"
                and ref.get("type") == "object" and ref.get("properties", {}) == {}
                and all(not node.get("x-kubernetes-preserve-unknown-fields")
                        and node.get("additionalProperties", False) is False
                        and not any(key in node for key in ("allOf", "anyOf", "oneOf", "$ref"))
                        for node in (root, parent, ref)), "ObjectBucket schema does not prove reference pruning")
        self.reference_schema = identity

    def verify_claim_bucket(self, claim, *, bound=False):
        spec = claim.get("spec", {})
        record = self.created[0]
        require(claim["metadata"].get("labels", {}).get(RUN) == self.run_id
                and (record["uid"] is None or claim["metadata"]["uid"] == record["uid"])
                and spec.get("storageClassName") == self.args.storage_class
                and spec.get("generateBucketName") == self.name, "claim identity or intent changed")
        name = spec.get("objectBucketName")
        if not name:
            require(not bound and self.bucket is None, "claim lost its ObjectBucket forward binding")
            return
        bucket = self.get("objectbucket", name)
        self.track_bucket(bucket)
        require(self.bucket is None or self.bucket["metadata"]["name"] == name,
                "claim forward binding changed")
        ref = bucket.get("spec", {}).get("claimRef")
        if ref == {}:
            self.verify_pruned_schema(bucket)
            bucket_spec = bucket.get("spec", {})
            bucket_name = spec.get("bucketName")
            require(claim.get("status", {}).get("phase") == "Bound"
                    and bucket.get("status", {}).get("phase") == "Bound"
                    and bucket_spec.get("storageClassName") == self.args.storage_class
                    and bucket_spec.get("reclaimPolicy") == "Delete"
                    and isinstance(bucket_name, str) and bucket_name.startswith(self.name + "-")
                    and bucket_spec.get("endpoint", {}).get("bucketName") == bucket_name,
                    "ObjectBucket forward association unverified")
            self.binding_source = "claim-forward-reference"
        else:
            require(isinstance(ref, dict) and ref.get("name") == self.name
                    and ref.get("namespace") == self.args.namespace
                    and ref.get("uid", claim["metadata"]["uid"]) == claim["metadata"]["uid"],
                    "ObjectBucket claim association mismatch")
        self.bucket = bucket

    def create(self, kind, obj):
        obj["metadata"] = {"name": self.name, "namespace": self.args.namespace,
                           "labels": {PART_OF: "storage-smoke", RUN: self.run_id}}
        # Record the attempt before sending it: a timed-out request can commit.
        record = {"kind": kind, "uid": None}
        self.created.append(record)
        self.oc("create", "-f", "-", "-o", "json", namespace=self.args.namespace, payload=json.dumps(obj))
        current = self.get(kind, self.name, self.args.namespace)
        require(current["metadata"].get("labels", {}).get(RUN) == self.run_id, "created object ownership mismatch")
        record["uid"] = current["metadata"]["uid"]

    def execute(self):
        a = self.args
        self.create("objectbucketclaim", {"apiVersion": "objectbucket.io/v1alpha1", "kind": "ObjectBucketClaim",
            "spec": {"generateBucketName": self.name, "storageClassName": a.storage_class}})
        def bound():
            claim = self.get("objectbucketclaim", self.name, a.namespace)
            if claim.get("status", {}).get("phase") != "Bound":
                return None
            require(claim["metadata"]["uid"] == self.created[0]["uid"], "claim identity changed")
            return claim
        claim = self.wait("bucket claim Bound", bound)
        self.verify_claim_bucket(claim, bound=True)
        container = {"name": "s3", "image": a.image,
            "command": ["python3", "-c", "import time; time.sleep(3600)"],
            "envFrom": [{"configMapRef": {"name": self.name}}, {"secretRef": {"name": self.name}}],
            "env": [{"name": "RGW_ALLOW_HTTP", "value": str(a.allow_http).lower()},
                    {"name": "RGW_TLS_CA", "value": a.tls_ca}],
            "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"memory": "128Mi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True,
                                "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}}}
        pod = {"apiVersion": "v1", "kind": "Pod", "spec": {"restartPolicy": "Never",
                "automountServiceAccountToken": False, "containers": [container]}}
        if a.ca_configmap:
            container["volumeMounts"] = [{"name": "ca", "mountPath": "/etc/rgw-ca", "readOnly": True}]
            pod["spec"]["volumes"] = [{"name": "ca", "configMap": {"name": a.ca_configmap}}]
        self.create("pod", pod)
        def ready():
            current = self.get("pod", self.name, a.namespace)
            require(current["metadata"]["uid"] == self.created[-1]["uid"]
                    and current["metadata"].get("labels", {}).get(RUN) == self.run_id,
                    "client pod identity changed")
            return any(c.get("type") == "Ready" and c.get("status") == "True"
                       for c in current.get("status", {}).get("conditions", []))
        self.wait("client pod Ready", ready)
        source = Path(__file__).with_name("rgw_s3_roundtrip.py").read_text(encoding="utf-8")
        output = self.oc("exec", "-i", self.name, "--", "python3", "-", namespace=a.namespace, payload=source)
        try:
            result = json.loads(output)
        except ValueError:
            raise Failure("S3 smoke result malformed") from None
        require(result.get("status") == "passed" and result.get("put_get_compare_delete") is True,
                "S3 roundtrip did not pass")

    def cleanup(self):
        if not self.created:
            return
        a = self.args
        require(self.get("namespace", a.namespace)["metadata"]["uid"] == self.namespace_uid,
                "cleanup namespace identity changed")
        self.scan_buckets()
        for record in reversed(self.created):
            kind = record["kind"]
            current = self.get(kind, self.name, a.namespace, optional=True)
            if current is not None:
                require(current["metadata"].get("labels", {}).get(RUN) == self.run_id
                        and (record["uid"] is None or current["metadata"]["uid"] == record["uid"]),
                        "cleanup object identity changed")
                if kind == "objectbucketclaim":
                    self.verify_claim_bucket(current)
                # A separate GET/UID check cannot protect a name-based DELETE
                # against replacement between requests. Enforce identity in the
                # API transaction itself. Raw DELETE accepts DeleteOptions stdin.
                prefix = "/api/v1" if kind == "pod" else "/apis/objectbucket.io/v1alpha1"
                plural = "pods" if kind == "pod" else "objectbucketclaims"
                path = prefix + "/namespaces/" + quote(a.namespace, safe="") + "/" + plural + "/" + self.name
                preconditions = {"uid": current["metadata"]["uid"]}
                if current["metadata"].get("resourceVersion"):
                    preconditions["resourceVersion"] = current["metadata"]["resourceVersion"]
                options = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": preconditions}
                self.oc("delete", "--raw", path, "-f", "-", namespace=a.namespace, payload=json.dumps(options))
                self.wait("owned object deletion", lambda: self.get(kind, self.name, a.namespace, optional=True) is None)
        # Re-scan after deletion as an unbound claim can finish provisioning
        # during a timeout. Never manually delete a global ObjectBucket.
        def buckets_gone():
            self.scan_buckets()
            left = False
            for name, uid in self.buckets.items():
                current = self.get("objectbucket", name, optional=True)
                if current:
                    require(current["metadata"]["uid"] == uid, "ObjectBucket identity changed")
                    left = True
            return not left
        self.wait("ObjectBucket deletion", buckets_gone)
        for kind in ("secret", "configmap"):
            self.wait("OBC companion deletion", lambda: not self.oc("get", kind, self.name,
                "--ignore-not-found", "-o", "name", namespace=a.namespace))

    def run(self):
        self.preflight()
        failure = None
        try:
            self.execute()
        except (Exception, KeyboardInterrupt) as error:
            # Attempt guarded cleanup even when Ctrl-C interrupts a resource creation.
            failure = error
        try:
            self.cleanup()
        except (Exception, KeyboardInterrupt):
            raise Failure("smoke cleanup unverified; preserve namespace and inspect owned resources") from None
        if isinstance(failure, KeyboardInterrupt):
            raise Failure("S3 smoke interrupted; owned-resource cleanup verified") from None
        if failure:
            raise Failure("S3 smoke failed; owned-resource cleanup verified") from None
        return {"status": "passed", "put_get_compare_delete": True, "cleanup_verified": True,
                "binding_source": self.binding_source}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--operator-namespace", default="openshift-storage")
    parser.add_argument("--storage-class", default="ocs-storagecluster-ceph-rgw")
    parser.add_argument("--image", required=True, help="pinned image with Python 3 and restricted-SCC support")
    parser.add_argument("--allow-http", action="store_true", help="trust the in-cluster HTTP path explicitly")
    parser.add_argument("--tls-ca", default="public", help="public, service-ca, or a mounted CA file path")
    parser.add_argument("--ca-configmap")
    parser.add_argument("--timeout-seconds", type=float, default=180)
    a = parser.parse_args(argv)
    label = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    names = [a.namespace, a.operator_namespace]
    subdomains = [a.storage_class] + ([a.ca_configmap] if a.ca_configmap else [])
    valid_subdomains = all(len(value) <= 253 and all(re.fullmatch(label, part) and len(part) <= 63
                           for part in value.split(".")) for value in subdomains)
    if (not a.context.strip() or not all(re.fullmatch(label, x) and len(x) <= 63 for x in names)
            or a.operator_namespace != "openshift-storage"
            or not valid_subdomains or not math.isfinite(a.timeout_seconds) or a.timeout_seconds <= 0
            or not ("@sha256:" in a.image or ":" in a.image.rsplit("/", 1)[-1]) or a.image.endswith(":latest")
            or (a.tls_ca != "public" and not a.ca_configmap)
            or (a.tls_ca not in ("public", "service-ca") and not a.tls_ca.startswith("/etc/rgw-ca/"))):
        print("STOP: invalid smoke target, image, timeout, or TLS trust configuration", file=sys.stderr)
        return 2
    try:
        print(json.dumps(Smoke(a).run()))
        return 0
    except Failure as error:
        print("STOP: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # run() catches interruption after provisioning; preflight is read-only.
        print("STOP: interrupted during read-only smoke preflight", file=sys.stderr)
        return 130
    except Exception:
        print("STOP: malformed or unverified smoke input/result", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
