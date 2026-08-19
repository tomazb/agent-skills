# Changelog

## 1.6.0

- Validated ODF 4.22.1 SNO **with CephFS**: RBD (RWO), CephFS (RWX), and Object (OBC) all pass; `StorageCluster` Ready, `HEALTH_OK`, `lvms-vg1` remained the sole default.
- Documented the empty-`topologyKey` fixes for **MDS and RGW** on 4.22 (CephFS + Object), which the mon/OSD fix alone does not cover.
- New regression: on Ceph 20.2 "tentacle" (ODF 4.22.1) the `CephObjectStore`/`CephFilesystem` metadata/data pools reject `size=1` while `replicasPerFailureDomain=1` — remove the field (block pools tolerate it).
- New: SNO CPU-request starvation workaround via minimal `spec.resources` requests (`resourceProfile: lean` remains unsafe on 4.22 — traps `Progressing`).
- Corrected the CSI ctrlplugin replica fix to patch the per-`drivers.csi.ceph.io` CRs (the `operatorconfigs.csi.ceph.io` patch is reverted on 4.22.1).
- Refined the StorageClient onboarding-signature recovery to a convergent token-only regeneration (never delete the keys after the token; restart `ocs-operator` once).
- Extended `scripts/render_sno_remediation.py` to emit the 4.22 object/file pool `replicasPerFailureDomain` removal and the minimal resource-request patches.
- Lifted the "do not enable CephFS on 4.22" caveat in `SKILL.md`.

Review-round fixes:

- `scripts/render_sno_remediation.py` now requires `--release {4.20,4.22}` and gates the release-specific blocks: the CephBlockPool failure-domain fix is 4.20-only, while the object/file `replicasPerFailureDomain` removal and the resource-request floor are 4.22-only. One script previously mixed both, so under `set -e` it aborted on the first inapplicable patch. Step numbers are assigned at render time so each release gets a contiguous sequence.
- The generator validates `--name`/`--namespace` as RFC 1123 names and rejects anything else, instead of interpolating operator-supplied values straight into executable shell.
- The `POOL_NO_REDUNDANCY` mute is emitted as commented guidance only: muting it before pool sizing (which the generator deliberately does not perform) hides a still-legitimate warning.
- The 4.22 block now emits a fail-closed precondition that exactly one `CephFilesystem` data pool exists, since the patch targets `/spec/dataPools/0`.
- Added command-level tests for the CLI entry point (`--output`, stdout, missing/invalid `--release`, rejected names), per-release output assertions, and value-level assertions on the rendered resource requests.
- `references/validated-odf-sno.md`: the 4.20 `CephBlockPool` patch now persists `size: 1` + `requireSafeReplicaSize: false` in the CR — `cephBlockPools: ignore` only stops ocs-operator, and Rook still reconciles the CR back over the live `ceph osd pool set`. The `SINGLE_NODE` CSV patch selects exactly one `ocs-operator` CSV and aborts when the variable is already present. The placement claim is scoped to mon/OSD/OSD-prepare, and the `replicasPerFailureDomain` rationale section now references Step 2b instead of repeating its non-idempotent `remove` patches.
- Added a **Restoring Managed Reconciliation After Upgrade** section: the workarounds leave three `reconcileStrategy: ignore` values and a `rook-config-override` ConfigMap behind, with no documented path back to `manage`.
- `references/validation-hardening.md`: the onboarding recovery now actually compares the RSA moduli it claims to check, selects the token by its `StorageConsumer` owner reference instead of `grep | head -1`, targets `openshift-storage` explicitly, and no longer hides a failed finalizer patch behind `|| true`.
- `references/local-storage-disks.md`: the udev rule gains `ENV{DEVTYPE}=="disk"` (partitions share the parent's `ID_PATH` and would otherwise claim the same symlink), with a `DEVTYPE`/`ID_PATH` verification step.
- `SKILL.md`: noted that ODF 4.20 does not reduce the SNO mon count (3 mons + 1 mgr), which contradicted the generic "reduced mon/mgr counts" rule.
- Added `tests/test_odf_sno_install_gate_contracts.py` pinning the SNO pre-flight gate invariants: topology discovery, both affected channels, gate-before-install ordering, and per-version routing.

Second review round:

- The generated script now opens with a release preflight that reads the installed `ocs-operator` CSV and exits before the first patch when it does not match `--release`. `--release` only selected templates, and `set -e` aborts a mismatched run only after the earlier still-valid patches have already mutated the cluster.
- `--name`/`--namespace` are also rejected past 63 characters (the RFC 1123 label limit Kubernetes enforces), so an over-long value fails at render time instead of on every emitted `oc` command.
- The restore-after-upgrade verification queries each pool spec at its real path: `.spec.replicated.size` exists on `CephBlockPool` only, so the object-store and filesystem pools previously read back blank and the check passed silently.
- The onboarding recovery exits when either key secret is missing or either modulus is empty, and a mismatched pair now stops the procedure instead of prescribing key deletion inline — deleting the pair invalidates every token signed with it and is documented as a separate, deliberate decision.
- The virtio disk verification uses exact `grep -Fx` assertions on `DEVTYPE=disk` and the expected `ID_PATH`, so it fails closed instead of printing whichever property happens to be present.
- Condensed the `SKILL.md` 4.20/4.22 SNO exception to the safety gate, the permitted scope of direct Rook CR editing, and the pointer to `references/validated-odf-sno.md`, per the repo convention of keeping skill instructions concise.

Third review round:

- Name validation uses `fullmatch`: `$` also matches before a trailing newline, so `"my-ns\n"` passed and would have split every emitted `oc` command in two.
- The release preflight resolves to exactly one `ocs-operator` CSV before comparing releases. A shell glob matches across newlines, so a newline-separated CSV list whose first entry was the right release satisfied the check while the cluster state was ambiguous. It now exits on zero and on more than one CSV.
- Added tests that execute the emitted preflight against a stubbed `oc`, asserting the ambiguous, wrong-release, and missing-CSV cases exit 1 with nothing mutated, and that a matching release proceeds to the first patch.

Re-validated against the live ODF 4.20.16-rhodf SNO cluster:

- Confirmed the 4.20 `CephBlockPool` size patch is required: `managedFields` shows `size`, `requireSafeReplicaSize`, and `failureDomain` owned by `kubectl-patch` while `ocs-operator` owns only `targetSizeRatio`. The runbook had documented only the failure-domain half of what was actually applied.
- Corrected the rationale for that patch. Rook does not rewrite pools continuously: `builtin-mgr` still carries `size: 3` against a live `.mgr` pool at `size 1`, and rook logged no pool reconcile in 24h. The CR is the desired state applied at the *next triggered* reconcile, so a stale value is a latent revert — which is what makes `.mgr` snap back after a mgr restart.
- Corrected the 4.20 StorageClass note: no default StorageClass exists on the validated cluster at all (`localblock` included), rather than a pre-existing default being preserved.
- Recorded the re-verification in `references/validated-odf-sno.md`: HEALTH_OK, 3 mons + 1 mgr, all 12 pools `size 1`, single `SINGLE_NODE` env entry, both CSI `Driver` CRs at `replicas: 1`, MDS/RGW `topologyKey` fixed, and one CephFilesystem data pool.

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
