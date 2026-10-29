---
name: openshift-rook
description: Use when planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, or troubleshooting Rook Ceph on OpenShift/OKD — including Single Node OpenShift, multi-node clusters, dedicated block disks for OSDs, CephBlockPool RBD, CephFS filesystem, CephObjectStore RGW/S3, device discovery, PG/PGP tuning, CDI/KubeVirt VM storage defaults and StorageProfile configuration, and operator lifecycle safety.
---

# OpenShift Rook Ceph Lifecycle

Use this skill as a lifecycle router for Rook Ceph on OpenShift/OKD. Do live discovery first, choose the relevant reference runbook, and write an actionable plan or command sequence with explicit safety gates.

## Product Ownership Gate

Before any install, upgrade, or remediation plan, classify who owns Ceph on the cluster with read-only discovery:

1. Check for a `StorageCluster` and ODF/OCS `Subscription` or CSV evidence.
2. Check for a `CephCluster` and whether Rook/ODF is reconciling it.
3. Do not treat namespace presence alone (`rook-ceph`, `openshift-storage`) as ownership proof.

Classify ownership as **ODF**, **upstream Rook**, **mixed/conflicting**, or **unknown**:

- **ODF**: `StorageCluster` plus ODF/OCS Subscription/CSV evidence → stop Rook mutation planning and hand off to `openshift-odf`.
- **Upstream Rook**: `CephCluster` without ODF ownership signals → continue with this skill.
- **Mixed/conflicting** or **unknown/insufficient access**: stop, report the evidence, and refuse mutating or destructive actions until ownership is resolved.

Never recommend applying upstream Rook manifests, wiping disks, or editing Ceph CRs until ownership is classified.

## Routing

- **Discovery, install, or prerequisite planning**: start with `references/install-and-preflight.md`.
- **Dedicated disk preparation for OSDs**: use `references/osd-disk-prep.md`.
- **Disk reuse versus sanitization**: run `python3 scripts/plan_osd_disk_prep.py` first. Reinstall defaults to BlueStore metadata reset. Only explicit `--intent sanitize` selects a whole-device erase.
- **RBD block storage pools and StorageClasses**: use `references/rbd-block-pools.md`.
- **CephFS filesystem pools and StorageClasses**: use `references/cephfs-filesystem.md`.
- **CephObjectStore (RGW/S3) setup**: use `references/rgw-object-store.md`.
- **Cluster expansion, shrink, or rebalancing**: use `references/cluster-expand-shrink.md`.
- **Rook upgrade or Ceph version selection**: use `references/upgrade.md`.
- **Backup, DR, and snapshot planning**: use `references/backup-restore-dr.md`.
- **Maintenance, node eviction, OSD replacement, operator uninstall, cluster destruction, or leftovers of an interrupted uninstall**: use `references/maintenance-uninstall.md`.
- **Validation, hardening, post-reboot drift checks, or troubleshooting**: use `references/validation-hardening.md`.
- **Post-install acceptance**: after storage/snapshot smoke cleanup, run `scripts/check_rook_health.py` (`--client operator` if no toolbox is installed) with an explicit context. Require sustained `HEALTH_OK`, active+clean PGs, and no new crash records, including newly archived ones.
- **RGW smoke testing**: use `scripts/check_rgw_smoke.py`; it respects OBC watch scope, keeps credentials inside the pod, and verifies owned-resource cleanup on success or failure.
- **Optional manager integration**: gate enablement with `scripts/check_rook_mgr_compatibility.py`. On affected Ceph releases keep only the optional `rook` manager module disabled; preserve Prometheus and genuine crash reporting.
- **Volume-expansion credentials**: run `scripts/check_volume_expansion_secrets.py`. CSI secret-reference templates are **Not checked**, not invalid; verify the resolved PV `spec.csi.controllerExpandSecretRef` and its Secret before declaring credentials ready. The helper exits 2 for unverified templates, 1 for a failed check, and 0 when all applicable checks pass.
- **Ceph `AUTH_*` cipher warnings**: use the strict full-record audit (`scripts/check_cephx_key_types.py`) and staged policy checks in `references/validation-hardening.md`. These warnings are not a SNO replica-count issue; audit rotating keys as well as client keys before tightening `allowedCiphers`.
- **VM storage defaults, CDI StorageProfiles, or `CDIStorageProfilesIncomplete`**: use `references/vm-storage-profiles.md`.

