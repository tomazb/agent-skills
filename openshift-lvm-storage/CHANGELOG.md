# Changelog

## 1.1.0

Fixes and evidence from a live LVMS 4.20.1 install on an OCP 4.20.32 SNO cluster that already ran ODF:

- Every `LVMCluster` template set `default: true` with no instruction to check for an existing default StorageClass, which silently produces a *second* default on a cluster running ODF or a prior LVMS install — contradicting the skill's own "keep exactly one default StorageClass" rule. `references/install-and-preflight.md` now has a decide-`default:`-first section with the discovery command and both branches, and `references/expand-shrink.md` says to preserve whatever the live CR already has.
- Documented what `default: false` costs: the operator's apply-time warning, and the fact that on a cluster with no default StorageClass a PVC omitting `storageClassName` stays `Pending` with nothing in the LVMS logs explaining it.
- Disk discovery assumed every disk has a `/dev/disk/by-id/` entry. virtio disks presented without a serial have none — only `/dev/disk/by-path/`. `references/install-and-preflight.md` now resolves the identity first, showing how to list both directories and when each is the right selector.
- Added a validated scenario to `references/validated-lvms-ocp-sno.md`: LVMS 4.20.1 alongside ODF in a shared `openshift-storage`, a 300 GiB virtio disk selected by `by-path`, the four-way raw-disk evidence gate, resulting VG/thin-pool figures, filesystem and raw-block validation, and the fact that 4.20.1 runs no `topolvm-controller`/`topolvm-node` pods.
- Contract tests in `tests/test_lvms_runbook_contracts.py` for all three fixes.

## 1.0.2

- Added openshift-versions handoff, patch_lvms_manifest helper invocation in install guidance, and package-validator reachability checks.

## 1.0.1

- Fix `lvextend` thin-pool example to use the LVM volume group name (`<vg-name>/<thin-pool-name>`) instead of the `openshift-storage` namespace.
- Add required `deletionPolicy: Delete` to all `VolumeSnapshotClass` manifests (block volumes and backup/restore), which the API server otherwise rejects.
- Stop `patch_lvms_manifest.py` from injecting empty `thinPoolConfig: {}` / `deviceSelector: {}` when those sections are not being patched, and validate `--size-percent` (10-90) and `--overprovision-ratio` (>= 1) against the LVMCluster schema.
- Fix `post_uninstall_audit.sh` PVC scan to handle PVCs with a null `storageClassName` (default StorageClass), which previously crashed jq and produced a false "no LVMS PVCs" result.
- Add the required `OperatorGroup` and correct resource ordering (namespace → OperatorGroup → Subscription) to the OLM install runbook.
- Replace `lsblk` (absent from ubi-minimal) with `test -b` in block smoke/exec checks.
- Stop relying on guessed CSI workload labels/names during upgrade and troubleshooting; discover workload names from the cluster instead.
- Clarify per-node evaluation of `deviceSelector.paths` in the multi-node example.

## 1.0.0

- Initial release of the OpenShift LVM Storage (LVMS) lifecycle skill.
- Covers discovery, install, volume group provisioning, filesystem volumes, block volumes, volume group expand/shrink, upgrade, backup/restore, maintenance, uninstall, validation, hardening, and troubleshooting.
- Includes YAML-aware manifest patching, restricted smoke manifest rendering for both filesystem and block modes, and read-only post-uninstall audits.
- Validated evidence journal placeholder for SNO + LVMS deployments.
