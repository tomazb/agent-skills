# Upgrade

Use this runbook for ODF upgrades on OpenShift/OKD. ODF is upgraded through OLM; for internal and internal-attached deployments, the Ceph version is bundled with each ODF release and is not upgraded independently. For external deployments, upgrade only the ODF service layer here and follow the separate RHCS upgrade procedure for the backend Ceph cluster.

## Pre-Upgrade Health Check

For internal and internal-attached deployments, run these checks before any upgrade step. Do not proceed unless all PGs are `active+clean` and all OSDs are `up`:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph health detail
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph pg stat
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd stat
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
```

Back up the `StorageCluster` and related CRs before proceeding (see `references/backup-restore-dr.md`).

## Interoperability And Order

- Verify the OpenShift and ODF versions are compatible in the Red Hat interoperability matrix. ODF must be upgraded within the version skew supported for the running OpenShift release.
- Upgrade OpenShift and ODF in the documented order for your path. As a rule, keep ODF within one minor version of OpenShift and follow the release notes.
- Never mix-and-match Ceph versions by hand: ODF bundles a specific Ceph image per release. Do not patch `cephVersion.image` on the Rook `CephCluster` to force a different Ceph build; `ocs-operator` owns that image.

## Operator Upgrade (OLM)

ODF was installed via an OperatorHub `Subscription` in `openshift-storage`. Upgrade through OLM; never apply upstream Rook manifests on top of an OLM-managed operator.

```bash
oc -n openshift-storage get subscription
oc -n openshift-storage get csv
```

### Automatic approval

With `installPlanApproval: Automatic`, moving the Subscription to a newer channel triggers the upgrade. Update the channel to the next supported stream:

```bash
oc -n openshift-storage patch subscription odf-operator --type=merge \
  -p '{"spec":{"channel":"<stable-x.y>"}}'
```

### Manual approval

With `installPlanApproval: Manual`, find and approve the pending InstallPlan after setting the channel:

```bash
oc -n openshift-storage get installplan
oc -n openshift-storage patch installplan <installplan-name> \
  --type=merge -p '{"spec":{"approved":true}}'
```

Wait for the new CSV to reach `Succeeded` and for the operators to roll out:

```bash
oc -n openshift-storage wait csv -l operators.coreos.com/odf-operator.openshift-storage \
  --for=jsonpath='{.status.phase}'=Succeeded --timeout=20m
oc -n openshift-storage rollout status deploy/rook-ceph-operator --timeout=10m
oc -n openshift-storage get csv,pods -o wide
```

## Ceph Upgrade (operator-driven, internal deployments)

For internal and internal-attached deployments, do not upgrade Ceph directly on ODF. When the ODF operator upgrade completes, `ocs-operator` and `rook-ceph-operator` roll the bundled Ceph image into the mons, OSDs, MDS, and RGW automatically. Watch the `StorageCluster` and `CephCluster` reach Ready and confirm the new Ceph version:

```bash
oc -n openshift-storage wait storagecluster/ocs-storagecluster \
  --for=jsonpath='{.status.phase}'=Ready --timeout=30m
oc -n openshift-storage get cephcluster -o wide
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph versions
```

## Upgrade Safety Rules

- Do not downgrade the ODF operator or Ceph versions.
- Read the ODF release notes and upgrade guide before applying a new version.
- Verify all PGs are `active+clean` and all OSDs are `up` before starting the upgrade.
- Upgrade in the supported ODF/OpenShift order; do not skip minor ODF versions unless the upgrade path documents it.
- Document the difference between the ODF operator channel/version and the bundled Ceph (cluster image) version. They move together per ODF release.
- If the upgrade fails, do not proceed with additional changes. Diagnose the CSV/InstallPlan and operator logs, and only roll back through OLM if the path is supported.

## Upgrade Validation

After upgrade, confirm:

- The ODF CSV is `Succeeded` and operator pods are running and healthy.
- All mons are in quorum.
- All OSDs are `up` and `in`.
- MDS is active (if CephFS is used).
- RGW gateways are running (if object store is used).
- Ceph cluster health is `HEALTH_OK` or `HEALTH_WARN` with known, documented warnings.
- No PGs are stuck in `creating`, `degraded`, or `peering`.
- The default ODF StorageClasses still exist and exactly one default StorageClass remains when defaulting is expected.

## Post-Upgrade Drift On Single-Replica SNO

An upgrade restarts the mgr and re-rolls the CSI plugins, which undoes several
single-node workarounds. All of this was observed on an unattended 4.20.16 →
4.20.17 z-stream upgrade, so run these checks after **any** ODF upgrade on a
single-OSD SNO cluster, including automatic ones.

```bash
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"

# 1. The mgr restarted, so .mgr is recreated at size 3 on a single OSD. That
#    shows up as undersized PGs and "Degraded data redundancy", not as an
#    obvious pool problem.
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool get .mgr size

# 2. Health mutes do not survive the upgrade, so POOL_NO_REDUNDANCY returns as
#    an unmuted warning even once the pools are correct again.
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" health detail

# 3. The CSI ctrlplugin rollout deadlocks on one node: two live ReplicaSets per
#    driver, the new pod Pending. See "The single-replica fix does not survive
#    the next image change" in references/validated-odf-sno.md.
oc -n openshift-storage get rs | grep ctrlplugin
```

If `.mgr` is back at `size 3`, re-apply the reduction, **prove the PGs
recovered**, and only then re-mute:

```bash
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" \
  osd pool set .mgr size 1 --yes-i-really-mean-it
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool set .mgr min_size 1

# Verify recovery explicitly: every PG active+clean, none undersized or
# degraded. Do not infer this from the absence of warnings.
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" pg stat
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" health detail

oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" health mute POOL_NO_REDUNDANCY
```

The explicit PG check is the safeguard, not the ordering. `POOL_NO_REDUNDANCY`
and the undersized/degraded PG checks are **separate** health checks, so muting
the former never hides the latter — on the observed cluster the undersized-PG
warning was plainly visible while `POOL_NO_REDUNDANCY` was already muted.
Re-mute last because it is the last step, not because it would conceal
anything.

Also re-read `.status.phase` on the `StorageCluster` against its conditions
rather than on its own: a z-stream can leave `phase: Error` from a reconcile
check that does not reflect serving state. See the `flexibleScaling` note in
`references/validated-odf-sno.md`.
