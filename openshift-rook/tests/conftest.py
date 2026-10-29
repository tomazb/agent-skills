from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"

# Loaded by path under a name of its own: other skills ship a validate_skill_package
# module too, and a shared pytest process would otherwise hand them this one.
_spec = importlib.util.spec_from_file_location(
    "openshift_rook_validate_skill_package", TOOLS_DIR / "validate_skill_package.py"
)
vsp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = vsp
_spec.loader.exec_module(vsp)


@pytest.fixture
def validator():
    return vsp


REFERENCE_TEXT = """\
# Sample Reference

Never run or recommend `wipefs` before explicit destructive confirmation.

Use `readlink -f`, `lsblk -f`, `wipefs -n`, and `ceph-volume lvm list` evidence.

On RHCOS, run `ceph-volume lvm list` from a node-local helper container that bind-mounts `mount --rbind /host/dev /dev`, `mount --rbind /host/run/lvm /run/lvm`, and `mount --rbind /host/etc/lvm /etc/lvm` into the ceph image; if that helper cannot inspect the disk, print `LVM residue audit failed; do not reuse the disk`. Fail closed when `DISKS` is empty (`no candidate disks configured`), when a path is not a block device (`invalid candidate disk`), or when node leftover inspection fails (`node leftover inspection failed; do not reuse the disk`, `for r in /sys/bus/rbd/devices/*; do [ -e "$r" ] || continue;`, `then echo "$dev"; exit 0; fi; done < /proc/mounts; echo "no /data mount" >&2; exit 1`, `BlueStore signature remains on $d; do not reuse the disk`, `LVM OSD metadata found on $d; do not reuse the disk`, `Raw Ceph inventory is not empty for $d; do not reuse the disk`).

Use stable `/dev/disk/by-id/*` paths.

For SNO, use `replicated.size: 1` and `requireSafeReplicaSize: false`.

Keep exactly one default StorageClass.

Also keep one default StorageClass.

RBD and CephFS and RGW are supported.

`cephblockpool`, `cephfilesystem`, `cephobjectstore` resources.

Use `mon.count` and `mgr.count`.

On OpenShift, use MachineConfig and reboot. Wait for MCP.

Grant privileged SCC temporarily.

Do not downgrade. Read release notes. Check HEALTH_OK and active+clean.

For upgrade, verify HEALTH_OK and active+clean.

Leave the PG autoscaler on; check `ceph osd pool autoscale-status`.

On OpenShift, install with operator-openshift.yaml for the dedicated rook-ceph SCC.

Apply `csi-operator.yaml` before `operator-openshift.yaml` or `CephConnection` reconciliation can fail.

Use `curl -fsSLo /tmp/rook-ceph-csi-operator.yaml` before `curl -fsSLo /tmp/rook-ceph-operator.yaml`.
On SNO, edit `/tmp/rook-ceph-operator.yaml` now, before its first apply.

Create the namespace first with `oc create ns rook-ceph`.

Run `oc apply --server-side --force-conflicts -f /tmp/rook-ceph-crds.yaml`, then `oc apply -f /tmp/rook-ceph-common.yaml`, then `oc apply -f /tmp/rook-ceph-csi-operator.yaml`, then `oc apply -f /tmp/rook-ceph-operator.yaml`.

Apply `oc apply -f /tmp/rook-ceph-csi-operator.yaml` before `oc apply -f /tmp/rook-ceph-operator.yaml`.

Use `useAllDevices: false` when the SNO install pins a dedicated OSD disk.

Use `/dev/disk/by-id/<stable-disk-id>` together with `osd_pool_default_size` and `mon_warn_on_pool_no_redundancy` on the SNO example.

On SNO with RGW, raise `mon_max_pg_per_osd` when the single OSD needs a higher PG ceiling.

If the OpenShift Prometheus API is auth-protected, point `PROMETHEUS_API_HOST` at an `internal Prometheus`.

Expose the dashboard Route through the `http-dashboard` service port.

Run `ceph mgr module enable rook` and `ceph orch set backend rook`.

Validate RGW with `ObjectBucket` state, a `curl -kI` route check, and an HTTP response from `Ceph Object Gateway` instead of a `TLS or connection failure`.

Validated SNO evidence should include `v1.20.2`, `v20.2.2`, `rook-ceph-rgw-obc`, and `Backend: rook`.

Use `python3 scripts/patch_rook_ceph_manifest.py` when preparing placeholder manifests.

Use `python3 scripts/render_smoke_manifest.py` for smoke PVC writers. Use `python3 scripts/check_snapshot_smoke.py` for snapshot recovery.

oc -n rook-rbd-smoke exec rbd-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-smoke
bash scripts/cleanup_smoke_namespace.sh --namespace rook-cephfs-smoke
oc -n rook-rgw-smoke get objectbucketclaim rook-ceph-obc
scheme = "https" if port in ("443", "8443") else "http"
s3.put_object
rook-rgw-smoke-ok
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rgw-smoke --object
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-aes256k-probe
oc -n rook-rbd-aes256k-probe describe pod rbd-smoke-writer
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-aes256k-probe
Then delete the probe namespace
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-aes256k-probe

Run `bash scripts/post_uninstall_audit.sh` after uninstall.

Gate the uninstall with `scripts/classify_ceph_ownership.sh`; follow **Orphans After An Interrupted Uninstall** (restart the kubelet on that node, never delete the volume directory under a running kubelet) and **Cluster RBAC left by Rook**.

Run `Leftover Install Detection` for both `ocs.openshift.io` and Rook, checking `/var/lib/rook/mon-` dirs, a `Has BlueStore device label` disk, and `oc get csidriver`.

Follow `Ceph Version And ceph-csi Compatibility`: Tentacle keys can fail with `failed to decode key` and `rados: ret=-22` because ceph-csi cannot decode `AES256K`. Move the image-set to `quay.io/cephcsi/cephcsi:v3.17.1`, set `keyType: aes256k`, probe namespace `rook-rbd-aes256k-probe`, and Keep AES256K when that volume write succeeds. Set `allowedCiphers` to `aes256k` so `AUTH_INSECURE_KEYS_ALLOWED` stays clear unless classic AES was requested. Rotate only after a `FailedMount` key-mapping error, and set `keepPriorKeyCountMax` so the prior CSI key remains.

During uninstall, clear stuck `clientprofiles.csi.ceph.io` finalizers (`csi.ceph.com/cleanup`), then `oc delete csidriver` orphans and clear the `dataDirHostPath` on each node. Record `PRIOR_DEFAULT_STORAGE_CLASS`. Delete `rook-ceph-metrics` when its only subject is `openshift-monitoring/prometheus-k8s` and both operator namespaces are gone.

Stale krbd Devices: check `/sys/bus/rbd/devices`, `rbd device unmap` leftovers, and note a wedged `ceph-volume raw list` hang needs a reboot.

BlueStore label cleanup: `wipefs -af` and `sgdisk --zap-all` are not sufficient. Clear labels at 0, 1 GiB, 10 GiB, 100 GiB, and 1000 GiB with `for mult in 0 1 10 100 1000`, or full-disk zero when required. From Ceph `v19.2.1`, `ceph-bluestore-tool zap-device --yes-i-really-really-mean-it` zeros them; `v19.2.0` has no `zap-device`. `ceph-volume raw list` must print `{}`. Either result alone is incomplete. OSD prepare skips a `Has BlueStore device label`. See `references/osd-disk-prep.md`.

Empty LVM inventory prints `No valid Ceph lvm devices found`. An empty `plugin` value uses `quay.io/cephcsi/cephcsi:v3.18.1`. Set `driverSpecDefaults` with `{"spec":{"driverSpecDefaults":{"controllerPlugin":{"replicas":1}}}}` and pin `cephVersion.image`. Controller anti-affinity uses `kubernetes.io/hostname`. PodSecurity `restricted:latest` can warn. Read `status.ceph.health`. `HEALTH_WARN` is a bootstrap state to diagnose with `ceph health detail`, not a pass. OpenShift `4.18.56` on kernel `5.14.0-427.151.1.el9_4` with Rook `v1.21.1` is field evidence. NVMe cryptographic erase uses `fna` and `sanicap`: `--sanact=4` for a key change, `--ses=2` for format cryptographic erase, `--sanact=2` for sanitize block erase. Success with Global Data Erased reports `0x101`. Choose the fastest proper erase with `scripts/select_erase_method.py`. A virtio or generic virtual disk with `write_zeroes_max_bytes` set uses `blkdiscard --zeroout`. `fstrim` only trims a mounted filesystem.

If `timeout 30 rbd device unmap` times out, skip sysfs remove* (it can block in D-state where `timeout` cannot help) and escalate to reboot or power-cycle. Re-check `/dev/rbd[0-9]*` and `/sys/bus/rbd/devices/*`. If either path is still populated, reboot or power-cycle before pool deletion or reinstall.

VM storage defaults: set `storageclass.kubevirt.io/is-default-virt-class` for the CDI/KubeVirt virtualization default, keep `storageclass.kubernetes.io/is-default-class` for the general default, and configure StorageProfile `claimPropertySets` (`ReadWriteMany` + `volumeMode: Block` for RBD, `Filesystem` for CephFS/NFS). Resolve `CDIStorageProfilesIncomplete` for an `UnrecognizedProvisioner` by setting `spec.claimPropertySets`. When moving a default off an LVMS class, set `LVMCluster.spec.storage.deviceClasses[].default: false` because the operator re-pins the annotation.

bash scripts/cleanup_smoke_namespace.sh --namespace rook-vm-smoke

## Smoke Test
`oc get sc` shows exactly one default StorageClass when defaulting is expected.
## Post-Reboot Drift
one default if defaulting is expected

csi.storage.k8s.io/controller-expand-secret-name: rook-csi-rbd-provisioner
csi.storage.k8s.io/controller-expand-secret-namespace: rook-ceph
csi.storage.k8s.io/node-stage-secret-name: rook-csi-rbd-node
csi.storage.k8s.io/controller-expand-secret-name: rook-csi-cephfs-provisioner
csi.storage.k8s.io/controller-expand-secret-namespace: rook-ceph
csi.storage.k8s.io/node-stage-secret-name: rook-csi-cephfs-node
The external-resizer does not fall back to the provisioner-secret parameters.
python3 scripts/check_volume_expansion_secrets.py
no `userID` or `userKey`

snapshotPolicy: volumeGroupSnapshot
Use `volumeSnapshot` by default
group snapshot and restore
--feature-gates=CSIVolumeGroupSnapshot=true
Do not set `snapshotPolicy` on an NFS driver
driverSpecDefaults.snapshotPolicy
rook-ceph.rbd.csi.ceph.com
rook-ceph.cephfs.csi.ceph.com
Set this driver's `snapshotPolicy` to `volumeSnapshot`
set `snapshotPolicy: volumeSnapshot` instead
TechPreviewNoUpgrade
kind: VolumeGroupSnapshotClass
groupsnapshot.storage.k8s.io/v1beta2
group API client
CustomNoUpgrade
Do not enable feature gates.
"""

