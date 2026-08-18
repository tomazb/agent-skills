# Design: openshift-odf skill updates from prod2 ODF 4.20 SNO deployment

Date: 2026-08-18
Branch: `feat/odf-sno-420-scenario`
Author: deployment findings from context `prod2` (OCP 4.20.32, ODF 4.20.16-rhodf, SNO)

## Problem

A live ODF 4.20.16 deployment on the single-node cluster `prod2` reached
`HEALTH_OK` and validated ceph-rbd, cephfs, and MCG/RGW object storage, but only
after several fix-ups that the current `openshift-odf` skill (v1.4.0,
`references/validated-odf-sno.md` ODF 4.20 section) does **not** document. This
design captures those gaps and the agreed skill changes.

### Gaps discovered (what did not work from the skill)

1. **Empty-`topologyKey` regression is broader than documented.** The runbook
   covers `topologyKey: ""` only for mon/OSD at the StorageCluster level. On
   prod2 the `CephFilesystem` (`metadataServer.placement`) and `CephObjectStore`
   (`gateway.placement`) also received `topologyKey: "" + whenUnsatisfiable:
   DoNotSchedule`, so MDS and RGW pods could not schedule and both CRs sat in
   `Failure` until patched to `kubernetes.io/hostname` + `ScheduleAnyway`.
2. **Pool-size fix must also cover CephFilesystem and CephObjectStore.** Same
   `size=3` + `replicasPerFailureDomain=1` validation failure
   ("size must be greater than replicasPerFailureDomain") as CephBlockPool;
   both need `reconcileStrategy: ignore` then direct CR patching of metadata and
   data pools (size 1, `failureDomain: host`, remove `replicasPerFailureDomain`).
3. **Onboarding ticket signature failure after reinstall.** The internal
   `StorageClient` stalled in `Initializing` (empty CONSUMER) with the provider
   logging `failed to verify onboarding ticket signature. crypto/rsa:
   verification error` (`server.go:163`). This blocked ClientProfile creation
   and therefore the `ceph-rbd` and `cephfs` StorageClasses (only `ceph-rgw`
   existed). Not documented at all.
4. **virtio disk with no `/dev/disk/by-id/` entry.** LSO refused to create the
   PV (`IDPathNotFoundError: a symlink to vdb was not found in
   /dev/disk/by-id/`); a udev MachineConfig was needed to mint a stable `by-id`
   symlink. Ignition `data:` URLs must encode spaces as `%20` (a literal `+`
   corrupts the udev rule).
5. **`.mgr` pool reverts to size=3** whenever the mgr restarts; needs a
   post-restart re-check.

## Scope and decisions

- Implement documentation items #1–#4 **and** a narrow helper script (item #5).
- Full formality: this design doc is committed, then a writing-plans
  implementation plan is produced before editing.
- Single squashed commit at the end of implementation.
- Script shape: **generator/renderer** (Approach A), matching
  `scripts/render_storagecluster.py` and `scripts/render_smoke_manifest.py`
  (argparse → emit text → unit test on output; never executes `oc`/`ceph`).
- Script scope is deliberately **narrow** (deterministic patches only). The
  full remediation flow is too stateful (waits, verification, stale-pod
  deletion, finalizer clearing, iterative onboarding recovery) to encode safely
  in a static script; the runbook prose remains the single source of truth for
  sequencing.

## Component 1: `openshift-odf/scripts/render_sno_remediation.py`

