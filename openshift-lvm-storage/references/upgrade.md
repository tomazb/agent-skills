# Upgrade

Use this runbook for LVMS operator and TopoLVM CSI upgrades on OpenShift/OKD.

## Pre-Upgrade Health Check

Run these checks before any upgrade step. Do not proceed unless all `LogicalVolume` CRs are healthy and all PVCs are bound:

```bash
oc -n openshift-storage get lvmcluster lvmcluster -o wide
oc -n openshift-storage get logicalvolumes.topolvm.io -o wide
oc get pv,pvc -A -o wide | grep -E 'Bound|Available'
oc -n openshift-storage get pods -o wide
```

Verify cluster health from the node:

```bash
NODE="<node>"
oc debug "node/${NODE}" -- chroot /host bash -c "vgs; lvs; lvs -o data_percent,metadata_percent"
```

Check that thin pool `data_percent` and `metadata_percent` are not near critical thresholds.

Back up the `LVMCluster` CR and any custom StorageClasses before proceeding.

## OLM Upgrade

If the cluster was installed via OLM (OperatorHub Subscription), upgrade through OLM:

```bash
oc -n openshift-storage get subscription
oc -n openshift-storage get csv
```

To trigger an upgrade, update the Subscription channel if needed, then find and approve the pending InstallPlan:

```bash
# Edit the channel if moving to a newer release stream:
oc -n openshift-storage edit subscription lvms-operator

# Find the pending InstallPlan:
oc -n openshift-storage get installplan

# Approve it:
oc -n openshift-storage patch installplan <installplan-name> \
  --type=merge -p '{"spec":{"approved":true}}'
```

Wait for the new CSV to reach `Succeeded`:

```bash
oc -n openshift-storage get csv -w
oc -n openshift-storage get pods -o wide
```

## Helm Upgrade (if applicable)

If the operator was installed via Helm, upgrade the chart:

```bash
helm repo update <repo-name>
helm upgrade lvms-operator <repo-name>/lvms-operator \
  --namespace openshift-storage \
  --reuse-values
```

## LVMCluster CR Compatibility

After the operator upgrade, verify the `LVMCluster` CR is still reconciled and `Ready`:

```bash
oc -n openshift-storage get lvmcluster lvmcluster -o yaml
oc -n openshift-storage wait lvmcluster/lvmcluster --for=condition=Ready --timeout=10m
```

If the operator version introduces CR schema changes, the `LVMCluster` may need updating. Check the release notes for any required CR changes.

## TopoLVM CSI Driver Upgrade

The TopoLVM CSI driver (node and controller) is typically managed by the operator. After an operator upgrade, verify the CSI driver pods are updated. Workload names and labels vary by LVMS version (for example `vg-manager`, `topolvm-node`, `topolvm-controller`), so list all workloads and read the names from the output rather than assuming a label selector:

```bash
oc -n openshift-storage get pods -o wide
oc -n openshift-storage get daemonset,deployment -o wide
```

## Upgrade Safety Rules

- Do not downgrade the LVMS operator.
- Read the release notes and upgrade guide before applying a new version.
- Verify all `LogicalVolume` CRs are healthy and all PVCs are bound before starting the upgrade.
- For major operator upgrades, verify the `LVMCluster` CR schema is compatible before upgrading.
- Document the difference between LVMS operator version and TopoLVM CSI driver version when applicable.
- If the upgrade fails, do not proceed with additional changes. Diagnose the issue and consider rolling back to the previous CSV version if OLM supports it.
- After a major upgrade, verify the StorageClasses and `LVMCluster` thin pool settings are still correct.

## Upgrade Validation

After upgrade, confirm:

- Operator pod is running and healthy.
- `LVMCluster` is `Ready`.
- TopoLVM CSI driver pods are running on all target nodes.
- All PVCs are still `Bound`.
- All `LogicalVolume` CRs are `Healthy`.
- Thin pool usage is within expected bounds.
- `oc get sc` shows the expected StorageClasses.
- Exactly one default StorageClass exists when defaulting is expected.
