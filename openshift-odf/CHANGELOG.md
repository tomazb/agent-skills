# Changelog

## 1.2.0

- Added explicit CRD cleanup step (step 5) to the Uninstall ODF procedure in `references/maintenance-uninstall.md`, listing all CRDs installed by ODF + LSO across five API groups. CRDs with `customresourcecleanup.apiextensions.k8s.io` finalizer block until all CR instances are gone.
- Updated Post-Uninstall Audit in `references/maintenance-uninstall.md` to check all five CRD groups (`ocs.openshift.io`, `ceph.rook.io`, `noobaa.io`, `csi.ceph.io`, `local.storage.openshift.io`), both `openshift-storage` and `rook-ceph` namespaces, and stuck Terminating PVCs/PVs.
- Added new **Stuck Namespace / Orphaned CRs** section to `references/maintenance-uninstall.md` with: detection commands, recreate-namespace → strip-finalizers → delete CRs → delete namespace pattern, and force-finalize procedure for namespaces stuck in Terminating via the `/finalize` API subresource.

## 1.1.0

- Added ODF 4.22 SNO validated scenario to `references/validated-odf-sno.md` documenting regression workarounds: `SINGLE_NODE=true` CSV patch, `topologyKey` placement overrides (mon, deviceSet placement/preparePlacement), pool size manual reduction with `reconcileStrategy: ignore`, CSI controller replica fix, and `rook-config-override` ConfigMap.
- Added upstream Rook conflict detection and cleanup gate to `references/install-and-preflight.md` Live Discovery section.
- Added ODF 4.22 SNO pointer note to the SNO StorageCluster section in `references/install-and-preflight.md`.
- Updated `references/local-storage-disks.md`: added full-disk zeroing requirement for disks previously used as Ceph BlueStore OSDs (wipefs alone is insufficient); added `LocalVolume` as a named exception path when multiple storage systems share a node.
- Added version-scoped exception in `SKILL.md` Core Safety Rules for ODF 4.22 SNO direct pool CR editing.

## 1.0.0

- Initial release of the OpenShift Data Foundation (ODF) lifecycle skill.
- Covers discovery, OLM-based install, Local Storage Operator disk preparation, ceph-rbd block, cephfs filesystem, MCG/NooBaa and RGW object storage, capacity expand/shrink, upgrade, backup/restore/DR, maintenance, uninstall, validation, hardening, and troubleshooting.
- Emphasizes ODF best practices: OLM `Subscription` install in `openshift-storage`, driving all changes through the `StorageCluster` CR, and never hand-editing the ODF-owned Rook CRs.
