#!/usr/bin/env python3
"""Round-trip CSI snapshots of explicitly labelled, disposable smoke sources.

Requires oc and a source image providing sh, test, printf, cat, dd, and sync.
Writes snapshot-probe on filesystems, or exactly 64 bytes at block offset zero.
Never creates/deletes a namespace, source PVC, source pod, or original class.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal, InvalidOperation
import json
import posixpath
import re
import secrets
import subprocess
import sys
import time

PART_OF = "app.kubernetes.io/part-of"
RUN = "storage-smoke/run"
API = "snapshot.storage.k8s.io/v1"
KINDS = {"VolumeSnapshotClass": "volumesnapshotclass", "VolumeSnapshot": "volumesnapshot",
         "PersistentVolumeClaim": "persistentvolumeclaim", "Pod": "pod"}


class Failure(Exception):
    """An operation could not be safely verified."""


def require(condition, message):
    if not condition:
        raise Failure(message)


def ready(obj):
    return any(c.get("type") == "Ready" and c.get("status") == "True"
               for c in obj.get("status", {}).get("conditions", []))


def size_bytes(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGTPE]i|[kKMGTPE]|[eE][+-]?[0-9]+)?", str(value))
    require(match is not None, "invalid snapshot restore size")
    number, suffix = match.groups()
    suffix = suffix or ""
    if suffix.endswith("i"):
        multiplier = Decimal(1024) ** ("KMGTPE".index(suffix[0]) + 1)
    elif suffix and suffix[0] in "eE" and len(suffix) > 1:
        multiplier = Decimal(10) ** int(suffix[1:])
    else:
        multiplier = Decimal(1000) ** ("kMGTPE".index(suffix.replace("K", "k")) + 1) if suffix else 1
    result = Decimal(number) * multiplier
    require(result > 0 and result == int(result), "invalid snapshot restore size")
    return int(result)


class Smoke:
    def __init__(self, args):
        self.args = args
        self.run_id = secrets.token_hex(8)
        self.name = "snapshot-smoke-" + self.run_id
        self.created = []
        self.contents = set()
        self.pvs = set()
        self.snapshot_uid = None
        self.snapshot_error_seen = False

    def oc(self, *args, namespace=None, payload=None):
        command = ["oc", "--context", self.args.context, "--request-timeout=5s"]
        if namespace:
            command += ["-n", namespace]
        command += list(args)
        try:
            result = subprocess.run(command, input=json.dumps(payload) if payload else None,
                                    capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise Failure("oc unavailable or command timed out; operation unverified") from None
        require(result.returncode == 0, "oc operation failed; access/API/exec result unverified")
        return result.stdout.strip()

    def get(self, kind, name, namespace=None, optional=False):
        flags = ["--ignore-not-found"] if optional else []
        raw = self.oc("get", kind, name, *flags, "-o", "json", namespace=namespace)
        require(bool(raw) or optional, "empty API response")
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except ValueError:
            raise Failure("invalid API response") from None
        require(isinstance(obj, dict) and obj.get("metadata", {}).get("uid"), "unverified object identity")
        return obj

    def scan_contents(self):
        raw = self.oc("get", "volumesnapshotcontent", "-o", "json")
        try:
            objects = json.loads(raw)["items"]
        except (ValueError, KeyError, TypeError):
            raise Failure("snapshot content inventory unverified") from None
        require(isinstance(objects, list), "snapshot content inventory unverified")
        for content in objects:
            ref = content.get("spec", {}).get("volumeSnapshotRef", {})
            if ref.get("name") == self.name and ref.get("namespace") == self.args.namespace:
                name = content.get("metadata", {}).get("name")
                require(name, "snapshot content identity missing")
                self.contents.add(name)
                require(not self.snapshot_uid or ref.get("uid") == self.snapshot_uid,
                        "snapshot content UID association mismatch")

    def wait(self, description, probe):
        deadline = time.monotonic() + self.args.timeout_seconds
        while True:
            value = probe()
            if value:
                return value
            remaining = deadline - time.monotonic()
            require(remaining > 0, "timed out: " + description)
            time.sleep(min(0.2, remaining))

    def labelled(self, obj):
        require(obj.get("metadata", {}).get("labels", {}).get(PART_OF) == "storage-smoke",
                "namespace, source PVC and writer must carry the storage-smoke label")
        require(not obj["metadata"].get("deletionTimestamp"), "source object is terminating")

    def preflight(self):
        a = self.args
        self.labelled(self.get("namespace", a.namespace))
        self.source = self.get("persistentvolumeclaim", a.source_pvc, a.namespace)
        self.writer = self.get("pod", a.writer_pod, a.namespace)
        self.labelled(self.source)
        self.labelled(self.writer)
        spec = self.source["spec"]
        require(self.source.get("status", {}).get("phase") == "Bound", "source PVC must be Bound")
        require(ready(self.writer), "source writer must be Ready")
        require(spec.get("storageClassName") and spec.get("volumeName"), "source storage identity missing")
        self.sc = self.get("storageclass", spec["storageClassName"])
        require(self.sc.get("reclaimPolicy", "Delete") == "Delete",
                "use a disposable StorageClass with reclaimPolicy Delete; Retain cleanup is unsafe")
        self.pv = self.get("persistentvolume", spec["volumeName"])
        ref = self.pv.get("spec", {}).get("claimRef", {})
        require(ref.get("uid") == self.source["metadata"]["uid"] and ref.get("name") == a.source_pvc
                and ref.get("namespace") == a.namespace, "source PV association mismatch")
        self.snapshot_class = self.get("volumesnapshotclass", a.snapshot_class)
        self.scan_contents()  # Verify cleanup inventory access before touching the source.
        driver = self.sc.get("provisioner")
        self.csi = self.pv["spec"].get("csi", {})
        require(driver and self.snapshot_class.get("driver") == driver and self.csi.get("driver") == driver
                and self.csi.get("volumeHandle"), "source and snapshot class driver mismatch")
        require(self.snapshot_class.get("deletionPolicy") in ("Delete", "Retain"), "invalid snapshot deletion policy")
        scp, snp = self.sc.get("parameters", {}), self.snapshot_class.get("parameters", {})
        require(driver != "driver.longhorn.io" or snp.get("type") == "snap",
                "Longhorn local snapshot smoke requires parameters.type=snap; bak is an external backup")
        for key in ("clusterID", "pool", "fsName", "journalPool", "dataPool", "dataEngine", "backingImage",
                    "csi.storage.k8s.io/snapshotter-secret-name", "csi.storage.k8s.io/snapshotter-secret-namespace"):
            require(key not in scp or key not in snp or scp[key] == snp[key], "snapshot backend parameter mismatch")
        secret_name = snp.get("csi.storage.k8s.io/snapshotter-secret-name")
        secret_ns = snp.get("csi.storage.k8s.io/snapshotter-secret-namespace")
        require(bool(secret_name) == bool(secret_ns), "incomplete snapshot credentials reference")
        if secret_name:
            require("$" not in secret_name + secret_ns, "templated snapshot credentials need manual validation")
            # Metadata-only output: never retrieve or print secret contents.
            require(self.oc("get", "secret", secret_name, "-o", "name", namespace=secret_ns),
                    "snapshot credentials unavailable")
        self.mode = spec.get("volumeMode", "Filesystem")
        require(self.mode in ("Filesystem", "Block") and spec.get("accessModes"), "unsupported source volume mode")
        podspec = self.writer["spec"]
        require(podspec.get("nodeName"), "source writer node missing")
        require(not any(podspec.get(k) for k in ("hostPID", "hostIPC", "hostNetwork")), "unsafe source pod host access")
        require(not any("hostPath" in v for v in podspec.get("volumes", [])), "hostPath writer is unsafe")
        volumes = [v for v in podspec.get("volumes", []) if
                   v.get("persistentVolumeClaim", {}).get("claimName") == a.source_pvc]
        require(len(volumes) == 1 and not volumes[0]["persistentVolumeClaim"].get("readOnly"),
                "writer must reference the writable source PVC exactly once")
        field, pathkey = ("volumeDevices", "devicePath") if self.mode == "Block" else ("volumeMounts", "mountPath")
        matches = [(c, m) for c in podspec.get("containers", []) for m in c.get(field, [])
                   if m.get("name") == volumes[0]["name"]]
        require(len(matches) == 1, "source must have exactly one writer mount/device association")
        self.container, mount = matches[0]
        self.path = mount.get(pathkey, "")
        require(self.path.startswith("/") and self.path != "/" and posixpath.normpath(self.path) == self.path
                and not mount.get("subPath") and not mount.get("subPathExpr") and not mount.get("readOnly"),
                "unsafe source mount/device path")
        require(self.container.get("image") and self.container.get("name"), "source container identity missing")
        require(not self.container.get("securityContext", {}).get("privileged"), "privileged writer is unsafe")
        if self.mode == "Block":
            require(re.fullmatch(r"/dev/[a-zA-Z0-9_-]+", self.path)
                    and not re.fullmatch(r"/dev/(?:[shv]d[a-z]+\d*|nvme\d+n\d+(?:p\d+)?|dm-\d+|loop\d+|root)", self.path),
                    "unsafe raw block device path; use a dedicated named volumeDevice")

    def create(self, kind, spec):
        namespace = None if kind == "VolumeSnapshotClass" else self.args.namespace
        metadata = {"name": self.name, "labels": {PART_OF: "storage-smoke", RUN: self.run_id}}
        if namespace:
            metadata["namespace"] = namespace
        obj = {"apiVersion": API if kind.startswith("VolumeSnapshot") else "v1", "kind": kind,
               "metadata": metadata}
        obj.update(spec)
        # Record before request: a timed-out create may still have reached the API.
        self.created.append((KINDS[kind], self.name, namespace))
        self.oc("create", "-f", "-", "-o", "json", namespace=namespace, payload=obj)

    def token(self, pod, container, path, value=None):
        if self.mode == "Block":
            script = 'test -b "$1"; '
            script += ('printf %s "$2" | dd of="$1" bs=1 count=64 conv=notrunc; sync' if value else
                       'dd if="$1" bs=1 count=64 2>/dev/null')
        else:
            script = 'test -d "$1"; test ! -L "$1/snapshot-probe"; '
            script += ('printf %s "$2" > "$1/snapshot-probe"; sync' if value else 'cat "$1/snapshot-probe"')
        args = ["exec", pod, "-c", container, "--", "sh", "-ceu", script, "snapshot-probe", path]
        if value:
            args.append(value)
        return self.oc(*args, namespace=self.args.namespace)

    def snapshot_ready(self):
        snap = self.get("volumesnapshot", self.name, self.args.namespace)
        self.snapshot_uid = snap["metadata"]["uid"]
        status = snap.get("status", {})
        if status.get("boundVolumeSnapshotContentName"):
            self.contents.add(status["boundVolumeSnapshotContentName"])
        # The controller retries and clears its last observed error upon success.
        # Track a boolean only: controller error details may contain secret data.
        self.snapshot_error_seen |= bool(status.get("error"))
        return snap if status.get("readyToUse") is True and not status.get("error") else None

    def verify_content(self, snap):
        status = snap["status"]
        require(status.get("boundVolumeSnapshotContentName") and status.get("restoreSize"),
                "snapshot binding or restore size missing")
        content = self.get("volumesnapshotcontent", status["boundVolumeSnapshotContentName"])
        spec, cstatus = content.get("spec", {}), content.get("status", {})
        ref = spec.get("volumeSnapshotRef", {})
        require(ref.get("uid") == snap["metadata"]["uid"] and ref.get("name") == self.name
                and ref.get("namespace") == self.args.namespace, "snapshot content association mismatch")
        require(spec.get("volumeSnapshotClassName") == snap["spec"]["volumeSnapshotClassName"],
                "snapshot content class association mismatch")
        require(spec.get("sourceVolumeMode", self.mode) == self.mode, "snapshot content volume mode mismatch")
        require(spec.get("driver") == self.sc["provisioner"] and spec.get("deletionPolicy") == "Delete"
                and spec.get("source", {}).get("volumeHandle") == self.csi["volumeHandle"],
                "snapshot content source/driver/policy mismatch")
        require(cstatus.get("readyToUse") is True and not cstatus.get("error") and cstatus.get("snapshotHandle"),
                "snapshot content is not ready")
        require(size_bytes(status["restoreSize"]) == size_bytes(cstatus.get("restoreSize", "")),
                "snapshot restore sizes disagree")
        return str(status["restoreSize"])

    def reader_manifest(self):
        podspec = self.writer["spec"]
        security = copy.deepcopy(podspec.get("securityContext", {}))
        security.update({"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}})
        container_security = {k: copy.deepcopy(v) for k, v in self.container.get("securityContext", {}).items()
                              if k in ("runAsUser", "runAsGroup", "seLinuxOptions")}
        container_security.update({"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                   "capabilities": {"drop": ["ALL"]}})
        container = {"name": "reader", "image": self.container["image"],
                     "command": ["sh", "-ceu", "while :; do sleep 10; done"], "securityContext": container_security}
        if self.mode == "Block":
            container["volumeDevices"] = [{"name": "restored", "devicePath": "/dev/snapshot-restored"}]
        else:
            # The new clone needs a writable mount for kubelet SELinux relabeling
            # on OpenShift (notably CephFS/NFS). The reader still only reads data.
            container["volumeMounts"] = [{"name": "restored", "mountPath": "/snapshot-restored", "readOnly": False}]
        spec = {"restartPolicy": "Never", "terminationGracePeriodSeconds": 1, "automountServiceAccountToken": False,
                "securityContext": security, "containers": [container], "volumes": [{"name": "restored",
                "persistentVolumeClaim": {"claimName": self.name, "readOnly": self.mode == "Block"}}],
                "affinity": {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [{"matchFields": [{"key": "metadata.name", "operator": "In",
                                                           "values": [podspec["nodeName"]]}]}]}}}}
        for key in ("serviceAccountName", "imagePullSecrets", "tolerations"):
            if key in podspec:
                spec[key] = copy.deepcopy(podspec[key])
        return {"spec": spec}

    def execute(self):
        self.preflight()
        token = secrets.token_hex(32)
        self.token(self.args.writer_pod, self.container["name"], self.path, token)
        require(self.token(self.args.writer_pod, self.container["name"], self.path) == token,
                "source token write/read failed")
        class_name = self.args.snapshot_class
        if self.snapshot_class["deletionPolicy"] == "Retain":
            self.create("VolumeSnapshotClass", {"driver": self.snapshot_class["driver"], "deletionPolicy": "Delete",
                                               "parameters": self.snapshot_class.get("parameters", {})})
            class_name = self.name
        self.create("VolumeSnapshot", {"spec": {"volumeSnapshotClassName": class_name,
                                                "source": {"persistentVolumeClaimName": self.args.source_pvc}}})
        try:
            snap = self.wait("snapshot readyToUse", self.snapshot_ready)
        except Failure as exc:
            # Do not mask access/API errors that are unrelated to the timeout.
            if str(exc) == "timed out: snapshot readyToUse" and self.snapshot_error_seen:
                raise Failure("snapshot controller reported an error") from None
            raise
        restore_size = self.verify_content(snap)
        mutated = secrets.token_hex(32)
        self.token(self.args.writer_pod, self.container["name"], self.path, mutated)
        require(self.token(self.args.writer_pod, self.container["name"], self.path) == mutated,
                "source token mutation unverified")
        source = self.source["spec"]
        self.create("PersistentVolumeClaim", {"spec": {"storageClassName": source["storageClassName"],
            "accessModes": source["accessModes"], "volumeMode": self.mode,
            "resources": {"requests": {"storage": restore_size}}, "dataSource": {"apiGroup": "snapshot.storage.k8s.io",
            "kind": "VolumeSnapshot", "name": self.name}}})
        # Create the consumer BEFORE waiting for Bound, including WFFC/local LVMS.
        self.create("Pod", self.reader_manifest())
        self.wait("restore PVC Bound", lambda: self.restore_bound())
        self.wait("reader Ready", lambda: ready(self.get("pod", self.name, self.args.namespace)))
        path = "/dev/snapshot-restored" if self.mode == "Block" else "/snapshot-restored"
        require(self.token(self.name, "reader", path) == token, "restored token mismatch")

    def restore_bound(self):
        pvc = self.get("persistentvolumeclaim", self.name, self.args.namespace)
        self.capture_pv(pvc)
        return pvc.get("status", {}).get("phase") == "Bound"

    def capture_pv(self, pvc):
        name = pvc.get("spec", {}).get("volumeName")
        if name:
            self.pvs.add(name)
            pv = self.get("persistentvolume", name)
            if pv:
                ref = pv.get("spec", {}).get("claimRef", {})
                require(ref.get("uid") == pvc["metadata"]["uid"] and ref.get("name") == self.name
                        and ref.get("namespace") == self.args.namespace, "restore PV association mismatch")
                require(pv["spec"].get("persistentVolumeReclaimPolicy") == "Delete", "restore PV is not disposable")
                require(pv["spec"].get("storageClassName") == self.source["spec"]["storageClassName"]
                        and pv["spec"].get("volumeMode", "Filesystem") == self.mode
                        and pv["spec"].get("csi", {}).get("driver") == self.sc["provisioner"]
                        and pv["spec"].get("csi", {}).get("volumeHandle")
                        and pv["spec"]["csi"]["volumeHandle"] != self.csi["volumeHandle"],
                        "restore PV driver/class/mode mismatch")

    def delete_owned(self, kind, name, namespace, obj):
        require(obj["metadata"].get("labels", {}).get(RUN) == self.run_id,
                "resource ownership changed; refusing deletion")
        self.oc("delete", kind, name, "--wait=false", namespace=namespace)
        self.wait("cleanup " + kind, lambda: self.get(kind, name, namespace, optional=True) is None)

    def cleanup(self):
        errors, classes = [], []
        snapshot_clean = True
        for kind, name, namespace in reversed(self.created):
            if kind == "volumesnapshotclass":
                classes.append((kind, name, namespace))
                continue
            try:
                obj = self.get(kind, name, namespace, optional=True)
                if obj is None:
                    if kind == "volumesnapshot":
                        self.scan_contents()
                    continue
                require(obj["metadata"].get("labels", {}).get(RUN) == self.run_id,
                        "resource ownership changed; refusing deletion")
                if kind == "volumesnapshot":
                    self.snapshot_uid = obj["metadata"]["uid"]
                    try:
                        self.scan_contents()
                    except Failure:
                        snapshot_clean = False
                        errors.append("snapshot content inventory/association")
                    content = obj.get("status", {}).get("boundVolumeSnapshotContentName")
                    if content:
                        self.contents.add(content)
                if kind == "persistentvolumeclaim":
                    try:
                        self.capture_pv(obj)
                    except Failure:
                        errors.append("restore PV verification")
                self.delete_owned(kind, name, namespace, obj)
            except Failure:
                if kind == "volumesnapshot":
                    snapshot_clean = False
                errors.append(kind + "/" + name)
        if any(k == "volumesnapshot" for k, _, _ in self.created):
            try:
                self.scan_contents()
            except Failure:
                snapshot_clean = False
                errors.append("snapshot content inventory/association")
        for kind, names in (("volumesnapshotcontent", self.contents), ("persistentvolume", self.pvs)):
            for name in sorted(names):
                try:
                    self.wait("cleanup " + kind, lambda k=kind, n=name: self.get(k, n, optional=True) is None)
                except Failure:
                    if kind == "volumesnapshotcontent":
                        snapshot_clean = False
                    errors.append(kind + "/" + name)
        # Keep credentials/parameters available for retry while snapshot cleanup is unverified.
        for kind, name, namespace in classes:
            if not snapshot_clean:
                errors.append(kind + "/" + name + " (retained for snapshot cleanup retry)")
                continue
            try:
                obj = self.get(kind, name, namespace, optional=True)
                if obj is not None:
                    self.delete_owned(kind, name, namespace, obj)
            except Failure:
                errors.append(kind + "/" + name)
        require(not errors, "cleanup incomplete: " + ", ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("context", "namespace", "source-pvc", "writer-pod", "snapshot-class"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?-smoke", args.namespace):
        parser.error("namespace must end in -smoke and identify a disposable smoke namespace")
    if not args.context.strip() or not 1 <= args.timeout_seconds <= 3600:
        parser.error("explicit context and timeout between 1 and 3600 seconds required")
    smoke = Smoke(args)
    errors = []
    try:
        smoke.execute()
    except (Failure, KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        # Only deliberate Failure text is safe to display; raw API/exec output never is.
        error = sys.exc_info()[1]
        errors.append(str(error) if isinstance(error, Failure) else "invalid or incomplete API object")
    finally:
        try:
            smoke.cleanup()
        except (Failure, KeyError, TypeError, ValueError, AttributeError):
            error = sys.exc_info()[1]
            errors.append(str(error) if isinstance(error, Failure) else "cleanup could not be verified")
    if errors:
        print("Snapshot smoke failed: " + "; ".join(errors), file=sys.stderr)
        return 1
    print("Snapshot round-trip verified; helper-created snapshot, restore PVC/PV and reader cleaned up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
