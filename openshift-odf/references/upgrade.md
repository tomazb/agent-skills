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
