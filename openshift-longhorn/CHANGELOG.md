# Changelog

## 1.2.4

- Added openshift-versions handoff and package-validator checks that preserve helper-script invocations in install/validation/uninstall runbooks.

## 1.2.3

- Corrected V2 host-prep guidance: `vfio_iommu_type1` is now described as an auto-loaded VFIO dependency rather than a Longhorn requirement, and the V2 SPDK MachineConfig loads only `vfio_pci`, `uio_pci_generic`, and `nvme_tcp` to match the validated evidence.
- Clarified that the `aio` disk-driver path needs only `nvme_tcp` for I/O; the vfio/uio modules satisfy `--enable-spdk` preflight and SPDK initialization.
- Noted that the `backupTargetName` StorageClass parameter requires Longhorn v1.8.0+.
- Added an oauth-proxy image-tag caveat, a V2 migration feature-parity gate, and a smoke-pod `fsGroup` note for non-OpenShift clusters.

## 1.2.2

- Updated the OKD manifest patch helper so clean V2 installs disable V1 Data Engine by default, with `--keep-v1-engine true` for migration cases.
- Reduced post-uninstall audit noise by filtering RBAC checks to Longhorn resources.

## 1.2.1

- Documented how to obtain and checksum a pinned `longhornctl` when it is not locally installed.
- Added OpenShift/RHCOS preflight interpretation notes for kernel-config, DNS-label, and V2 `ublk_drv` warnings found during live testing.

## 1.2.0

- Added helper scripts for OKD manifest patching, restricted smoke manifest rendering, and read-only post-uninstall audits.
- Added a reusable smoke PVC/writer pod template that avoids OpenShift restricted PodSecurity warnings.
- Packaged the 2026-06-22 deprovision lessons journal as an expected reference.
- Made V1 and V2 Longhorn preflight flows explicit, including when to avoid or use `--enable-spdk`.
- Updated install, validation, and uninstall runbooks to reference the packaged helpers.
- Extended package validation and tests so lifecycle helpers are shipped and their V1/V2 behavior stays covered.

## 1.1.0

- Fixed the OpenShift uninstall runbook to delete the `longhorn-okd.yaml` manifest that install applies, and added a Helm uninstall path.
- Hardened the package validator: phrase checks run in a single pass, scan only runbooks (not README/CHANGELOG), and a new check keeps the README version in sync with `VERSION`.
- Excluded the development `tests/` suite from the packaged `.skill` archive so it stays self-contained.
- Repaired validator tests that passed for the wrong reason (no-op `replace` calls) and added positive/negative phrase-detection coverage.
- Tightened the `SKILL.md` description and removed an empty heading from the validated SNO evidence journal.

## 1.0.0

- Refactored `SKILL.md` into a concise lifecycle router.
- Added focused OpenShift/OKD Longhorn lifecycle reference runbooks.
- Moved the validated OpenShift 4.22 SNO V2 journal into `references/`.
- Added package metadata and validation tests for lifecycle references, safety gates, SNO defaults, V2 prerequisites, and markdown hygiene.
