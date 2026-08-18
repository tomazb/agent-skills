# Design: openshift-odf v1.6.0 — ODF 4.22.1 SNO CephFS Validation

## Context

Live deployment of ODF 4.22.1 on OCP 4.22.8 SNO (context `htz2`) **with CephFS
enabled** empirically tested whether the ODF 4.20 SNO fixes (shipped in v1.5.0)
also apply to 4.22.1, and whether the skill's "no CephFS on 4.22" caveat can be
lifted. Result: CephFS works on 4.22.1 once the MDS/RGW topologyKey fixes and a
newly-discovered pool-spec fix are applied. All three storage types (RBD RWO,
CephFS RWX, Object/OBC via RGW) validated; `StorageCluster` Ready, `HEALTH_OK`;
`lvms-vg1` remained the sole default StorageClass.

## Findings

### 4.20 fixes confirmed still required on 4.22.1
- Mon/OSD empty-`topologyKey` (already in the 4.22 section).
- **MDS** empty-`topologyKey` — CephFilesystem stuck `Failure` without it.
- **RGW** empty-`topologyKey` — no RGW pod → NooBaa cannot configure without it.
- Pool `size=1` + reconcile freeze including `cephFilesystems`.
- `.mgr` pool size reversion to 3 (recurs after any mgr restart).
- StorageClient onboarding-signature recovery.

### New 4.22.1 findings (not previously documented)
1. **`replicasPerFailureDomain:1` + `size:1` rejected on object/file metadata
   pools** (Ceph 20.2 "tentacle"): `error pool size is 1 and
   replicasPerFailureDomain is 1, size must be greater`. `CephBlockPool`
   tolerates it, but `CephObjectStore`/`CephFilesystem` reconcile fails, blocking
   RGW and CephFS entirely. Fix: remove `replicasPerFailureDomain` from those
   pools' `replicated` spec (keep `size:1`).
2. **Onboarding-signature recovery ordering**: the documented delete-keys +
   repeated-restart loop races (keys regenerate out of sync with the signed
   token) and never converges. Correct sequence: ensure the key pair
   (`onboarding-private-key` / `onboarding-ticket-key`) exists as a matched pair,
   delete **only** the `onboarding-token-*` secret and the StorageClient, then
   restart `ocs-operator` **once** so it regenerates only the token using the
   existing private key. Never delete the keys after the token; do not restart
   the operator repeatedly.
3. **CSI ctrlplugin replicas not reduced for SNO**: the `operatorconfigs.csi.ceph.io`
   `driverSpecDefaults.controllerPlugin.replicas` patch is reverted by
   ocs-client-operator on 4.22.1. Working target: patch the per-driver
   `drivers.csi.ceph.io` CRs' `spec.controllerPlugin.replicas: 1` (sticks).
4. **CPU-request starvation on SNO**: ODF's default "balanced" resource requests
   (mon 1050m, mds/osd/rgw 2050m, noobaa-core/endpoint 999m) saturate the node's
   schedulable CPU (99% requested vs ~6% used), leaving `noobaa-core` and the
   second CSI replica `Pending` with `Insufficient cpu`. `resourceProfile: lean`
   remains unsafe on 4.22 (traps `Progressing`). Fix: set minimal per-component
   requests via `StorageCluster spec.resources` (mon, mgr, noobaa-*, and OSD via
   `storageDeviceSets[].resources`) plus direct `CephFilesystem`/`CephObjectStore`
   resource patches for the frozen MDS/RGW. Dropped requests 99% → 35%.

## Scope of changes

1. `references/validated-odf-sno.md` — extend the 4.22 section: MDS/RGW
   topologyKey, `replicasPerFailureDomain` removal, CPU-request starvation,
   corrected CSI-replicas target, `.mgr` reversion note, and flip Validation
   Notes to record CephFS validated.
2. `references/validation-hardening.md` — refine the onboarding-signature
   recovery ordering.
3. `SKILL.md` — lift the "no CephFS on 4.22" caveat; enumerate the 4.22 CephFS
   patch set in the Core Safety Rules version-scoped exception.
4. `scripts/render_sno_remediation.py` (+ tests) — emit the deterministic 4.22
   patches (MDS/RGW topologyKey, `replicasPerFailureDomain` removal, per-Driver
   CSI replicas, minimal resource requests) behind a version/target selector.
5. Version bump 1.5.0 → 1.6.0 (VERSION, package.json, README, CHANGELOG).

## Non-goals

- No change to the 4.20 runbook content (already validated in v1.5.0).
- No automatic execution of `oc`/`ceph` from the generator (review-before-run
  contract preserved).
