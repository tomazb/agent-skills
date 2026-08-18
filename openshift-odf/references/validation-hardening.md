# Validation Hardening And Troubleshooting

Use this runbook after install, upgrade, reboot, maintenance, or incident response on ODF.

## Core Validation

```bash
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc -n openshift-storage get csv,pods -o wide
oc -n openshift-storage get storagecluster,cephcluster -o wide
oc -n openshift-storage get cephblockpool,cephfilesystem,cephobjectstore,noobaa -o wide
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph health detail
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd df
```

If the toolbox is not running, enable it first:

```bash
oc patch OCSInitialization ocsinit -n openshift-storage --type merge \
  -p '{"spec":{"enableCephTools":true}}'
oc -n openshift-storage rollout status deploy/rook-ceph-tools --timeout=5m
```

Confirm exactly one default StorageClass when defaulting is expected, and that the ODF StorageClasses (`ocs-storagecluster-ceph-rbd`, `ocs-storagecluster-cephfs`, and `ocs-storagecluster-ceph-rgw` if object storage is enabled) exist.

## Smoke Test

Create a namespace, PVC, and writer pod using the intended StorageClass. Validate:

- PVC is `Bound`.
- pod reaches `Ready`.
- write/read succeeds.
- RBD/CephFS volume is healthy.
- replica count matches SNO or multi-node policy.
- `oc get sc` shows exactly one default StorageClass.

Use unique smoke namespaces per mode, for example `odf-rbd-smoke` and `odf-cephfs-smoke`, so cleanup and audit commands are unambiguous.

Minimum smoke flow for RBD (pod name `rbd-smoke-writer` matches `scripts/render_smoke_manifest.py` output):

```bash
python3 scripts/render_smoke_manifest.py \
  --mode rbd \
  --namespace odf-rbd-smoke \
  --storage-class ocs-storagecluster-ceph-rbd \
  --output /tmp/odf-rbd-smoke.yaml

oc apply -f /tmp/odf-rbd-smoke.yaml
oc -n odf-rbd-smoke wait pod/rbd-smoke-writer --for=condition=Ready --timeout=5m
oc -n odf-rbd-smoke exec rbd-smoke-writer -- cat /data/smoke-probe
```

Minimum smoke flow for CephFS (pod name `cephfs-smoke-writer`):

```bash
python3 scripts/render_smoke_manifest.py \
  --mode cephfs \
  --namespace odf-cephfs-smoke \
  --storage-class ocs-storagecluster-cephfs \
  --output /tmp/odf-cephfs-smoke.yaml

oc apply -f /tmp/odf-cephfs-smoke.yaml
oc -n odf-cephfs-smoke wait pod/cephfs-smoke-writer --for=condition=Ready --timeout=5m
oc -n odf-cephfs-smoke exec cephfs-smoke-writer -- cat /data/smoke-probe
```

If the helper is unavailable, `assets/smoke-pvc-writer.yaml` is the RBD baseline: it uses namespace `odf-smoke`, PVC `smoke-pvc`, pod `smoke-writer`, and StorageClass `ocs-storagecluster-ceph-rbd`. For CephFS, change those names consistently in the apply, wait, and exec commands, set `accessModes` to `ReadWriteMany`, and set `storageClassName` to `ocs-storagecluster-cephfs`.

On OpenShift, make smoke pods compatible with restricted PodSecurity by setting `allowPrivilegeEscalation: false`, dropping all capabilities, setting `runAsNonRoot: true` when the image supports it, and setting `seccompProfile.type: RuntimeDefault`.

## Dashboard And Monitoring

- ODF integrates Ceph metrics with OpenShift monitoring automatically; use the OpenShift console **Storage → Data Foundation** dashboards and the built-in cluster Prometheus. You do not need to stand up a separate Prometheus for ODF as you would on upstream Rook.
- If a user relies on `ceph orch` or the Ceph mgr dashboard directly, that dashboard is managed by ODF; prefer the OpenShift console views and the toolbox for CLI checks.
- Alert on degraded/faulted volumes, failed snapshots, capacity pressure, OSD failures, mon quorum loss, and MDS laggy using the ODF/OpenShift monitoring stack.

## Post-Reboot Drift

After a node reboot, check:

- Ceph mons are in quorum.
- All OSDs are `up` and `in`.
- MDS is active (if CephFS is used).
- RGW gateways are running (if object store is used).
- Ceph cluster health is `HEALTH_OK` or `HEALTH_WARN` with known, documented warnings.
- No PGs are stuck in `creating`, `degraded`, or `peering`.
- One default StorageClass remains.
- MachineConfigs have been applied and MCP is `Updated`.

