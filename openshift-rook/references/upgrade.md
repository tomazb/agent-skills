# Upgrade

Use this runbook for Rook operator and Ceph cluster upgrades on OpenShift/OKD.

## Pre-Upgrade Health Check

Run these checks before any upgrade step. Do not proceed unless all PGs are `active+clean` and all OSDs are `up`:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph pg stat
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd stat
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
```

Back up the Rook CRs before proceeding (see `references/backup-restore-dr.md`).

## Rook Operator Upgrade

### OLM Upgrade

If the cluster was installed via OLM (OperatorHub Subscription), upgrade through OLM — do not apply manifests on top of an OLM-managed operator as it will corrupt the CSV state:

```bash
oc -n rook-ceph get subscription
oc -n rook-ceph get csv
```

To trigger an upgrade, update the Subscription channel if needed, then find and approve the pending InstallPlan:

```bash
# Edit the channel if moving to a newer release stream:
oc -n rook-ceph edit subscription <subscription-name>

# Find the pending InstallPlan:
oc -n rook-ceph get installplan

# Approve it:
oc -n rook-ceph patch installplan <installplan-name> \
  --type=merge -p '{"spec":{"approved":true}}'
```

### Helm Upgrade

```bash
helm repo update rook-release
helm upgrade rook-ceph rook-release/rook-ceph \
  --namespace rook-ceph \
  --reuse-values
```

If values have changed between chart versions, export current values first and reconcile:

```bash
helm get values rook-ceph -n rook-ceph > /tmp/rook-current-values.yaml
# review /tmp/rook-current-values.yaml against new chart defaults before upgrading
```

### Manifest Upgrade

Download all manifests for the new version and apply CRDs first, then common (RBAC/ServiceAccounts change between versions), then operator:

```bash
ROOK_VERSION="v<new-version>"
curl -fsSLo /tmp/rook-ceph-crds.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/crds.yaml"
curl -fsSLo /tmp/rook-ceph-common.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/common.yaml"
curl -fsSLo /tmp/rook-ceph-operator.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/operator-openshift.yaml"

oc apply --server-side --force-conflicts -f /tmp/rook-ceph-crds.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-common.yaml
oc apply -f /tmp/rook-ceph-common.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-operator.yaml
oc apply -f /tmp/rook-ceph-operator.yaml
```

Wait for the operator to reconcile and check for errors:

```bash
oc -n rook-ceph rollout status deploy/rook-ceph-operator --timeout=10m
oc -n rook-ceph get pods -o wide
oc -n rook-ceph get cephcluster -o wide
```

## Ceph Image Upgrade

Update the Ceph image in the `CephCluster` CR:

```yaml
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v<new-ceph-version>
```

Apply the change and wait for the operator to upgrade the Ceph daemons:

```bash
oc -n rook-ceph patch cephcluster rook-ceph --type=merge \
  -p '{"spec":{"cephVersion":{"image":"quay.io/ceph/ceph:v<new-ceph-version>"}}}'

oc -n rook-ceph wait cephcluster/rook-ceph --for=condition=Ready --timeout=30m
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
```

## Upgrade Safety Rules

- Do not downgrade Rook or Ceph versions.
- Read the release notes and upgrade guide before applying a new version.
- Verify all PGs are `active+clean` and all OSDs are `up` before starting the upgrade.
- For major Ceph version upgrades, upgrade Rook first to a version that supports the target Ceph version, then upgrade Ceph.
- After a major Ceph version upgrade (e.g., Pacific → Quincy), run `ceph osd require-osd-release <new-release>` to exit compatibility mode and allow the cluster to use new on-disk formats:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd require-osd-release reef
```

  Replace `reef` with the actual target release name. Check `ceph health detail` first — the cluster will warn if this step is pending.
- Document the difference between Rook (operator) version and Ceph (cluster image) version. They can be upgraded independently, but each has documented compatibility.
- If the upgrade fails, do not proceed with additional changes. Diagnose the issue and consider rolling back to the previous version if the operator supports it.

## Upgrade Validation

After upgrade, confirm:

- Operator pod is running and healthy.
- All mons are in quorum.
- All OSDs are `up` and `in`.
- MDS is active (if CephFS is used).
- RGW gateways are running (if object store is used).
- Ceph cluster health is `HEALTH_OK` or `HEALTH_WARN` with known, documented warnings.
- No PGs are stuck in `creating`, `degraded`, or `peering`.