## Snapshot readiness

For installation, configuration, and remediation, configure supported snapshotting by default before declaring storage ready, unless the user explicitly opts out. Do not enable feature gates. Follow [references/backup-restore-dr.md](references/backup-restore-dr.md) for prerequisites, driver-matched `VolumeSnapshotClass` setup, selection, and snapshot/restore verification. Check each installed storage service; a CSI snapshotter sidecar alone does not prove support or configuration.

Validation-only requests remain read-only. Report supported but unconfigured snapshotting as **Warning**, unsupported combinations as **N/A** with a version-specific reason, and inaccessible or unverified capability as **Not checked**. Report **Supported**, **Configured**, **Scheduled**, and **Restore-tested** separately for each StorageClass. Configure classes during authorized setup even when no PVC exists; create recurring jobs only with a workload, retention, and consistency policy. Local snapshots do not replace off-cluster backups. Smoke tests must run `python3 scripts/check_snapshot_smoke.py` for supported modes and verify restored data and cleanup before a full pass; see `references/validation-hardening.md`.

For ordinary RBD/CephFS snapshots, use `volumeSnapshot`. Use optional group mode only for a group-snapshot requirement with verified target API/sidecar compatibility and group snapshot/restore evidence; API presence alone is insufficient. Preserve an existing verified group configuration. See the Snapshot readiness runbook for the gates.

## Core Safety Rules

