# Storage Deep-Dive Diagnostics

Extended commands and signal patterns for Phase 8 of the OpenShift cluster health check.

---

## PV and PVC triage

```bash
# PVs not in Bound or Available state
oc get pv -o json | jq '.items[] |
  select(.status.phase != "Bound" and .status.phase != "Available") |
  {name: .metadata.name, phase: .status.phase, claim: .spec.claimRef.name,
   storageClass: .spec.storageClassName}'

# PVCs stuck in Pending — identify provisioner errors
oc get pvc -A -o json | jq '.items[] |
  select(.status.phase == "Pending") |
  {namespace: .metadata.namespace, name: .metadata.name,
   storageClass: .spec.storageClassName}'

# Events on Pending PVCs for provisioner errors
PENDING_PVC_NS=$(oc get pvc -A --field-selector=status.phase=Pending \
  -o jsonpath='{range .items[*]}{.metadata.namespace}{"\n"}{end}' | sort -u)
for ns in $PENDING_PVC_NS; do
  oc get events -n "$ns" --field-selector reason=ProvisioningFailed \
    --sort-by=.lastTimestamp 2>/dev/null | tail -5
done
```

---

## Storage class audit

```bash
# List all storage classes with default marker
oc get storageclasses -o custom-columns=\
'NAME:.metadata.name,PROVISIONER:.provisioner,DEFAULT:.metadata.annotations.storageclass\.kubernetes\.io/is-default-class'

# More than one default storage class causes PVC binding ambiguity
oc get storageclasses -o json | \
  jq '[.items[] | select(.metadata.annotations["storageclass.kubernetes.io/is-default-class"] == "true") | .metadata.name]'
```

---

## Snapshot readiness

This inventory is read-only. Check every StorageClass, even with no PVCs. Discover APIs before querying them:

```bash
oc get storageclasses -o json
oc get csidrivers
oc api-resources --api-group=snapshot.storage.k8s.io --verbs=list -o name
# Run each following query only when its resource was discovered above.
oc get volumesnapshotclasses -o json
oc get volumesnapshots -A
oc get volumesnapshotcontents
```

Match `StorageClass.provisioner` to `VolumeSnapshotClass.driver`, then check backend parameters such as clusterID/pool and credential references. Class names are not ownership or compatibility proof. A snapshot class for LVMS does not cover Rook RBD/CephFS. Verify installed-version support for each backend, data engine, and volume mode; a CSIDriver object or snapshotter sidecar does not establish capability by itself. Check the distribution snapshot-controller and relevant CSI snapshotter workloads for readiness. Do not install controllers or create classes in a health-check request.

Record **Supported**, **Configured**, **Scheduled**, and **Restore-tested** separately for each StorageClass. Configured requires ready prerequisites, a matching VolumeSnapshotClass, existing referenced credentials, and explicit class selection or an unambiguous intended snapshot default. `snapshot.storage.kubernetes.io/is-default-class` allows at most one default per driver and is independent of StorageClass defaulting. With multiple backends sharing a driver, verify explicit selection. If CDI is present, also verify the StorageProfile's snapshotClass/default selection for VM disks.

Report supported but unconfigured snapshotting as **Warning**, not a runtime storage outage. Verified unsupported combinations are **N/A** with their reason; inaccessible APIs, failed discovery, and unverified support are **Not checked**. An explicit user opt-out is disabled by policy, not configured. Zero existing VolumeSnapshots means no currently retained Kubernetes snapshots were observed, not that the feature is disabled. Absence of schedules must not imply that external backup automation is absent.

Inspect `readyToUse`, snapshot errors, bound VolumeSnapshotContent, driver, restore size, deletionPolicy, and any dated restore/data-comparison evidence. Do not claim recoverability from a ready snapshot or Bound restore PVC alone. Local snapshots do not replace independent off-cluster backups; record schedule, retention, workload/application-consistency coverage, and backup/restore uncertainty separately. Missing configuration routes to `openshift-rook`, `openshift-odf`, `openshift-longhorn`, or `openshift-lvm-storage` after ownership discovery. During authorized setup/remediation those skills configure supported snapshotting by default; this health check only reports the gap.

## vSphere CSI driver

```bash
oc get pods -n openshift-cluster-csi-drivers \
  -l app=vsphere-csi-driver-controller -o wide

oc logs -n openshift-cluster-csi-drivers \
  -l app=vsphere-csi-driver-controller --tail=200 --prefix 2>&1 \
  | grep -i "error\|failed\|timeout\|vcenter"
```

Common vSphere storage issues:
- vCenter certificate expired or changed → CSI controller fails to connect
- Datastore at capacity → PVC provisioning fails with quota error
- VM folder permissions inadequate → `ProvisioningFailed` events

---

## AWS EBS CSI driver

```bash
oc get pods -n openshift-cluster-csi-drivers \
  -l app=aws-ebs-csi-driver-controller -o wide

oc logs -n openshift-cluster-csi-drivers \
  -l app=aws-ebs-csi-driver-controller --tail=100 --prefix 2>&1 \
  | grep -i "error\|failed\|throttl"
```

Common AWS storage issues:
- AWS API rate limiting → `ThrottlingException` in CSI driver logs
- IAM permissions missing for EBS operations → `UnauthorisedOperationException`
- AZ mismatch between PVC and pod node → `FailedAttachVolume`

---

## Bare metal: local-storage and ODF/OCS

```bash
# Local Storage Operator
oc get pods -n openshift-local-storage 2>/dev/null
oc get localvolume -n openshift-local-storage 2>/dev/null

# OpenShift Data Foundation / OCS
oc get pods -n openshift-storage 2>/dev/null | grep -v Running
oc get storagecluster -n openshift-storage 2>/dev/null
oc get cephcluster -n openshift-storage 2>/dev/null
```

```bash
# Ceph health (if ODF is installed)
CEPH_TOOLS=$(oc get pods -n openshift-storage -l app=rook-ceph-tools \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [[ -n "$CEPH_TOOLS" ]]; then
  oc rsh -n openshift-storage "$CEPH_TOOLS" ceph status
  oc rsh -n openshift-storage "$CEPH_TOOLS" ceph health detail
fi
```

ODF health states:
- `HEALTH_OK` — nominal
- `HEALTH_WARN` — one or more OSD slow or near capacity
- `HEALTH_ERR` — data at risk; investigate immediately

---

## VolumeMounts and attachment failures

```bash
# FailedAttachVolume events cluster-wide
oc get events -A --field-selector reason=FailedAttachVolume \
  --sort-by=.lastTimestamp | tail -20

# FailedMount events cluster-wide
oc get events -A --field-selector reason=FailedMount \
  --sort-by=.lastTimestamp | tail -20
```

These events often appear for pods in `ContainerCreating` state. Correlate with PVC status and CSI driver logs.