On single-replica SNO, verify the `.mgr` pool is still `size=1` after any mgr
restart — it is recreated at `size=3` and will re-raise `POOL_NO_REDUNDANCY`
noise / undersized PGs until re-fixed:

```bash
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool get .mgr size
# If 3: re-apply size 1 / min_size 1 as in references/validated-odf-sno.md.
```

## Hardening

- Configure backup targets and recurring snapshot schedules.
- Rely on the ODF/OpenShift monitoring integration for Ceph metrics and alerts.
- For multi-node production, prefer at least three replicas and spread across failure domains.
- For SNO, document that one replica is a topology constraint, not high availability.
- Avoid root disk OSD placement; use dedicated LSO-provisioned disks.
- Enable RGW/MCG TLS via Route for production object endpoints.
- Use CephFS `activeStandby` for MDS high availability in multi-node clusters (ODF sets this by default on multi-node).

## Troubleshooting Shape

For incidents, answer with:

- symptom and impact.
- current health evidence.
- likely layer: ODF operator/CSV, `StorageCluster` reconciliation, Ceph mon, mgr, OSD, MDS, RGW, MCG/NooBaa, CSI, network, or OpenShift host/MachineConfig.
- commands already run.
- next read-only checks.
- safest remediation and stop conditions.

Collect support data when needed:

```bash
oc -n openshift-storage get events --sort-by=.lastTimestamp
oc -n openshift-storage logs -l app=rook-ceph-osd --tail=200 --prefix=true
oc -n openshift-storage logs deploy/rook-ceph-operator --tail=200
oc -n openshift-storage logs deploy/ocs-operator --tail=200
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph health detail
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd df
```

For a full support bundle, use the ODF must-gather image documented for your release.

### StorageClient stuck `Initializing` — onboarding ticket signature error

**Symptom:** after a reinstall, only `ocs-storagecluster-ceph-rgw` exists; the
`ceph-rbd` and `cephfs` StorageClasses are missing. `oc -n openshift-storage get
storageclients.ocs.openshift.io` shows the internal client `Initializing` with an
empty CONSUMER. The provider logs (`deploy/ocs-provider-server`) repeat:

```
Failed to validate onboarding ticket ... failed to verify onboarding ticket
signature. crypto/rsa: verification error
```

**Cause:** a stale onboarding token/keys left over from a previous install cycle.
The `StorageConsumer`-owned `onboarding-token-*` secret was signed with a private
key that no longer matches the public key the provider verifies with, so the
`ocs-client-operator` cannot onboard the consumer and never creates the
`ClientProfile` that gates CSI StorageClass creation.

**Fix — regenerate the onboarding token against a stable key pair:**

The failure is a signature mismatch: the signed `onboarding-token-*` secret was
produced with a private key that no longer matches the public key the provider
verifies with. Repeatedly deleting the keys and restarting races (the keys and
token regenerate out of order) and never converges. Regenerate the **token
only** against the existing key pair:

```bash
# 1. Confirm the key pair exists and is matched (same RSA modulus). If either
#    key is missing, restart ocs-operator once and wait for BOTH to be recreated
#    together before continuing.
oc -n openshift-storage get secret onboarding-private-key onboarding-ticket-key

# 2. Delete ONLY the signed token and the StorageClient (leave the keys intact).
TOKEN=$(oc -n openshift-storage get secret -o name | grep onboarding-token | head -1)
[ -n "$TOKEN" ] && oc -n openshift-storage delete "$TOKEN"
oc delete storageclients.ocs.openshift.io ocs-storagecluster --wait=false
oc patch storageclients.ocs.openshift.io ocs-storagecluster \
  --type merge -p '{"metadata":{"finalizers":[]}}' || true

# 3. Restart ocs-operator ONCE. Because the keys already exist, it regenerates
#    only the missing token — signed with the current private key — and recreates
#    the StorageClient. Do NOT delete the keys or restart repeatedly.
oc -n openshift-storage rollout restart deploy/ocs-operator
```

**Verify:** `oc get storageclients.ocs.openshift.io` shows `Connected` with a
populated CONSUMER, one `clientprofiles.csi.ceph.io` exists, and the
`ocs-storagecluster-ceph-rbd` and `ocs-storagecluster-cephfs` StorageClasses
appear. Observed on ODF 4.22.1 after a StorageCluster delete/recreate; the key
point is to never delete the keys after the token. This recovery is a
leftover-state hazard after repeated
install/delete cycles; a first clean install does not need it.
