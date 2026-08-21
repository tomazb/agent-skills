# Changelog

## 1.11.0

- Hardened the uninstall and preflight runbooks with findings from a live Rook→ODF→Rook round-trip on SNO:
  - **`references/install-and-preflight.md`** — the Leftover Install Detection now checks `/dev/rbd*` and `/sys/bus/rbd/devices` for stale krbd mappings (ODF's NooBaa DB and any `ceph-rbd` PVC use RBD), which otherwise hang a later OSD prepare's `ceph-volume raw list`.
  - **`references/maintenance-uninstall.md`** — documented that the `reconcileStrategy: ignore` teardown block covers `cephBlockPools`, `cephObjectStores`, **and** `cephFilesystems`, and that the `CephCluster` also waits on `CephBlockPoolRadosNamespace`, `CephClient`, `CephFilesystemSubVolumeGroup`, and `CephObjectStoreUser` dependents plus NooBaa's `graceful_finalizer`; added the `cluster-cleanup-job` hang on `ceph-volume raw/lvm list` and the stale-krbd cross-check.
  - **`references/validated-odf-sno.md`** — added an ODF 4.20.17 fresh-install observations section: `enableCephTools` is rejected as an unknown field (use the rook-operator ceph path), `ocs-operator` runs 0 replicas until a StorageCluster exists (Regression 1 verification gap), and the misleading `dmcrypt` wording in ceph-volume raw prepare.
- Extended the package validator and tests to enforce the new leftover-detection, teardown-dependents, and 4.20.17 install guidance.

## 1.10.0

- Added a **Leftover Install Detection (ODF or Rook)** subsection to `references/install-and-preflight.md`. A prior ODF uninstall and a prior upstream Rook uninstall leave the same Ceph/Rook byproducts, so the preflight now checks for *either* product's leftovers — namespaces, CRDs, orphaned StorageClasses/CSIDrivers/SCCs, stale `/var/lib/rook/mon-*` dirs, and residual BlueStore disk labels — before installing, and routes cleanup to the ODF or Rook uninstall runbook as appropriate.
- Extended the package validator and tests to enforce the new leftover-detection guidance.

## 1.9.0

Drift observed on a live SNO cluster after an unattended ODF 4.20.16 → 4.20.17 z-stream upgrade. All three effects were found on a cluster that had every documented 4.20 SNO workaround correctly applied, so none of them are misconfiguration:

- **The CSI ctrlplugin single-replica fix does not survive the next image change.** Setting the `Driver` CRs to `replicas: 1` prevents the initial scheduling failure, but every later CSI image update deadlocks the rollout on one node: `maxUnavailable: 25%` of 1 replica rounds down to 0 so the outgoing pod is never removed, `maxSurge` rounds up to 1 so a new pod is created, and hard pod anti-affinity forbids it landing on the only node. The new pods sat `Pending` for 13 hours while the Deployment still reported `1/1`, hiding it from any pod-count check. Documented in `references/validated-odf-sno.md` with the ReplicaSet-pair symptom and the delete-the-old-pod remedy.
- **`flexibleScaling: true` does not silence the node-count reconcile error on 4.20.17.** The runbook claimed it does. The upgraded cluster carries `.status.phase: Error` with `Not enough nodes found: Expected 3, found 1` logged ~200 times an hour while `Available=True`, `Degraded=False`, `ceph -s` is `HEALTH_OK` and all three storage modes serve normally. The claim is now qualified, with instructions to read the conditions rather than gate on `phase`.
- **Added a Post-Upgrade Drift On Single-Replica SNO section to `references/upgrade.md`.** The upgrade restarts the mgr, so `.mgr` returns to `size 3` and produces undersized PGs, and health mutes do not survive, so `POOL_NO_REDUNDANCY` comes back unmuted. The remediation is spelled out: reduce the pool size, verify explicitly with `pg stat` / `health detail` that no PGs remain undersized or degraded, then re-mute. The verification is the safeguard — `POOL_NO_REDUNDANCY` and the PG health checks are separate, so the mute never hides an unrecovered PG.
- Added `tests/test_odf_sno_upgrade_drift_contracts.py` covering all three.

Review round:

- Corrected the stated reason for the remediation order. `POOL_NO_REDUNDANCY` and the undersized/degraded PG checks are separate Ceph health checks, so muting the former never hides the latter — on the observed cluster the undersized-PG warning was visible while `POOL_NO_REDUNDANCY` was already muted. The safeguard is now an explicit `pg stat` / `health detail` verification between reducing `.mgr` and re-muting, rather than ordering alone.
- Tightened the contract tests from keyword presence to the remediation contract: the ctrlplugin section must carry both sides of the rollout arithmetic, the ReplicaSet check, the delete-the-old-pod remedy and one-driver-at-a-time recovery; the upgrade section must carry both `.mgr` commands with the PG check between the fix and the mute; the `flexibleScaling` qualification must be anchored at the claim itself and name the release, the exact error, and the conditions to trust.

## 1.8.0

Validation-runbook fixes from a live ODF 4.20.16 SNO validation:

- Core Validation reached Ceph only through `deploy/rook-ceph-tools`, so on a cluster without the toolbox the documented path was to patch `OCSInitialization` and create it — a validation pass mutating the cluster it validates. It now also documents the read-only route through the running `rook-ceph-operator` pod with `ceph -c <config>`, which is the form the `.mgr` drift check and `references/validated-odf-sno.md` already use.
- "Exactly one default StorageClass" was asserted unscoped in the smoke checklist and the post-reboot drift list, while the Core Validation prose correctly scoped it to "when defaulting is expected". ODF does not claim the default on install, so a cluster can deliberately have none; stated flatly the check turns that policy into a reported failure. Both now scope it, and note that with no default a PVC omitting `storageClassName` stays `Pending`.
- The smoke section stopped at block and file, so a validation run on a cluster with RGW or MCG enabled silently skipped the object path. Added an object-storage subsection pointing at the existing `ObjectBucketClaim` flow in `references/object-mcg-rgw.md`, with the success criteria (`Bound`, `.spec.bucketName`, generated ConfigMap and Secret) and the cleanup check.
- Added `tests/test_odf_validation_runbook_contracts.py` covering all three.

Review round:

- The Ceph CLI checks are now presented as an explicit choice *before* any toolbox-dependent command, with the read-only rook-operator route first. The earlier fix was additive, so a reader working top-to-bottom still hit four failing `exec deploy/rook-ceph-tools` commands before reaching the alternative.
- The object smoke flow names a dedicated `odf-object-smoke` namespace instead of a `<obc-namespace>` placeholder. Cleanup deletes that namespace, so a placeholder invited pointing it at a live application namespace.
- The object check no longer stops at OBC provisioning. An OBC reaches `Bound` with its ConfigMap and Secret created while the endpoint or credentials are unusable, so metadata-only validation reports a healthy object service on a broken data plane. Added an S3 PUT/GET/DELETE using the generated `BUCKET_HOST`/`BUCKET_PORT`/`BUCKET_NAME` and credentials via `envFrom`, pointed at the in-cluster service-CA bundle for the RGW service's TLS on 443. Verified end to end against a live 4.20.16 cluster; the `pip install boto3` egress dependency and the disconnected-cluster alternative are called out.

Second review round:

- The S3 snippet normalizes `BUCKET_HOST` instead of prefixing `https://` unconditionally. It is a bare hostname on the RGW StorageClass but can already carry a scheme on the MCG one, which produced `https://https://…`.
- The cleanup verification fails closed. `oc get objectbucket | grep X || echo ok` exits 0 whether or not a leftover is found and hides a failed query behind the pipe, so it could never report incomplete cleanup — the same shape as the object check it follows.
- The contract test now requires the DELETE step and every generated field the snippet consumes (`BUCKET_PORT`, `BUCKET_NAME`, `AWS_SECRET_ACCESS_KEY` were droppable without failing it), and asserts the cleanup check can fail.

## 1.7.0

Uninstall runbook fixes validated on a live ODF 4.22.1 SNO undeploy (shared `openshift-storage` namespace with LVMS + LSO):

- Added step 0 namespace inventory gate to `references/maintenance-uninstall.md`: LVMS installs into `openshift-storage` by default; blanket subscription deletion and unconditional namespace deletion destroy LVMS/LSO. Namespace deletion is now guarded on an empty subscription list, and ODF subscriptions/CSVs are deleted by package name via `.status.installedCSV` (the odf-operator CSV label selector matches only 1 of the 12 component CSVs).
- Documented that the ODF 4.20/4.22 SNO `reconcileStrategy: ignore` workaround blocks graceful uninstall: `ocs-operator` skips the ignored pools and rook loops on `will not be deleted until all dependents are removed` for `builtin-mgr`/`ocs-storagecluster-cephblockpool`. Resolution: delete the leftover `CephBlockPool` CRs directly. Cross-referenced from `references/validated-odf-sno.md`.
- Added disk-wipe verification (`cluster-cleanup-job-<node>`, `lsblk -f` signature check) and clarified the cleanup job quick-sanitizes rather than fully zeroes.
- LSO ownership discovery now uses the local PV labels (`storage.openshift.com/owner-namespace`) instead of assuming `openshift-local-storage`; documented the `LocalVolumeSet` deletion cascade (PVs + StorageClass) and the Available-PV recreation race on the wiped disk.
- Added step 4b residue sweep for a kept namespace: `drivers.csi.ceph.io` CRs (cascade deployments/daemonsets), CSIDrivers, `ocs-client-operator-console` Service (service-ca keeps re-creating its cert secret), configmap pinned by the orphaned `ocs-client-operator.ocs.openshift.io/storageused` finalizer, rook mon state (`rook-ceph-pdbstatemap`, `rook-config-override`, keyrings — reinstall poison), ODF SCCs, `csv.odf.openshift.io` mutating webhook, and `odf-console`/`odf-client-console` consoleplugins.
- CRD cleanup now sweeps by API group per release instead of a fixed list, adding `odf.openshift.io` and the NooBaa embedded CloudNativePG group `postgresql.cnpg.noobaa.io`; `local.storage.openshift.io` is skipped while LSO stays installed and shared `groupsnapshot.storage.openshift.io` CRDs are left in place.
- `scripts/post_uninstall_audit.sh`: accepts a kept `openshift-storage` namespace when non-ODF operators remain (then sweeps it for leftover ODF subscriptions, CSVs, and residue objects including StatefulSets), treats retained `local.storage.openshift.io` CRDs as OK **only while LSO is still installed**, and audits the two new CRD groups, `ceph-csi` SCCs, the ODF mutating webhook, and consoleplugins.
- Added contract tests `tests/test_odf_uninstall_runbook_contracts.py` and audit-script tests for the kept-namespace and retained-LSO scenarios.

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
