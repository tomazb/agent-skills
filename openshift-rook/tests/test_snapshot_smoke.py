"""CLI contracts against a stateful oc double; no cluster or third-party runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_snapshot_smoke.py"
LABEL = {"app.kubernetes.io/part-of": "storage-smoke"}

FAKE_OC = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ["FAKE_STATE"])
s = json.loads(path.read_text())
a = sys.argv[1:]
s["calls"].append(a)
def finish(value=None, code=0):
    path.write_text(json.dumps(s))
    if value is not None:
        print(json.dumps(value) if isinstance(value, (dict, list)) else value)
    sys.exit(code)
assert a[:2] == ["--context", "target"]
assert a[2].startswith("--request-timeout=")
a = a[3:]
ns = ""
if a[:1] == ["-n"]:
    ns, a = a[1], a[2:]
verb = a[0]
scenario = s.get("scenario", "")
if verb == "get":
    if a[1:3] == ["volumesnapshotcontent", "-o"]:
        if scenario == "content-list-forbidden":
            finish("Forbidden private-secret-value", 1)
        finish({"items": [o for k, o in s["objects"].items() if k.startswith("volumesnapshotcontent/")]})
    kind, name = a[1:3]
    if scenario == "forbidden" and kind == "volumesnapshotclass":
        finish("Forbidden private-secret-value", 1)
    obj = s["objects"].get(kind + "/" + name)
    if kind == "persistentvolumeclaim" and obj and name != "source":
        if scenario == "restore-api-error":
            finish("Forbidden", 1)
        if not any(k.startswith("pod/snapshot-smoke-") for k in s["objects"]):
            obj["status"]["phase"] = "Pending"
    if kind == "volumesnapshot" and obj:
        if scenario == "snapshot-pending":
            obj["status"] = {}
        elif scenario == "snapshot-error":
            obj["status"]["error"] = {"message": "private-secret-value"}
    if kind == "pod" and obj and name != "writer" and scenario == "ownership-changed":
        obj["metadata"]["labels"]["storage-smoke/run"] = "different-owner"
    if kind == "secret" and obj:
        assert a[-2:] == ["-o", "name"], "secret data must never be fetched"
        finish("secret/credentials")
    if obj is None:
        if "--ignore-not-found" in a:
            finish()
        finish("NotFound private-secret-value", 1)
    finish(obj)
if verb == "create":
    obj = json.load(sys.stdin)
    mapping = {"VolumeSnapshotClass": "volumesnapshotclass", "VolumeSnapshot": "volumesnapshot",
               "PersistentVolumeClaim": "persistentvolumeclaim", "Pod": "pod"}
    kind = mapping[obj["kind"]]
    name = obj["metadata"]["name"]
    obj["metadata"]["uid"] = name + "-uid"
    s["created"].append(obj)
    if kind == "volumesnapshot":
        s["snap_token"] = s.get("source_token")
        content = "content-" + name
        obj["status"] = {"readyToUse": True, "boundVolumeSnapshotContentName": content,
                          "restoreSize": "1536Mi"}
        ref = {"name": name, "namespace": ns, "uid": obj["metadata"]["uid"]}
        vsc = {"metadata": {"name": content, "uid": content + "-uid"},
               "spec": {"driver": s["objects"]["storageclass/source-sc"]["provisioner"], "deletionPolicy": "Delete",
                        "source": {"volumeHandle": "source-handle"}, "volumeSnapshotRef": ref,
                        "volumeSnapshotClassName": obj["spec"]["volumeSnapshotClassName"]},
               "status": {"readyToUse": True, "restoreSize": 1610612736,
                          "snapshotHandle": "snapshot-handle"}}
        if scenario == "content-mismatch":
            vsc["spec"]["source"]["volumeHandle"] = "other-handle"
        if scenario == "content-uid-mismatch":
            vsc["spec"]["volumeSnapshotRef"]["uid"] = "other-snapshot-uid"
        if scenario == "content-size-mismatch":
            vsc["status"]["restoreSize"] = 4096
        s["objects"]["volumesnapshotcontent/" + content] = vsc
    if kind == "persistentvolumeclaim":
        obj["status"] = {"phase": "Bound"}
        obj["spec"]["volumeName"] = "restore-pv"
        s["objects"]["persistentvolume/restore-pv"] = {
            "metadata": {"name": "restore-pv", "uid": "restore-pv-uid"},
            "spec": {"persistentVolumeReclaimPolicy": "Delete", "storageClassName": "source-sc",
                "volumeMode": s["objects"]["persistentvolumeclaim/source"]["spec"]["volumeMode"],
                "csi": {"driver": s["objects"]["storageclass/source-sc"]["provisioner"], "volumeHandle": "restored-handle"}, "claimRef": {
                "namespace": ns, "name": name, "uid": obj["metadata"]["uid"]}}}
    if kind == "pod" and scenario == "reader-create-fails":
        finish("Forbidden private-secret-value", 1)
    if kind == "pod":
        obj["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
    s["objects"][kind + "/" + name] = obj
    if (scenario == "create-response-lost" and kind == "volumesnapshot") or (
            scenario == "pvc-create-response-lost" and kind == "persistentvolumeclaim"):
        finish("private-secret-value", 1)
    finish(obj)
if verb == "exec":
    pod = a[1]
    command = a[a.index("--") + 1:]
    script = command[2]
    if scenario == "selinux-relabel" and pod != "writer":
        reader = s["objects"]["pod/" + pod]["spec"]
        mount = reader["containers"][0]["volumeMounts"][0]
        claim = reader["volumes"][0]["persistentVolumeClaim"]
        if mount.get("readOnly") or claim.get("readOnly"):
            finish("Permission denied: restored filesystem was not relabelled", 1)
    if "printf" in script:
        assert pod == "writer", "reader must never write"
        s["writes"].append(command)
        s["source_token"] = command[-1]
        finish()
    token = s.get("source_token", "") if pod == "writer" else s.get("snap_token", "")
    finish("wrong-token" if scenario == "restore-mismatch" and pod != "writer" else token)
if verb == "delete":
    kind, name = a[1:3]
    obj = s["objects"].get(kind + "/" + name)
    assert obj and obj["metadata"].get("labels", {}).get("storage-smoke/run"), "unowned delete"
    if scenario == "snapshot-delete-fails" and kind == "volumesnapshot":
        finish("Forbidden private-secret-value", 1)
    s["deleted"].append([kind, name])
    del s["objects"][kind + "/" + name]
    if kind == "volumesnapshot" and scenario != "content-remains":
        for key in list(s["objects"]):
            if key.startswith("volumesnapshotcontent/"):
                del s["objects"][key]
    if kind == "persistentvolumeclaim" and scenario != "pv-remains":
        s["objects"].pop("persistentvolume/restore-pv", None)
    finish()
finish("unexpected command", 99)
'''


def initial(mode="Filesystem", policy="Delete"):
    def meta(name):
        return {"name": name, "uid": name + "-uid", "labels": dict(LABEL)}
    container = {"name": "writer", "image": "example.invalid/smoke:1",
                 "securityContext": {"runAsUser": 1001000000}}
    field, path_key, target = ("volumeDevices", "devicePath", "/dev/test-volume") if mode == "Block" else (
        "volumeMounts", "mountPath", "/actual-data")
    container[field] = [{"name": "source-volume", path_key: target}]
    return {"objects": {
        "namespace/test-smoke": {"metadata": meta("test-smoke")},
        "persistentvolumeclaim/source": {"metadata": meta("source"), "status": {"phase": "Bound"},
            "spec": {"storageClassName": "source-sc", "volumeName": "source-pv", "volumeMode": mode,
                     "accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "2Gi"}}}},
        "pod/writer": {"metadata": meta("writer"), "status": {
            "conditions": [{"type": "Ready", "status": "True"}]}, "spec": {
            "nodeName": "node-a", "serviceAccountName": "smoke", "securityContext": {"fsGroup": 1001000000},
            "containers": [container], "volumes": [{"name": "source-volume", "persistentVolumeClaim": {
                "claimName": "source"}}]}},
        "storageclass/source-sc": {"metadata": meta("source-sc"), "provisioner": "test.csi.example",
            "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer", "parameters": {"clusterID": "backend"}},
        "persistentvolume/source-pv": {"metadata": meta("source-pv"), "spec": {
            "claimRef": {"uid": "source-uid", "name": "source", "namespace": "test-smoke"},
            "csi": {"driver": "test.csi.example", "volumeHandle": "source-handle"}}},
        "volumesnapshotclass/snap-class": {"metadata": meta("snap-class"), "driver": "test.csi.example",
            "deletionPolicy": policy, "parameters": {"clusterID": "backend"}}},
        "created": [], "deleted": [], "calls": [], "writes": []}


def run(tmp_path, scenario="", mode="Filesystem", policy="Delete", change=None, args=None):
    state = initial(mode, policy)
    state["scenario"] = scenario
    if change:
        change(state["objects"])
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))
    oc = tmp_path / "oc"
    oc.write_text(FAKE_OC)
    oc.chmod(0o755)
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
               FAKE_STATE=str(state_path))
    command = args if args is not None else ["--context", "target", "--namespace", "test-smoke",
        "--source-pvc", "source", "--writer-pod", "writer", "--snapshot-class", "snap-class",
        "--timeout-seconds", "1"]
    result = subprocess.run([sys.executable, str(SCRIPT), *command], capture_output=True, text=True,
                            env=env, timeout=20)
    return result, json.loads(state_path.read_text())


@pytest.mark.parametrize("mode", ["Filesystem", "Block"])
def test_round_trip_uses_original_token_new_pvc_and_cleans(tmp_path, mode):
    result, state = run(tmp_path, mode=mode)
    assert result.returncode == 0, result.stderr
    assert "verified" in result.stdout.lower()
    assert len(state["writes"]) == 2
    assert state["writes"][0][-1] != state["writes"][1][-1]
    assert state["snap_token"] == state["writes"][0][-1]
    assert state["source_token"] == state["writes"][1][-1]
    assert not any(k.startswith("volumesnapshotcontent/") for k in state["objects"])
    assert "persistentvolume/restore-pv" not in state["objects"]
    assert "persistentvolumeclaim/source" in state["objects"]
    assert "pod/writer" in state["objects"]
    assert "namespace/test-smoke" in state["objects"]
    assert all(call[:2] == ["--context", "target"] for call in state["calls"])
    restore = next(o for o in state["created"] if o["kind"] == "PersistentVolumeClaim")
    assert restore["spec"]["resources"]["requests"]["storage"] == "1536Mi"
    assert restore["spec"]["volumeMode"] == mode
    assert restore["spec"]["dataSource"]["kind"] == "VolumeSnapshot"
    reader = next(o for o in state["created"] if o["kind"] == "Pod")
    assert "nodeName" not in reader["spec"]
    affinity = reader["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    assert affinity["nodeSelectorTerms"][0]["matchFields"][0] == {
        "key": "metadata.name", "operator": "In", "values": ["node-a"]}
    assert reader["spec"]["containers"][0]["securityContext"]["allowPrivilegeEscalation"] is False
    assert reader["spec"]["volumes"][0]["persistentVolumeClaim"]["readOnly"] is (mode == "Block")
    assert reader["spec"]["securityContext"]["fsGroup"] == 1001000000
    # Stateful fake keeps WFFC Pending until a consumer exists; success proves consumer-first ordering.
    assert reader["spec"]["containers"][0]["image"] == "example.invalid/smoke:1"
    assert "printf" not in " ".join(reader["spec"]["containers"][0]["command"])
    script = state["writes"][0][2]
    assert "sync" in script
    assert ("test -b" in script and "count=64" in script and "conv=notrunc" in script) if mode == "Block" else (
        state["writes"][0][-2] == "/actual-data")


@pytest.mark.parametrize("which", ["namespace/test-smoke", "persistentvolumeclaim/source", "pod/writer"])
def test_unlabelled_sources_never_mutate(tmp_path, which):
    result, state = run(tmp_path, change=lambda objs: objs[which]["metadata"].pop("labels"))
    assert result.returncode != 0
    assert not state["writes"] and not state["created"]


@pytest.mark.parametrize("scenario", ["missing-class", "driver", "backend", "reclaim", "unready", "wrong-volume", "unsafe-device"])
def test_unsafe_preflight_never_mutates(tmp_path, scenario):
    def change(o):
        if scenario == "missing-class":
            del o["volumesnapshotclass/snap-class"]
        elif scenario == "driver":
            o["volumesnapshotclass/snap-class"]["driver"] = "other.csi.example"
        elif scenario == "backend":
            o["volumesnapshotclass/snap-class"]["parameters"]["clusterID"] = "other"
        elif scenario == "reclaim":
            o["storageclass/source-sc"]["reclaimPolicy"] = "Retain"
        elif scenario == "unready":
            o["pod/writer"]["status"]["conditions"] = []
        elif scenario == "wrong-volume":
            o["pod/writer"]["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] = "other"
        elif scenario == "unsafe-device":
            o["pod/writer"]["spec"]["containers"][0]["volumeDevices"][0]["devicePath"] = "/dev/sda"
    result, state = run(tmp_path, mode="Block" if scenario == "unsafe-device" else "Filesystem", change=change)
    assert result.returncode != 0
    assert not state["writes"] and not state["created"]


@pytest.mark.parametrize("scenario", ["snapshot-pending", "snapshot-error", "content-mismatch", "restore-mismatch",
                                     "restore-api-error", "create-response-lost", "content-remains", "pv-remains", "forbidden",
                                     "content-list-forbidden", "reader-create-fails", "content-uid-mismatch", "content-size-mismatch",
                                     "pvc-create-response-lost"])
def test_failures_do_not_claim_success_or_leak_and_cleanup(tmp_path, scenario):
    result, state = run(tmp_path, scenario=scenario)
    assert result.returncode != 0
    assert "verified" not in result.stdout.lower()
    assert "private-secret-value" not in result.stdout + result.stderr
    assert "persistentvolumeclaim/source" in state["objects"]
    if state["created"]:
        assert state["deleted"]
        assert not any(k.startswith("volumesnapshot/") for k in state["objects"])
        assert not any(k.startswith("pod/snapshot-smoke-") for k in state["objects"])


def test_retained_class_is_preserved_and_temporary_delete_class_removed(tmp_path):
    result, state = run(tmp_path, policy="Retain")
    assert result.returncode == 0, result.stderr
    assert state["objects"]["volumesnapshotclass/snap-class"]["deletionPolicy"] == "Retain"
    clone = next(o for o in state["created"] if o["kind"] == "VolumeSnapshotClass")
    assert clone["deletionPolicy"] == "Delete"
    assert clone["parameters"] == {"clusterID": "backend"}
    assert ["volumesnapshotclass", clone["metadata"]["name"]] in state["deleted"]


@pytest.mark.parametrize("args", [[], ["--context", "target", "--namespace", "production",
    "--source-pvc", "source", "--writer-pod", "writer", "--snapshot-class", "snap-class"]])
def test_required_explicit_context_and_smoke_namespace(tmp_path, args):
    result, state = run(tmp_path, args=args)
    assert result.returncode == 2
    assert state["calls"] == []


@pytest.mark.parametrize("scenario", ["reader-create-fails", "pvc-create-response-lost"])
def test_partial_restore_creation_cleans_owned_pv(tmp_path, scenario):
    result, state = run(tmp_path, scenario=scenario)
    assert result.returncode != 0
    assert "persistentvolume/restore-pv" not in state["objects"]
    assert not any(k.startswith("persistentvolumeclaim/snapshot-smoke-") for k in state["objects"])


@pytest.mark.parametrize("snapshot_type", ["bak", None])
def test_longhorn_external_backup_class_cannot_pass_local_snapshot_test(tmp_path, snapshot_type):
    def change(objects):
        objects["storageclass/source-sc"]["provisioner"] = "driver.longhorn.io"
        objects["persistentvolume/source-pv"]["spec"]["csi"]["driver"] = "driver.longhorn.io"
        objects["volumesnapshotclass/snap-class"]["driver"] = "driver.longhorn.io"
        if snapshot_type:
            objects["volumesnapshotclass/snap-class"]["parameters"]["type"] = snapshot_type
    result, state = run(tmp_path, change=change)
    assert result.returncode != 0
    assert not state["writes"] and not state["created"]


def test_longhorn_snap_class_round_trip(tmp_path):
    def change(objects):
        objects["storageclass/source-sc"]["provisioner"] = "driver.longhorn.io"
        objects["persistentvolume/source-pv"]["spec"]["csi"]["driver"] = "driver.longhorn.io"
        objects["volumesnapshotclass/snap-class"].update(driver="driver.longhorn.io", parameters={"type": "snap"})
    result, state = run(tmp_path, change=change)
    assert result.returncode == 0, result.stderr
    assert len(state["writes"]) == 2


@pytest.mark.parametrize("exists", [True, False])
def test_snapshot_credentials_are_metadata_only_and_checked_before_write(tmp_path, exists):
    def change(objects):
        objects["volumesnapshotclass/snap-class"]["parameters"].update({
            "csi.storage.k8s.io/snapshotter-secret-name": "credentials",
            "csi.storage.k8s.io/snapshotter-secret-namespace": "storage-system"})
        if exists:
            objects["secret/credentials"] = {"metadata": {"name": "credentials", "uid": "credentials-uid"}}
    result, state = run(tmp_path, change=change)
    assert result.returncode == (0 if exists else 1), result.stderr
    if not exists:
        assert not state["writes"] and not state["created"]
    secret_calls = [c for c in state["calls"] if "secret" in c]
    assert len(secret_calls) == 1 and secret_calls[0][-2:] == ["-o", "name"]
    assert "private-secret-value" not in result.stdout + result.stderr


def test_changed_ownership_refuses_cleanup_deletion(tmp_path):
    result, state = run(tmp_path, scenario="ownership-changed")
    assert result.returncode != 0
    assert not any(kind == "pod" for kind, name in state["deleted"])
    assert "cleanup incomplete" in result.stderr


@pytest.mark.parametrize("scenario", ["snapshot-delete-fails", "content-remains"])
def test_retained_clone_survives_unverified_snapshot_cleanup(tmp_path, scenario):
    result, state = run(tmp_path, scenario=scenario, policy="Retain")
    assert result.returncode != 0
    assert "cleanup incomplete" in result.stderr
    clone = next(o for o in state["created"] if o["kind"] == "VolumeSnapshotClass")
    assert "volumesnapshotclass/" + clone["metadata"]["name"] in state["objects"]
    assert not any(kind == "volumesnapshotclass" for kind, name in state["deleted"])
    assert state["objects"]["volumesnapshotclass/snap-class"]["deletionPolicy"] == "Retain"


def test_filesystem_restore_allows_selinux_relabel_before_readonly_probe(tmp_path):
    """Read-only clone mounts leave CephFS/NFS restored inodes unlabeled on OpenShift."""
    result, state = run(tmp_path, scenario="selinux-relabel")
    assert result.returncode == 0, result.stderr
    reader = next(o for o in state["created"] if o["kind"] == "Pod")
    container = reader["spec"]["containers"][0]
    assert container["volumeMounts"][0]["readOnly"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert "printf" not in " ".join(container["command"])
    assert "persistentvolumeclaim/source" in state["objects"]