SKILL_TEMPLATE = """\
---
name: openshift-rook
description: Use when planning, installing, or troubleshooting Rook Ceph on OpenShift.
---

# OpenShift Rook Ceph Lifecycle

Use this skill as a lifecycle router.

## Product Ownership Gate

Before routing, run read-only ownership discovery. Inspect `StorageCluster`, ODF/OCS
`Subscription` or CSV evidence, and `CephCluster`. Namespace presence alone is
insufficient. Classify ODF, upstream Rook, mixed/conflicting, or unknown. Stop and
report evidence when ownership is mixed, conflicting, unknown, or access is
insufficient. Do not recommend mutation until ownership is classified. If ODF owns
the cluster, hand off to `openshift-odf`.

## Routing

Routing guidance.

## Core Safety Rules

Safety guidance. If `oc wait --for=jsonpath` fails with `unrecognized condition`, poll the field instead. A former BlueStore OSD also keeps labels at 10 GiB, 100 GiB, and 1000 GiB; with Ceph `v19.2.1` or later, `ceph-bluestore-tool zap-device` zeros them; do not reuse the disk until `ceph-volume raw list` prints `{}`. Either result alone is incomplete when wipefs or lsblk still reports ceph_bluestore. SSDs often support cryptographic erase or a sanitize block erase; discover `fna` and `sanicap` first, then run `scripts/select_erase_method.py` for the fastest proper erase. Virtio and generic virtual disks use `blkdiscard --zeroout` or writing zeroes; `fstrim` does not blank a raw disk. See `references/osd-disk-prep.md`.

## Required Source Checks

Source guidance. For OpenShift channel or upgrade-path questions, use
`openshift-versions`. Release availability is not cluster upgrade readiness.

## Inputs To Collect

Input guidance.

## Output Expectations

Output guidance. After a smoke test is recorded, delete its namespace with `scripts/cleanup_smoke_namespace.sh`.
"""


