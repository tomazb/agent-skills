# Platform-Specific Diagnostics

Extended commands for Phase 13 of the OpenShift cluster health check. Run only the section that matches the platform detected in Phase 0.

---

## 13a — Bare metal IPI (Metal3 / Ironic)

```bash
# BareMetalHost resources
oc get baremetalhosts -n openshift-machine-api
oc get bmh -n openshift-machine-api -o wide

# BMHs not in a terminal state
oc get bmh -n openshift-machine-api -o json | jq '.items[] |
  select(.status.provisioning.state != "provisioned" and
         .status.provisioning.state != "externally provisioned") |
  {name: .metadata.name,
   state: .status.provisioning.state,
   errorMessage: .status.errorMessage}'

# Metal3 and Ironic pods
oc get pods -n openshift-machine-api | grep -E "metal3|ironic"
oc get pods -n openshift-machine-api \
  -l baremetal.openshift.io/cluster-baremetal-operator=metal3 -o wide

# Provisioning configuration
oc get provisioning cluster -o yaml

# BMO and Ironic logs
oc logs -n openshift-machine-api deployment/metal3 \
  -c metal3-baremetal-operator --tail=100
oc logs -n openshift-machine-api deployment/metal3 \
  -c metal3-ironic-conductor --tail=100
```

### BMH state reference

| State | Normal? | Action |
|---|---|---|
| `provisioned` | Yes | No action |
| `externally provisioned` | Yes (UPI) | No action |
| `inspecting` | Transient during enroll | Expected; becomes error if stuck > 15 min |
| `preparing` | Transient | Expected |
| `registering` | Transient | Expected; IPMI/BMC connectivity required |
| `available` | Waiting for Machine claim | Normal for spare hosts |
| `provisioning` | Transient | Expected during node add |
| `deprovisioning` | Transient | Expected during node remove |
| `error` | No | Check `errorMessage` and `errorType`; fix IPMI or image |

### What to look for

- BMH stuck in `inspecting` → Ironic conductor cannot reach BMC; check IPMI credentials and network.
- BMH in `error` with `errorType: registrationError` → BMC address or credentials wrong.
- Ironic conductor not running → no provisioning or deprovisioning possible.
- Provisioning network CIDR mismatch → nodes cannot PXE boot.
- Machine objects without corresponding nodes → CSR approval may be pending (Phase 12).

---

## 13b — Bare metal UPI (platform=None)

```bash
# Machines may not exist on UPI
oc get machines -n openshift-machine-api 2>/dev/null || echo "Machine API not configured (expected on UPI)"

# Nodes are managed manually
oc get nodes -o wide

# Check for pending CSRs — common after node reboots on UPI
oc get csr | grep -i pending

# Pending CSR details
oc get csr -o json | jq '.items[] |
  select(.status.conditions == null or (.status.conditions | length == 0)) |
  {name: .metadata.name, requestor: .spec.username,
   created: .metadata.creationTimestamp}'
```

On UPI clusters, CSR auto-approval is not available. Unapproved CSRs prevent nodes from joining or communicating. Confirm with the cluster owner before approving.

---

## 13c — vSphere

```bash
# Cloud controller manager
oc get pods -n openshift-cloud-controller-manager -o wide 2>/dev/null

# Machine API
oc get machines -n openshift-machine-api -o wide
oc get machinesets -n openshift-machine-api

# Machines not in Running state
oc get machines -n openshift-machine-api -o json | jq '.items[] |
  select(.status.phase != "Running") |
  {name: .metadata.name, phase: .status.phase,
   errorReason: .status.errorReason, errorMessage: .status.errorMessage}'

# vSphere CSI controller
oc get pods -n openshift-cluster-csi-drivers \
  -l app=vsphere-csi-driver-controller -o wide

# vSphere connection config (does not reveal credentials)
oc get cm -n openshift-config cloud-provider-config -o yaml 2>/dev/null
```

### What to look for

- Machines stuck in `Provisioning` → vCenter API unreachable or resource exhaustion.
- Machines in `Failed` with `errorReason: MachineCreationFailed` → vCenter permissions or template issue.
- Cloud controller manager not running → node addresses, zones, and load balancers not synced.
- vSphere CSI errors → PVC provisioning broken for dynamically provisioned volumes.
- vCenter certificate change → CSI and cloud controller lose connectivity.

---

## 13d — AWS

```bash
# Cloud controller manager
oc get pods -n openshift-cloud-controller-manager -o wide

# Machine API
oc get machines -n openshift-machine-api -o wide
oc get machinesets -n openshift-machine-api

# Machines not in Running state
oc get machines -n openshift-machine-api -o json | jq '.items[] |
  select(.status.phase != "Running") |
  {name: .metadata.name, phase: .status.phase,
   errorReason: .status.errorReason}'

# EBS CSI driver
oc get pods -n openshift-cluster-csi-drivers -l app=aws-ebs-csi-driver-controller

# LoadBalancer services — check external IPs assigned
oc get svc -A -o json | jq '.items[] |
  select(.spec.type=="LoadBalancer") |
  {namespace: .metadata.namespace, name: .metadata.name,
   ingress: .status.loadBalancer.ingress}'

# Cloud credential operator
oc describe clusteroperator cloud-credential
```

### What to look for

- Machines stuck in `Provisioning` → EC2 API errors, quota limits, or IAM permission issues.
- LoadBalancer services without ingress entries → ELB provisioning failed; check cloud-credential operator.
- EBS volumes failing to attach → AZ mismatch or IAM policy missing `ec2:AttachVolume`.
- CloudFront / Route53 changes affecting ingress → verify DNS records for routes.

---

## 13e — Azure and GCP

The diagnostic pattern mirrors AWS. Adapt namespace labels as needed.

```bash
# Universal platform checks
oc describe clusteroperator cloud-credential
oc get pods -n openshift-cloud-controller-manager -o wide
oc get machines -n openshift-machine-api -o wide

# Machines not in Running state
oc get machines -n openshift-machine-api -o json | jq '.items[] |
  select(.status.phase != "Running") |
  {name: .metadata.name, phase: .status.phase,
   errorReason: .status.errorReason}'
```

**Azure-specific:**

```bash
# Azure disk CSI
oc get pods -n openshift-cluster-csi-drivers \
  -l app=azure-disk-csi-driver-controller -o wide

# Azure file CSI
oc get pods -n openshift-cluster-csi-drivers \
  -l app=azure-file-csi-driver-controller -o wide
```

**GCP-specific:**

```bash
# GCP PD CSI
oc get pods -n openshift-cluster-csi-drivers \
  -l app=gcp-pd-csi-driver-controller -o wide
```

### What to look for (Azure / GCP)

- Service principal (Azure) or service account key (GCP) expired → cloud-credential operator degraded.
- Managed disk quotas hit → PVC provisioning failures.
- Load balancer provisioning timeout → ingress routes inaccessible externally.
- AZ-specific capacity issues → machines stuck provisioning in one AZ but not others.
