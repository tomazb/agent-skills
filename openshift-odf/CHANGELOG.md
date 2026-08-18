# Changelog

## 1.5.0

- Updated the `SKILL.md` Core Safety Rules ODF 4.20/4.22 SNO exception to add the `cephFilesystems` reconcile freeze + `CephFilesystem` CR patches, the empty-`topologyKey` and pool-sizing steps, and to scope the "do not enable CephFS" caveat to 4.22 (CephFS was validated on 4.20 SNO).
- Extended the **ODF 4.20 SNO** scenario in `references/validated-odf-sno.md`: added **Regression 4 (empty `topologyKey` on CephFilesystem MDS and CephObjectStore RGW placements)** with symptoms and patches, extended **Regression 2** pool sizing to CephFilesystem and CephObjectStore metadata/data pools (`size: 1`, `failureDomain: host`, drop `replicasPerFailureDomain`) and the `cephFilesystems` reconcile freeze, and noted that the `.mgr` pool reverts to `size=3` after any mgr restart.
- Added an onboarding-recovery troubleshooting entry to `references/validation-hardening.md` for the internal `StorageClient` stuck `Initializing` with a `crypto/rsa: verification error`, plus a `.mgr` post-reboot drift check.
- Added a **virtio / no `/dev/disk/by-id/`** udev MachineConfig recipe to `references/local-storage-disks.md`, including the ignition `data:` `%20`-not-`+` encoding caveat.
- Added `scripts/render_sno_remediation.py` (generator, review-before-run) that emits the deterministic ODF 4.20 SNO patches (reconcile ignore, MDS/RGW `topologyKey`, CephBlockPool failure domain, CSI `Driver` replicas, `POOL_NO_REDUNDANCY` mute); pool sizing and onboarding remain runbook-only. Covered by `tests/test_render_sno_remediation.py`.

## 1.4.0

- Added early SNO topology detection: `oc get infrastructure cluster` is now an explicit discovery step in `references/install-and-preflight.md` Live Discovery and in `SKILL.md` Inputs To Collect; `SingleReplica` result triggers the SNO path.
- Added **SNO Pre-flight Gate** to `references/install-and-preflight.md`: when `controlPlaneTopology: SingleReplica` is detected and the target ODF channel is `stable-4.20` or `stable-4.22`, the runbook hard-stops and routes to the matching section in `references/validated-odf-sno.md` instead of the generic install path.
- Added complete **ODF 4.20 SNO Scenario** section to `references/validated-odf-sno.md` (OCP 4.20.32, ODF 4.20.16-rhodf) documenting all required workarounds in deployment order: `flexibleScaling: true` + placement overrides baked into the StorageCluster, `SINGLE_NODE=true` CSV patch, pool size manual reduction, ODF 4.20-specific `CephBlockPool` `failureDomain: host` + `replicasPerFailureDomain` removal, CSI controller replicas via `Driver` CRs (not `OperatorConfig`), and `rook-config-override` ConfigMap.
- Extended `SKILL.md` Core Safety Rules exception from "ODF 4.22 SNO only" to "ODF 4.20 and 4.22 SNO", documenting the two additional 4.20-specific steps (CephBlockPool failureDomain fix and Driver CR CSI fix).
- Updated `SKILL.md` Routing line for `references/validated-odf-sno.md` to mention 4.16, 4.20, and 4.22.
- Updated `SKILL.md` Inputs To Collect and `references/install-and-preflight.md` "additional required steps" pointer to name both ODF 4.20 and 4.22.

## 1.3.0

- Added Product Ownership Gate for ODF vs upstream Rook classification, openshift-versions handoff, and concrete helper invocations for StorageCluster and smoke manifests.

## 1.2.0

- Added explicit CRD cleanup step (step 5) to the Uninstall ODF procedure in `references/maintenance-uninstall.md`, listing all CRDs installed by ODF + LSO across five API groups. CRDs with `customresourcecleanup.apiextensions.k8s.io` finalizer block until all CR instances are gone.
- Updated Post-Uninstall Audit in `references/maintenance-uninstall.md` to check all five CRD groups (`ocs.openshift.io`, `ceph.rook.io`, `noobaa.io`, `csi.ceph.io`, `local.storage.openshift.io`), both `openshift-storage` and `rook-ceph` namespaces, and stuck Terminating PVCs/PVs.
- Added new **Stuck Namespace / Orphaned CRs** section to `references/maintenance-uninstall.md` with: detection commands, recreate-namespace → strip-finalizers → delete CRs → delete namespace pattern, and force-finalize procedure for namespaces stuck in Terminating via the `/finalize` API subresource.
- Aligned `scripts/post_uninstall_audit.sh` with the five CRD groups, `rook-ceph` namespace absence, and Terminating PVC/PV checks; synced `package.json` and `README.md` to 1.2.0.

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
