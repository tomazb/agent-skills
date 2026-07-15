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
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph dashboard get-prometheus-api-host || true
```

Confirm exactly one default StorageClass when defaulting is expected.

## Smoke Test

Create a namespace, PVC, and writer pod using the intended StorageClass. Validate:

- PVC is `Bound`.
- pod reaches `Ready`.
- write/read succeeds.
- RBD/CephFS volume is healthy.
- replica count matches SNO or multi-node policy.
- `oc get sc` shows exactly one default StorageClass.

Use unique smoke namespaces per mode, for example `rook-rbd-smoke` and `rook-cephfs-smoke`, so cleanup and audit commands are unambiguous.

Minimum smoke flow for RBD (pod name `rbd-smoke-writer` matches `scripts/render_smoke_manifest.py` output):

```bash
oc apply -f /tmp/rook-rbd-smoke.yaml
oc -n rook-rbd-smoke wait pod/rbd-smoke-writer --for=condition=Ready --timeout=5m
oc -n rook-rbd-smoke exec rbd-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
```

Minimum smoke flow for CephFS (pod name `cephfs-smoke-writer`):

```bash
oc apply -f /tmp/rook-cephfs-smoke.yaml
oc -n rook-cephfs-smoke wait pod/cephfs-smoke-writer --for=condition=Ready --timeout=5m
oc -n rook-cephfs-smoke exec cephfs-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
```

If the helper is unavailable, adapt `assets/smoke-pvc-writer.yaml` and replace every placeholder before applying it.

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
- One default StorageClass remains.
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