Generator that prints an ordered, commented bash script (leading banner:
"review before running; prerequisite: CephCluster Ready; NOT included — follow
`references/validated-odf-sno.md` Regression 2 for pool sizing and
`references/validation-hardening.md` for onboarding recovery").

CLI flags:
- `--name` (default `ocs-storagecluster`)
- `--namespace` (default `openshift-storage`)
- `--output` (default stdout)

Emitted deterministic patch blocks (kube-API patches, plus the idempotent mute):
1. `reconcileStrategy: ignore` for `cephBlockPools`, `cephObjectStores`,
   `cephFilesystems` on the StorageCluster.
2. topologyKey ×2 → `kubernetes.io/hostname` + `ScheduleAnyway` on
   `cephfilesystem/<name>-cephfilesystem` (`metadataServer.placement`) and
   `cephobjectstore/<name>-cephobjectstore` (`gateway.placement`).
3. `cephblockpool/<name>-cephblockpool`: `failureDomain: host` + remove
   `replicasPerFailureDomain`.
4. both `drivers.csi.ceph.io` (`<namespace>.rbd.csi.ceph.com`,
   `<namespace>.cephfs.csi.ceph.com`) → `controllerPlugin.replicas: 1`.
5. `ceph ... health mute POOL_NO_REDUNDANCY` at the tail, commented
   "re-run after pool sizing from the runbook".

Explicitly NOT emitted (documented in the banner): the live `ceph osd pool ls`
size=1 loop + global ceph config, the CephFilesystem/CephObjectStore pool
size=1 + failureDomain patches, onboarding-key recovery, and all
wait/verify/finalizer/stale-pod steps.

### Test: `openshift-odf/tests/test_render_sno_remediation.py`

Asserts:
- all five emitted blocks are present (reconcileStrategy ignore, both
  topologyKey patches, CephBlockPool failureDomain, both Driver replica
  patches, mute);
- the "NOT included / follow the runbook" banner text is present;
- onboarding-recovery and the `ceph osd pool ls` loop are **absent**;
- `--output <path>` writes the same content to a file.

Mirrors the structure of the existing render-script tests.

## Component 2: `references/validated-odf-sno.md` (ODF 4.20 section)

- Add **Regression 4: Empty topologyKey on MDS and RGW placements** — symptom
  (CephFilesystem/CephObjectStore stuck `Failure`, no MDS/RGW pods; `ceph fs ls`
  empty), and the two `oc patch` fixes.
- Extend **Regression 2 (pool sizes)** to include CephFilesystem and
  CephObjectStore: `reconcileStrategy: ignore` then patch metadata and data
  pools to size 1, `failureDomain: host`, remove `replicasPerFailureDomain`.
- Add a note that the `.mgr` pool reverts to `size=3` on mgr restart; re-check
  and re-fix after any mgr restart.
- Add a pointer to `scripts/render_sno_remediation.py` and to the new
  onboarding troubleshooting entry.

## Component 3: `references/validation-hardening.md`

- New Troubleshooting entry **StorageClient stuck Initializing — onboarding
  ticket signature verification error**: symptom (`server.go:163` provider log,
  StorageClient `Initializing` with empty CONSUMER, missing `ceph-rbd`/`cephfs`
  StorageClasses), cause (stale onboarding token after reinstall), and the fix
  (delete `onboarding-private-key`, `onboarding-ticket-key`, and the
  StorageConsumer-owned `onboarding-token-*` secret; restart `ocs-operator` and
  `ocs-provider-server`; recreate the StorageClient, clearing its finalizer if
  stuck `Offboarding`; verify `Connected`).
- Add `.mgr` size=3-after-mgr-restart check to **Post-Reboot Drift**.

## Component 4: `references/local-storage-disks.md`

- New subsection **virtio / disks with no `/dev/disk/by-id/` entry**, before the
  `LocalVolume` exception: symptom (`IDPathNotFoundError`, no `localblock` PV),
  udev MachineConfig recipe creating a stable `by-id` symlink, and the
  `%20`-not-`+` ignition `data:` encoding caveat. Note the SNO reboot warning
  for MachineConfig changes.

## Packaging and validation

- Bump `VERSION`, `package.json`, and `README.md` "Current version" 1.4.0 →
  **1.5.0** (additive documentation + new script).
- Add a `## 1.5.0` entry to `CHANGELOG.md` summarizing the four doc changes and
  the new script.
- Register the new script wherever the script inventory is maintained
  (README/package manifest), if applicable.
- Validation: `pytest openshift-odf/tests` and
  `python3 scripts/validate_skill_collection.py` must pass.

## Non-goals

- No change to ODF 4.16 or 4.22 sections beyond cross-references.
- No auto-executing remediation; the script only generates reviewable commands.
- No new operator/version support.