- Never run or recommend `ceph-volume lvm zap`, `ceph-bluestore-tool zap-device`, `wipefs`, `sgdisk --zap-all`, `dd`, `mkfs`, or any OSD disk partitioning before the user gives explicit destructive confirmation for the exact target disk and intent.
- Before every destructive disk action, require `readlink -f`, `lsblk -f`, `wipefs -n`, and `ceph-volume lvm list` evidence for the target.
- `wipefs -af` and `sgdisk --zap-all` do not clear a former BlueStore OSD. Also zero the labels at 1 GiB, 10 GiB, 100 GiB, and 1000 GiB when they fit. With Ceph `v19.2.1` or later, `ceph-bluestore-tool zap-device`, run from the Ceph image, zeros all of them. Do not reuse the disk until `ceph-volume raw list` prints `{}` and `wipefs` or `lsblk` no longer reports `ceph_bluestore`. Either result alone is incomplete. See `references/osd-disk-prep.md`.
- Reinstall disk reuse requires clearing every BlueStore label and partition metadata, then verifying `ceph-volume raw list` is empty. This is not media sanitization. Only when the user requires whole-device sanitization, use `scripts/plan_osd_disk_prep.py --intent sanitize`, which delegates to `scripts/select_erase_method.py`. SSDs/NVMe may support cryptographic erase or sanitize block erase; discover `fna` and `sanicap` read-only. For that sanitization intent, virtio and generic virtual disks use `blkdiscard --zeroout` when write zeroes is advertised, and writing zeroes when it is not. `fstrim` only trims a mounted filesystem. See `references/osd-disk-prep.md`.
- Use stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` paths for destructive block-device targeting. Never use `/dev/sdX`, `/dev/nvmeXnY`, or guessed paths.
- Warn that MachineConfig changes and node drains can reboot nodes. On SNO, that removes API access until the single node returns; wait for MCP recovery and node readiness before continuing.
- Rook Ceph on SNO requires `mon.count: 1`, `mgr.count: 1`, `allowMultiplePerNode: true` under both `spec.mon` and `spec.mgr`, and reduced replica counts. Do not copy these SNO-only settings into multi-node production plans without explicit direction.
- Multi-node production requires at least three mons, three OSDs across failure domains, and a minimum replica count of 3 for Ceph data pools. Document explicit exceptions when the user overrides.
- Keep exactly one default StorageClass unless the user explicitly requests another policy. Before uninstall, record that name, including when there is none, in `PRIOR_DEFAULT_STORAGE_CLASS` and leave the variable set for `scripts/post_uninstall_audit.sh`. A cluster that started with no default is clean when it still has none.
- If `oc wait --for=jsonpath=...` fails with `unrecognized condition`, the client is older than that condition. Poll the same field until it matches. Do not treat the wait error as a failed object.
- Before deleting Rook's CRDs, SCCs, or `dataDirHostPath`, re-run `scripts/classify_ceph_ownership.sh` (the runbook's `rook_classify`) and stop unless it exits 0: ODF uses the same `ceph.rook.io`, `csi.ceph.io`, and `objectbucket.io` CRDs and SCC names `rook-ceph`/`rook-ceph-csi`, and names some of its objects `rook-ceph-*`. Judge residue by CSI driver, provisioner, and ownership, never by name; `scripts/post_uninstall_audit.sh` does that and exits nonzero on any residue.
- Ceph pool parameters are changeable but disruptive, not immutable: `pg_num` (the PG autoscaler is on by default), replica `size`, and failure-domain rules can all be modified on existing pools, but changes trigger rebalancing that is expensive and can degrade performance. Plan them at creation time and change them deliberately after verifying cluster health.
- For Rook operator updates, prefer the Operator Lifecycle Manager (OLM) path when the cluster uses OLM. For direct manifest installs, use version-pinned manifests and never apply a newer Rook manifest without reading the release notes and upgrade guide.
- Do not downgrade Rook operator or Ceph versions. For major version upgrades, verify all PGs are active+clean and OSDs are up before proceeding.
- Document the difference between Rook (operator) version and Ceph (cluster image) version. They can be upgraded independently, but each has documented compatibility.
- Choose the Ceph image and CSI key type with the AES256K probe in `references/install-and-preflight.md`. The default `allowedCiphers` list is `aes256k` alone, so `AUTH_INSECURE_KEYS_ALLOWED` stays clear. Keep that restriction when every schedulable node writes through a `/dev/rbd` mount. Allow classic AES only when the user requests it or a probe node reports a key-mapping failure.

## Required Source Checks

For install, upgrade, OSD operations, and operator changes, verify the current Rook Ceph docs and release notes when network access is available. Use pinned version docs for commands and live cluster discovery for the installed version; do not assume `v1.15` or `v18.2` is the target unless the user asks for it or the cluster already runs it.

For OpenShift channel, patch, or one-hop upgrade-path questions, use `openshift-versions`. Release availability is not cluster upgrade readiness and is not Rook/Ceph product compatibility.

## Inputs To Collect

- Cluster topology: SNO or multi-node, OpenShift/OKD version, node roles, target MachineConfigPool, and failure domain layout (host, rack, zone, or datacenter).
- Current Rook Ceph state: absent, operator installed, CephCluster CR exists, installed versions, mon/mgr/osd counts, pool health, StorageClasses, and any existing RGW/CephFS.
- Target storage services: RBD block, CephFS shared filesystem, RGW object/S3, or a combination.
- Target lifecycle action: install, OSD disk prep, RBD pool, CephFS pool, RGW object store, cluster expand, upgrade, backup/restore, maintenance, OSD replace, uninstall, cluster destroy, validation, hardening, or troubleshooting.
- Target disk inventory by node, preferably `/dev/disk/by-id/*`, plus whether each disk may be destroyed and whether it is raw (unpartitioned, no signatures) or already has data.
- Replica policy, PG counts, failure-domain rules, default StorageClass intent, backup/restore requirements, and maintenance window constraints.

## Output Expectations

- Start with discovered facts, assumptions, and safety gates.
- Name the exact reference runbook(s) used.
- Separate read-only discovery from mutating or destructive actions.
- Show commands with placeholders for cluster-specific values instead of fabricating node, disk, or version identifiers.
- Include post-change validation and rollback or stop conditions.
- After a smoke test or the AES256K probe is recorded, delete its disposable smoke namespace with `scripts/cleanup_smoke_namespace.sh` when the test created one. The RGW helper uses an existing namespace and deletes only its owned resources. Never delete the operator namespace to clean an object smoke test. A passing check left in place is not finished.
- For production work, include backup, monitoring, and restore validation guidance.
