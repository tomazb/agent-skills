# Validation Hardening And Troubleshooting

Use this runbook after install, upgrade, reboot, maintenance, or incident response.

## Core Validation

```bash
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc -n rook-ceph get pods -o wide
oc -n rook-ceph get cephcluster -o wide
oc -n rook-ceph get cephblockpool,cephfilesystem,cephobjectstore -o wide
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df
```

Check optional routes if the dashboard or RGW was exposed:

```bash
oc -n rook-ceph get route rook-ceph-dashboard -o wide 2>/dev/null || echo "dashboard route not deployed"
oc -n rook-ceph get route rook-ceph-rgw -o wide 2>/dev/null || echo "RGW route not deployed"
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph dashboard get-prometheus-api-host || echo "dashboard Prometheus API host not configured"
```

Confirm exactly one default StorageClass when defaulting is expected.

## Snapshot readiness

Run the read-only [snapshot readiness inventory](backup-restore-dr.md#snapshot-readiness) during every validation, including clusters with no PVCs. Report supported but unconfigured drivers as **Warning**, alongside Ceph runtime health; a healthy cluster can still lack snapshot protection. Record Supported, Configured, Scheduled, and Restore-tested for each StorageClass. Configure missing supported classes during authorized setup/remediation; validation alone does not authorize mutations or production-volume tests.

## CephX cipher warnings on existing clusters

For Rook **1.20.5 / Ceph 20.2.4** (also check the installed version's [key-rotation guide](https://github.com/rook/rook/blob/v1.20.5/Documentation/Storage-Configuration/Advanced/cephx-key-rotation.md)), distinguish key material from policy:

- `AUTH_EMERGENCY_CIPHERS_SET`: inspect monitor arguments for `--mon-auth-emergency-allowed-ciphers` and `spec.security.cephx.daemon.keyType`. An explicit daemon override can leave this temporary recovery mechanism enabled even when all keys are AES256K.
- `AUTH_INSECURE_KEYS_ALLOWED` and `AUTH_INSECURE_KEYS_CREATABLE`: inspect `spec.security.cephx.allowedCiphers` and the MonMap policy. An omitted/empty list allows classic AES; creating AES256K keys alone does not restrict it.
- These are authentication-policy warnings, not the expected loss of redundancy on SNO. Do not change pool replica counts, downgrade Ceph, or rotate working keys merely to clear them.

Read the requested policy, effective policy, and monitor arguments:

```bash
oc -n rook-ceph get cephcluster rook-ceph -o jsonpath='{.spec.security.cephx}{"\n"}{.status.cephx}{"\n"}'
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph mon dump --format=json
oc -n rook-ceph get pod -l app=rook-ceph-mon -o jsonpath='{range .items[*]}{range .spec.containers[?(@.name=="mon")]}{.args}{"\n"}{end}{end}'
```

In the MonMap, inspect `auth_allowed_ciphers`, `auth_preferred_cipher`, and `auth_service_cipher`. Cipher policy lives in the MonMap; an empty `ceph config dump` cipher search does not prove the policy is restricted. Redact monitor addresses before recording output.

The audit below prints only key-type counts, including pending, expiring, and rotating keys. The Ceph 20.2.4 schema check requires nonempty conventional and rotating inventories and validates every auth key and every rotating `expiring_key.key`. Missing records, malformed structures, unknown or classic-AES keys, and failed queries return nonzero, including with `PYTHONOPTIMIZE` enabled. Explicit unused `pending_key` slots (`type: 0`, `type_str: none`) are accepted; an empty primary or rotating key is rejected. Do not paste raw auth dumps or key values into evidence. If no toolbox is deployed, use an existing `rook-ceph-operator` Pod with `ceph -c /var/lib/rook/rook-ceph/rook-ceph.config` in place of the toolbox invocation; discovering a warning does not require creating a toolbox.

```bash
# Audit all CephX key types before restricting allowedCiphers.
(
set -euo pipefail
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph auth dump-keys --format=json \
  | python3 scripts/check_cephx_key_types.py
)
```

Observed on OCP **4.20.34**, SNO, Rook **1.20.5 / Ceph 20.2.4**: all 28 audited key records were AES256K, but the MonMap allowed both `aes` and `aes256k`, `allowedCiphers` was omitted, and `daemon.keyType: aes256k` kept the emergency monitor argument enabled. Removing only the daemon override cleared `AUTH_EMERGENCY_CIPHERS_SET` while the two permissive-policy warnings remained. After a fresh kernel RBD write/read probe passed, setting `allowedCiphers: [aes256k]` cleared both remaining warnings. Verify the **effective MonMap**, not just the requested CR value, before treating a test as evidence of the restricted policy.

Post-remediation verification: Ceph `HEALTH_OK` with no health checks, all **217 PGs active+clean**, the single monitor in quorum without an emergency cipher argument, and fresh RBD, CephFS, and NFS PVC write/sync/read probes passed. Post-policy probes require the effective AES256K-only MonMap before claim creation. Smoke namespaces and their claiming PVs were deleted, original PVC/PV/namespace inventories and StorageClasses/defaults were preserved, and the CephCluster spec changed only by removing the daemon override and adding the allowed-cipher list. No key rotation, node drain, or pool change was needed.

For a cluster with that evidence, plan two separate changes through the **CephCluster**, preserving unrelated security settings:

1. Remove only `spec.security.cephx.daemon.keyType`; leave the allowed-cipher policy unchanged. Let Rook reconcile the monitors, then verify quorum and that **every** monitor has lost the emergency argument. Removing this override may restart monitors; on SNO, plan for interruption rather than draining its only node.
2. Re-run the full audit. Only when every key is AES256K and the RBD mount/write probe in `references/install-and-preflight.md` passes on every intended node, set `spec.security.cephx.allowedCiphers: [aes256k]`. Account for external clients, mirror peers, NFS per-export keys, and retained CSI generations before retiring classic AES.

If the audit reports any `aes`, stop before step 2 and use the version-matched migration guide; rotating service tokens may take 2–3 hours to expire. Keep in-use CSI generations until their mounts have migrated. If the audit command or schema is unavailable, do not infer success from key prefixes. After either change, check Ceph health, quorum, OSDs, PGs, the effective MonMap, and fresh RBD/CephFS write/read probes; clean up the smoke namespaces. Do not mute warnings to report a successful fix.

## Smoke Test

For every backend/mode with verified snapshot support, the minimum smoke test also runs `python3 scripts/check_snapshot_smoke.py`. It writes and syncs a token, snapshots the source, changes the source token, restores a new PVC, and compares the restored data with the original token. A ready snapshot or Bound restore PVC is not sufficient. Missing supported snapshot configuration fails this stage; resolve it using [Snapshot readiness](backup-restore-dr.md#snapshot-readiness) before rerunning. Mark verified unsupported combinations **N/A** with the version/mode reason, and unavailable or unverified recovery **untested**; never silently report a complete smoke pass after skipping supported snapshot tests.

Use generated manifests or labeled assets with `app.kubernetes.io/part-of: storage-smoke` on the Namespace, PVC, and writer Pod. The helper refuses unlabeled or non-smoke sources, and requires a Delete-reclaim StorageClass so test PV cleanup can complete. Pass the same explicit target context to source creation, the round-trip helper, and namespace cleanup. Replace the snapshot-class placeholder with the discovered compatible class. Retained snapshot classes are preserved; the helper uses a temporary Delete class for its own snapshots. It checks restored PVC/PV and VolumeSnapshotContent cleanup before success, then the EXIT trap removes and audits the source namespace even if the test fails. Record cleanup failures as failures, retaining the resource names for follow-up. Use a unique namespace per run and replace the example name consistently; the preflight refuses an existing namespace.

Create a namespace, PVC, and writer pod using the intended StorageClass. Validate:

- PVC is `Bound`.
- pod reaches `Ready`.
- write/read succeeds.
- RBD/CephFS volume is healthy.
- replica count matches SNO or multi-node policy.
- `oc get sc` shows exactly one default StorageClass when defaulting is expected. Zero defaults are legitimate when that is the cluster policy; a PVC that omits `storageClassName` then stays Pending.

Use unique smoke namespaces per mode, for example `rook-rbd-smoke` and `rook-cephfs-smoke`, so cleanup and audit commands are unambiguous.

After the snapshot/restore result is recorded, delete that namespace with `scripts/cleanup_smoke_namespace.sh`. The writer command is `sleep 3600` and the pod restarts, so a passing test keeps its volume until this command runs. The script waits for the namespace to disappear and fails if a PV still claims it or a VolumeSnapshotContent still references it. It only deletes a `*-smoke` namespace or `rook-rbd-aes256k-probe`. If a step fails, record the pod events, then run the same cleanup. A finished smoke does not stay on the cluster.

Minimum smoke flow for RBD (pod name `rbd-smoke-writer` matches `scripts/render_smoke_manifest.py` output):

```bash
(
set -euo pipefail
target_context="<target-context>"
smoke_existing=$(oc --context="$target_context" get namespace rook-rbd-smoke --ignore-not-found -o name)
if [ -n "$smoke_existing" ]; then
  echo "refusing to reuse existing namespace rook-rbd-smoke" >&2
  exit 1
fi
python3 scripts/render_smoke_manifest.py \
  --mode rbd \
  --namespace rook-rbd-smoke \
  --storage-class rook-ceph-block \
  --output /tmp/rook-rbd-smoke.yaml

cleanup_smoke() {
  smoke_status=$?
  trap - EXIT
  if ! bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-smoke --context "$target_context"; then
    exit 1
  fi
  exit "$smoke_status"
}
trap cleanup_smoke EXIT


oc --context="$target_context" apply -f /tmp/rook-rbd-smoke.yaml
oc --context="$target_context" -n rook-rbd-smoke wait pod/rbd-smoke-writer --for=condition=Ready --timeout=5m
python3 scripts/check_snapshot_smoke.py \
  --context "$target_context" \
  --namespace rook-rbd-smoke \
  --source-pvc rbd-smoke-pvc --writer-pod rbd-smoke-writer \
  --snapshot-class "<rbd-snapshot-class>"
)
```

Minimum smoke flow for CephFS (pod name `cephfs-smoke-writer`):

```bash
(
set -euo pipefail
target_context="<target-context>"
smoke_existing=$(oc --context="$target_context" get namespace rook-cephfs-smoke --ignore-not-found -o name)
if [ -n "$smoke_existing" ]; then
  echo "refusing to reuse existing namespace rook-cephfs-smoke" >&2
  exit 1
fi
python3 scripts/render_smoke_manifest.py \
  --mode cephfs \
  --namespace rook-cephfs-smoke \
  --storage-class rook-cephfs \
  --output /tmp/rook-cephfs-smoke.yaml

cleanup_smoke() {
  smoke_status=$?
  trap - EXIT
  if ! bash scripts/cleanup_smoke_namespace.sh --namespace rook-cephfs-smoke --context "$target_context"; then
    exit 1
  fi
  exit "$smoke_status"
}
trap cleanup_smoke EXIT


oc --context="$target_context" apply -f /tmp/rook-cephfs-smoke.yaml
oc --context="$target_context" -n rook-cephfs-smoke wait pod/cephfs-smoke-writer --for=condition=Ready --timeout=5m
python3 scripts/check_snapshot_smoke.py \
  --context "$target_context" \
  --namespace rook-cephfs-smoke \
  --source-pvc cephfs-smoke-pvc --writer-pod cephfs-smoke-writer \
  --snapshot-class "<cephfs-snapshot-class>"
)
```

If the helper is unavailable, adapt `assets/smoke-pvc-writer.yaml` and replace every placeholder before applying it. That asset uses namespace `rook-smoke`. Delete it with `bash scripts/cleanup_smoke_namespace.sh --namespace rook-smoke`.

On OpenShift, make smoke pods compatible with restricted PodSecurity by setting `allowPrivilegeEscalation: false`, dropping all capabilities, setting `runAsNonRoot: true` when the image supports it, and setting `seccompProfile.type: RuntimeDefault`.

## Dashboard And Monitoring

- On OpenShift, the working dashboard Route can target the mgr service port named
  `http-dashboard` with edge termination.
- If the built-in OpenShift Prometheus API is auth-protected and the Ceph
  dashboard build does not expose a Prometheus token setting, use an internal
  Prometheus in the `rook-ceph` namespace and point `PROMETHEUS_API_HOST` at it.
- If dashboard history must survive pod restarts, run that internal Prometheus as
  a PVC-backed StatefulSet rather than an ephemeral Deployment.
- If users rely on the dashboard Orchestrator page or `ceph orch`, enable the
  Rook backend once per cluster:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph mgr module enable rook
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph orch set backend rook
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph orch status
```

## Post-Reboot Drift

After a node reboot, check:

- Ceph mons are in quorum.
- All OSDs are `up` and `in`.
- MDS is active (if CephFS is used).
- RGW gateways are running (if object store is used).
- Ceph cluster health is `HEALTH_OK` or `HEALTH_WARN` with known, documented warnings.
- No PGs are stuck in `creating`, `degraded`, or `peering`.
- The default-StorageClass situation is unchanged from before the reboot — one default if defaulting is expected, still none if that was the intended policy.
- MachineConfigs have been applied and MCP is `Updated`.

## Hardening

- Configure backup targets and recurring snapshot schedules.
- Integrate Ceph metrics with OpenShift monitoring via the Rook dashboard or Prometheus.
- Alert on degraded/faulted volumes, failed snapshots, capacity pressure, OSD failures, mon quorum loss, and MDS laggy.
- For multi-node production, prefer at least three replicas and spread across failure domains.
- For SNO, document that one replica is a topology constraint, not high availability.
- Avoid root disk OSD placement unless intentionally accepted.
- Enable RGW TLS via Route or Ingress for production.
- Use CephFS activeStandby for MDS high availability in multi-node clusters.

## Troubleshooting Shape

For incidents, answer with:

- symptom and impact.
- current health evidence.
- likely Ceph layer: mon, mgr, OSD, MDS, RGW, CSI, network, or OpenShift host/MachineConfig.
- commands already run.
- next read-only checks.
- safest remediation and stop conditions.

Collect support data when needed:

```bash
oc -n rook-ceph get events --sort-by=.lastTimestamp
oc -n rook-ceph logs -l app=rook-ceph-osd --tail=200 --prefix=true
oc -n rook-ceph logs deploy/rook-ceph-operator --tail=200
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df
```
