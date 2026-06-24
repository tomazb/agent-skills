# Changelog

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
