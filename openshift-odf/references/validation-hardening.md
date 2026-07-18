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
oc apply -f /tmp/odf-rbd-smoke.yaml
oc -n odf-rbd-smoke wait pod/rbd-smoke-writer --for=condition=Ready --timeout=5m
oc -n odf-rbd-smoke exec rbd-smoke-writer -- cat /data/smoke-probe
```

Minimum smoke flow for CephFS (pod name `cephfs-smoke-writer`):

```bash
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
