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

If the toolbox is not running you have two options. Prefer the second one when
you are validating rather than operating: enabling the toolbox creates a
Deployment, and a validation pass should not have to modify the cluster it is
checking.

Enable the toolbox (persistent, mutates the cluster):

```bash
oc patch OCSInitialization ocsinit -n openshift-storage --type merge \
  -p '{"spec":{"enableCephTools":true}}'
oc -n openshift-storage rollout status deploy/rook-ceph-tools --timeout=5m
```

Or run the same read-only queries through the rook-ceph-operator pod, which is
already running and needs no cluster change. It has the cluster config on disk,
so pass it with `-c`:

```bash
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"

oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" -s
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" health detail
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd tree
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd df
```

Substitute the namespace into `CONF` if the cluster is not in
`openshift-storage`. This is the same form the `.mgr` drift check below uses.

Confirm exactly one default StorageClass when defaulting is expected, and that the ODF StorageClasses (`ocs-storagecluster-ceph-rbd`, `ocs-storagecluster-cephfs`, and `ocs-storagecluster-ceph-rgw` if object storage is enabled) exist.

## Smoke Test

Create a namespace, PVC, and writer pod using the intended StorageClass. Validate:

- PVC is `Bound`.
- pod reaches `Ready`.
- write/read succeeds.
- RBD/CephFS volume is healthy.
- replica count matches SNO or multi-node policy.
- `oc get sc` shows exactly one default StorageClass **when defaulting is expected**. ODF does not claim the default on install, so a cluster can legitimately have none — record the intended policy before treating a count of zero as a failure. Note that with no default, any PVC omitting `storageClassName` stays `Pending`.

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

### Object storage

The renderer covers block and file only. When object storage is enabled — a `CephObjectStore` (RGW) or the MCG `NooBaa` system exists — exercise it too, or a validation pass silently reports success on a cluster whose object path was never touched. Use the `ObjectBucketClaim` flow in `references/object-mcg-rgw.md`, against either the RGW StorageClass (`ocs-storagecluster-ceph-rgw`) or the MCG one (`openshift-storage.noobaa.io`).

A successful OBC reaches `Bound`, sets `.spec.bucketName`, and creates a ConfigMap and a Secret of the same name in the claim's namespace holding the endpoint and S3 credentials:

```bash
oc -n <obc-namespace> get obc <name> -o jsonpath='{.status.phase}{" "}{.spec.bucketName}{"\n"}'
oc -n <obc-namespace> get cm,secret <name>
```

Delete the namespace afterwards and confirm no `objectbucket` objects survive the claim.

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
- The default-StorageClass situation is unchanged from before the reboot — one default if defaulting is expected on this cluster, still none if that was the intended policy. A reboot should not change the count either way.
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
NS=openshift-storage

# 1. Confirm the key pair exists AND is actually a pair. Existence alone proves
#    nothing: two secrets from different install cycles regenerate the same
#    signature mismatch. Compare the RSA moduli and stop if they differ — with a
#    mismatched pair, deleting the token below just reproduces the error.
#    If either key is missing, restart ocs-operator once and wait for BOTH to be
#    recreated together before continuing.
if ! oc -n "$NS" get secret onboarding-private-key onboarding-ticket-key; then
  echo "onboarding keys are missing - restart ocs-operator once, wait for BOTH" >&2
  echo "keys to be recreated together, then re-run this procedure" >&2
  exit 1
fi

# (the secrets hold a single PEM entry; read it without hardcoding its data key)
PRIV_MOD=$(oc -n "$NS" get secret onboarding-private-key -o json \
  | jq -r '.data | to_entries[0].value' | base64 -d \
  | openssl rsa -noout -modulus 2>/dev/null)
PUB_MOD=$(oc -n "$NS" get secret onboarding-ticket-key -o json \
  | jq -r '.data | to_entries[0].value' | base64 -d \
  | openssl rsa -pubin -noout -modulus 2>/dev/null)
if [ -z "$PRIV_MOD" ] || [ -z "$PUB_MOD" ] || [ "$PRIV_MOD" != "$PUB_MOD" ]; then
  echo "onboarding keys are not a matching pair - stop before token recovery" >&2
  exit 1
fi

# 2. Delete ONLY the signed token and the StorageClient (leave the keys intact).
#    Select the token by its StorageConsumer owner reference: a bare
#    'grep onboarding-token | head -1' can pick a stale or another consumer's
#    token and delete the wrong secret. Stop unless exactly one matches.
mapfile -t TOKENS < <(oc -n "$NS" get secret -o json | jq -r \
  '.items[]
   | select(any(.metadata.ownerReferences[]?; .kind == "StorageConsumer"))
   | select(.metadata.name | startswith("onboarding-token"))
   | .metadata.name')
[ "${#TOKENS[@]}" -eq 1 ] || { echo "expected 1 StorageConsumer-owned onboarding token, found ${#TOKENS[@]}: ${TOKENS[*]}" >&2; exit 1; }
oc -n "$NS" delete "secret/${TOKENS[0]}"

oc -n "$NS" delete storageclients.ocs.openshift.io ocs-storagecluster --wait=false
# Strip the finalizer only if the object is still there. `oc patch` has no
# --ignore-not-found, and a blanket `|| true` would also swallow a real patch
# failure, leaving the StorageClient stuck in Terminating with no signal.
if oc -n "$NS" get storageclients.ocs.openshift.io ocs-storagecluster >/dev/null 2>&1; then
  oc -n "$NS" patch storageclients.ocs.openshift.io ocs-storagecluster \
    --type merge -p '{"metadata":{"finalizers":[]}}'
fi

# 3. Restart ocs-operator ONCE. Because the keys already exist, it regenerates
#    only the missing token — signed with the current private key — and recreates
#    the StorageClient. Do NOT delete the keys or restart repeatedly.
oc -n openshift-storage rollout restart deploy/ocs-operator
```

**If the moduli do not match**, stop: this procedure regenerates the token
only, and it cannot converge against a mismatched pair. Deleting the keys is a
separate, more disruptive decision — it invalidates every token signed with
them, so make it deliberately rather than as part of this recovery. Confirm no
other `StorageConsumer` depends on the current pair first, then delete both
keys together and restart `ocs-operator` once so it regenerates the pair and
the token in one pass.

**Verify:** `oc get storageclients.ocs.openshift.io` shows `Connected` with a
populated CONSUMER, one `clientprofiles.csi.ceph.io` exists, and the
`ocs-storagecluster-ceph-rbd` and `ocs-storagecluster-cephfs` StorageClasses
appear. Observed on ODF 4.22.1 after a StorageCluster delete/recreate; the key
point is to never delete the keys after the token. This recovery is a
leftover-state hazard after repeated
install/delete cycles; a first clean install does not need it.