def _make_skill_text(name: str = vsp.EXPECTED_NAME, missing_sections: list[str] | None = None) -> str:
    text = SKILL_TEMPLATE
    if name != vsp.EXPECTED_NAME:
        text = text.replace("name: openshift-rook", f"name: {name}")
    if missing_sections:
        for section in missing_sections:
            text = text.replace(f"## {section.lstrip('# ').strip()}", "")
    return text


@pytest.fixture
def make_skill_text():
    return _make_skill_text


@pytest.fixture
def reference_text():
    return lambda: REFERENCE_TEXT


@pytest.fixture
def package_factory(tmp_path, make_skill_text, reference_text):
    def _factory(
        skill_text: str | None = None,
        reference_content: str | None = None,
    ) -> Path:
        root = tmp_path / "openshift-rook"
        root.mkdir()

        refs = root / "references"
        refs.mkdir()

        (root / "SKILL.md").write_text(skill_text or make_skill_text(), encoding="utf-8")
        (root / "README.md").write_text(
            "# OpenShift Rook Ceph\n\nCurrent version: **1.0.0**\n", encoding="utf-8"
        )
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0\n\n- Initial.\n", encoding="utf-8")
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "openshift-rook",
                    "version": "1.0.0",
                    "description": "Rook Ceph lifecycle",
                }
            ),
            encoding="utf-8",
        )
        (root / "assets").mkdir()
        (root / "assets" / "smoke-pvc-writer.yaml").write_text("", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "patch_rook_ceph_manifest.py").write_text("", encoding="utf-8")
        (root / "scripts" / "post_uninstall_audit.sh").write_text("", encoding="utf-8")
        (root / "scripts" / "classify_ceph_ownership.sh").write_text("", encoding="utf-8")
        (root / "scripts" / "rook_common.sh").write_text("", encoding="utf-8")
        (root / "scripts" / "render_smoke_manifest.py").write_text("", encoding="utf-8")
        (root / "scripts" / "check_snapshot_smoke.py").write_text("", encoding="utf-8")
        (root / "scripts" / "check_volume_expansion_secrets.py").write_text("", encoding="utf-8")
        (root / "scripts" / "cleanup_smoke_namespace.sh").write_text("", encoding="utf-8")
        (root / "scripts" / "select_erase_method.py").write_text("", encoding="utf-8")
        for helper in ("plan_osd_disk_prep.py", "check_rook_mgr_compatibility.py", "check_rook_health.py",
                       "check_rgw_smoke.py", "rgw_s3_roundtrip.py", "rook_audit_expectations.sh"):
            (root / "scripts" / helper).write_text("", encoding="utf-8")
        (root / "tools").mkdir()
        (root / "tools" / "validate_skill_package.py").write_text("", encoding="utf-8")
        (root / "tools" / "validate_skill_package.sh").write_text("", encoding="utf-8")

        ref_content = reference_content or REFERENCE_TEXT
        for ref in vsp.EXPECTED_REFERENCES:
            (root / ref).write_text(ref_content + "\n", encoding="utf-8")

        return root

    return _factory
