---
name: openshift-cluster-health-check
description: >
  Use this skill when asked to assess OpenShift cluster health, explain degraded status,
  troubleshoot control-plane issues, or produce a health report. Covers all platform types
  including bare metal (IPI/UPI, Metal3, Ironic), virtualized (vSphere, RHV), cloud (AWS,
  Azure, GCP), and SNO. Inspects cluster version, cluster operators, nodes, MCPs,
  control-plane pods, etcd, authentication/OAuth, ingress, DNS, networking (OVN-Kubernetes/
  OpenShiftSDN), storage (CSI, PV/PVC), monitoring/alerting, image registry, console,
  certificates, and platform-specific subsystems. Read-only by default. Use whenever the
  user mentions cluster health, degraded operators, node issues, etcd problems, auth
  failures, ingress errors, certificate expiry, upgrade readiness, post-maintenance
  validation, pending pods, CrashLoopBackOff, pod scheduling failures, quota exhaustion,
  or OOMKilled pods — even if they don't explicitly say "health check."
---

# OpenShift Cluster Health Check

## Purpose

Assess the current health of an OpenShift cluster with a strong bias toward:

- Read-only diagnostics first.
- Platform-aware checks (bare metal, virtual, cloud, SNO).
- Fast identification of control-plane risk.
- Comprehensive subsystem coverage: etcd, auth, ingress, DNS, storage, networking, monitoring, registry, console, certificates.
- Clear separation between symptoms, evidence, likely impact, and next checks.
- Safe escalation from broad health signals to deeper subsystem inspection.

## When to use

Use this skill when the user asks for:

- Cluster health status or health report.
- Root-cause triage for degraded OpenShift behavior.
- Pre-maintenance or post-maintenance validation.
- Upgrade readiness or post-upgrade sanity checks.
- Control-plane, node, MCP, ingress, monitoring, etcd, auth, storage, networking, or certificate health review.
- Bare-metal-specific diagnostics (BMH, Ironic, provisioning).
- Platform-specific diagnostics (vSphere, AWS, Azure, GCP).

Do not use this skill for:

- Application-only debugging inside a single namespace unless it clearly affects cluster health.
- Making changes (drain, cordon, patch, delete, reboot, operator edits) unless the user explicitly asks for remediation.

## Safety rules

- Default to read-only commands.
- Do NOT drain, cordon, delete, patch, edit, restart, or approve CSRs unless explicitly instructed.
- Do NOT assume a warning is critical until supported by evidence.
- Prefer evidence from `oc` over assumptions.
- Call out uncertainty explicitly when access is limited or a subsystem cannot be verified.

## Required inputs

Try to gather before starting:

1. Cluster access confirmation: `oc whoami` and working kubeconfig.
2. Cluster topology: production, lab, SNO, compact (3-node), or full HA.
3. Platform type: bare metal (IPI or UPI), vSphere, AWS, Azure, GCP, or None.
4. Scope: quick summary vs. deep inspection.
5. Context: pre-change, post-change, during incident, upgrade validation.

If any of these are missing, detect what you can from the cluster and state assumptions.

---

## Health model

Classify every finding into one of three levels:

### Healthy
- No control-plane blockers.
- Cluster operators available, not degraded.
- Nodes ready.
- MCPs updated, not degraded.
- No etcd, API, auth, or ingress instability.

### Warning
- Single-node or localized issue with limited blast radius.
- Non-critical operator degradation with working control plane.
- Worker node readiness or pressure issues without broader control-plane impact.
- MCP updating during an expected change window.
- Certificate expiring in 7–30 days.
- Non-critical storage or registry warnings.
- Pending pods due to quota exhaustion in user namespaces (informational, not platform risk).
- Isolated CrashLoopBackOff in user namespaces without node-level correlation.
- A few workloads blocked by insufficient node capacity.

### Critical
- etcd health concerns (member down, DB size, leader elections).
- API, authentication, ingress, kube-apiserver, scheduler, controller-manager, or machine-config failures with cluster-wide impact.
- Control-plane node readiness problems.
- Multiple degraded core operators.
- Cluster version failing or blocked.
- Certificate expired or expiring within 7 days.
- Storage backend unreachable or degraded.
- Authentication completely broken (no logins possible).
- CrashLoopBackOff or Pending pods in `openshift-*` namespaces affecting platform components.
- Cluster-wide scheduling failure due to total node capacity exhaustion.
- Widespread OOMKilled across multiple namespaces or nodes indicating systemic memory pressure.

---

## Workflow

### Phase 0 — Platform detection

Determine the infrastructure platform before running platform-specific checks.

```bash
oc get infrastructure cluster -o jsonpath='{.status.platformStatus.type}'
```

Possible values: `BareMetal`, `VSphere`, `AWS`, `Azure`, `GCP`, `OpenStack`, `None`, `IBMCloud`, `Nutanix`, `PowerVS`.

Also determine topology:

```bash
oc get infrastructure cluster -o jsonpath='{.status.infrastructureTopology}'
# Returns: HighlyAvailable or SingleReplica (SNO)
oc get nodes --no-headers | wc -l
oc get nodes -l node-role.kubernetes.io/master --no-headers | wc -l
oc get nodes -l node-role.kubernetes.io/worker --no-headers | wc -l
```

Record: platform type, topology (HA/SNO/compact-3), control-plane count, worker count. Use this throughout to decide which checks apply.

---

### Phase 1 — Cluster version and operators

```bash
oc get clusterversion
oc get clusterversion -o jsonpath='{.items[0].status.conditions[*]}' | jq .
oc get clusteroperators
oc get clusteroperators -o json | jq '.items[] | select(.status.conditions[] | select(.type=="Degraded" and .status=="True")) | .metadata.name'
oc get clusteroperators -o json | jq '.items[] | select(.status.conditions[] | select(.type=="Available" and .status=="False")) | .metadata.name'
oc get clusteroperators -o json | jq '.items[] | select(.status.conditions[] | select(.type=="Progressing" and .status=="True")) | .metadata.name'
```

For any degraded or unavailable operator:

```bash
oc describe clusteroperator <name>
```

Key things:

- `Available=False` → that capability is down.
- `Degraded=True` → partial failure, may still function.
- `Progressing=True` for extended time → stuck rollout.
- Check the `.status.conditions[].message` for root cause hints.
- Check `.status.versions` to confirm expected version alignment.

---

### Phase 2 — Nodes and capacity

```bash
oc get nodes -o wide
oc adm top nodes
```

For any unhealthy node:

```bash
oc describe node <node>
oc get events --field-selector involvedObject.name=<node> --sort-by=.lastTimestamp
```

Look for:

- `NotReady` or `SchedulingDisabled` when not expected.
- `MemoryPressure`, `DiskPressure`, `PIDPressure`.
- Resource saturation (CPU/memory near 100%).
- Repeated node events (kernel OOM, kubelet restarts).
- Taints blocking scheduling.
- Control-plane nodes are highest priority — a single unhealthy master in a 3-node cluster is dangerous.

For SNO, any node issue is automatically Critical.

---

### Phase 3 — Machine config and rollout health

```bash
oc get machineconfigpools
```

For each pool, check:

- `UPDATED=False` → config not applied yet.
- `UPDATING=True` outside a planned change → unexpected rollout.
- `DEGRADED=True` → rollout failed on one or more nodes.
- `READYMACHINECOUNT` vs `MACHINECOUNT` mismatch.

If a pool is degraded:

```bash
oc describe machineconfigpool <pool-name>
oc get pods -n openshift-machine-config-operator
oc get pods -n openshift-machine-config-operator -l k8s-app=machine-config-daemon -o wide
oc logs -n openshift-machine-config-operator -l k8s-app=machine-config-daemon --tail=100 --prefix
```

Check which node is blocking:

```bash
oc get nodes -o json | jq '.items[] | select(.metadata.annotations["machineconfiguration.openshift.io/state"] != "Done") | {name: .metadata.name, state: .metadata.annotations["machineconfiguration.openshift.io/state"], desired: .metadata.annotations["machineconfiguration.openshift.io/desiredConfig"], current: .metadata.annotations["machineconfiguration.openshift.io/currentConfig"]}'
```

---

### Phase 4 — etcd health

etcd is the most critical subsystem. Check it proactively, not just when symptoms appear.

#### 4a — Operator and pod status

```bash
oc describe clusteroperator etcd
oc get pods -n openshift-etcd -o wide
oc get pods -n openshift-etcd -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{.spec.nodeName}{"\n"}{end}'
```

Verify: all etcd pods are Running, one per control-plane node, no restarts.

#### 4b — etcd member health

Exec into an etcd pod and check member health:

```bash
# Identify a running etcd pod
ETCD_POD=$(oc get pods -n openshift-etcd -l k8s-app=etcd -o jsonpath='{.items[0].metadata.name}')

# Member list
oc rsh -n openshift-etcd $ETCD_POD etcdctl member list -w table

# Endpoint health
oc rsh -n openshift-etcd $ETCD_POD etcdctl endpoint health --cluster -w table

# Endpoint status (shows DB size, leader, raft index)
oc rsh -n openshift-etcd $ETCD_POD etcdctl endpoint status --cluster -w table
```

#### 4c — What to look for

- All members should report `healthy: true`.
- DB size should be under 8 GB (warning above 4 GB, critical above 6 GB).
- Raft term differences between members → leader election churn.
- One member down in a 3-member cluster → cluster still has quorum but zero fault tolerance.
- Two members down → quorum lost, cluster is effectively read-only or down. This is Critical.
- Leader changes in etcd logs indicate instability:

```bash
oc logs -n openshift-etcd $ETCD_POD --tail=200 | grep -i "leader\|election\|compaction\|took too long\|slow\|overloaded"
```

#### 4d — etcd performance signals

```bash
oc logs -n openshift-etcd $ETCD_POD --tail=500 | grep -E "apply request took too long|slow fdatasync|failed to send out heartbeat"
```

These indicate disk I/O latency — common on virtualized environments with shared storage.

#### 4e — etcd on SNO

On SNO there is exactly one etcd member. Any etcd issue is immediately Critical since there is no quorum redundancy. Verify the single pod is healthy and DB size is reasonable.

---

### Phase 5 — Authentication and OAuth

```bash
oc describe clusteroperator authentication
oc get pods -n openshift-authentication -o wide
oc get pods -n openshift-authentication-operator -o wide
```

Check OAuth server health:

```bash
oc get oauthclient
oc get pods -n openshift-authentication -l app=oauth-openshift -o wide
oc logs -n openshift-authentication -l app=oauth-openshift --tail=100
```

Verify identity providers are configured:

```bash
oc get oauth cluster -o jsonpath='{.spec.identityProviders[*].name}'
```

Test token endpoint accessibility (read-only):

```bash
oc get route -n openshift-authentication
```

Signs of trouble:

- `oauth-openshift` pods in CrashLoopBackOff → users cannot log in.
- `authentication` operator degraded → console login broken, `oc login` fails.
- Identity provider misconfiguration → users see login errors.
- Certificate issues on the OAuth route → browser SSL errors at login.

If the `authentication` operator is degraded, also check:

```bash
oc get events -n openshift-authentication --sort-by=.lastTimestamp
oc describe clusteroperator authentication
oc logs -n openshift-authentication-operator deployment/authentication-operator --tail=200
```

---

### Phase 6 — Ingress and DNS

#### 6a — Ingress

```bash
oc describe clusteroperator ingress
oc get ingresscontroller -n openshift-ingress-operator
oc get pods -n openshift-ingress -o wide
```

For each IngressController:

```bash
oc describe ingresscontroller default -n openshift-ingress-operator
```

Check:

- Router pods Running with expected replica count.
- `Available=True` on the IngressController.
- No router pods stuck in `Pending` (scheduling/resource issue).
- Router pods distributed across nodes (anti-affinity).

If on bare metal, ingress often depends on external load balancer or keepalived/MetalLB:

```bash
oc get pods -n openshift-ingress -o wide
# Check if VIPs are reachable (user must confirm externally)
```

#### 6b — DNS

```bash
oc describe clusteroperator dns
oc get pods -n openshift-dns -o wide
oc get pods -n openshift-dns -l dns.operator.openshift.io/daemonset-dns=default
```

Check:

- DNS daemonset pods running on every node (compare count to node count).
- DNS operator not degraded.

Quick DNS validation from within a pod:

```bash
oc debug node/<any-node> -- chroot /host nslookup api-int.$(oc get dns cluster -o jsonpath='{.spec.baseDomain}')
```

---

### Phase 7 — Networking (OVN-Kubernetes / OpenShiftSDN)

Determine network type:

```bash
oc get network.config cluster -o jsonpath='{.status.networkType}'
```

#### OVN-Kubernetes

```bash
oc describe clusteroperator network
oc get pods -n openshift-ovn-kubernetes -o wide
oc get pods -n openshift-ovn-kubernetes | grep -v Running
```

Check:

- `ovnkube-node` pods running on every node.
- `ovnkube-control-plane` pods running on control-plane nodes.
- No CrashLoopBackOff or excessive restarts.
- OVN northbound/southbound DB pods healthy.

```bash
oc logs -n openshift-ovn-kubernetes -l app=ovnkube-node --tail=50 --prefix 2>&1 | grep -i "error\|failed\|timeout"
```

#### OpenShiftSDN (legacy)

```bash
oc get pods -n openshift-sdn -o wide
oc get pods -n openshift-sdn | grep -v Running
```

#### Network diagnostics

```bash
oc get network.operator cluster -o jsonpath='{.status.conditions}' | jq .
```

---

### Phase 8 — Storage

#### 8a — Storage operator and CSI

```bash
oc describe clusteroperator storage
oc get pods -n openshift-cluster-csi-drivers -o wide
oc get csidrivers
oc get storageclasses
```

#### 8b — PV/PVC health

```bash
oc get pv --sort-by=.status.phase | head -30
oc get pv -o json | jq '.items[] | select(.status.phase != "Bound" and .status.phase != "Available") | {name: .metadata.name, phase: .status.phase}'
oc get pvc -A -o json | jq '.items[] | select(.status.phase == "Pending") | {namespace: .metadata.namespace, name: .metadata.name, storageClass: .spec.storageClassName}'
```

Check for:

- PVs in `Failed` or `Released` state.
- PVCs stuck in `Pending` — indicates provisioner issues, quota, or storage backend problems.
- Storage class marked as default exists.

#### 8c — Platform-specific storage

**vSphere:**

```bash
oc get pods -n openshift-cluster-csi-drivers -l app=vsphere-csi-driver-controller
oc logs -n openshift-cluster-csi-drivers -l app=vsphere-csi-driver-controller --tail=100 --prefix
```

**AWS (EBS CSI):**

```bash
oc get pods -n openshift-cluster-csi-drivers -l app=aws-ebs-csi-driver-controller
```

**Bare metal (often uses local-storage or ODF/OCS):**

```bash
oc get pods -n openshift-local-storage 2>/dev/null
oc get pods -n openshift-storage 2>/dev/null
oc get storagecluster -n openshift-storage 2>/dev/null
```

---

### Phase 9 — Monitoring and alerting

```bash
oc describe clusteroperator monitoring
oc get pods -n openshift-monitoring -o wide
oc get pods -n openshift-monitoring | grep -v Running
```

Key components to verify:

- `prometheus-k8s-*` pods running (2 replicas in HA).
- `alertmanager-main-*` pods running.
- `thanos-querier-*` pods running.
- `cluster-monitoring-operator` pod running.

Check for firing alerts:

```bash
oc get prometheusrules -n openshift-monitoring
# To see currently firing alerts (requires port-forward or route):
oc -n openshift-monitoring exec -c prometheus prometheus-k8s-0 -- curl -s 'http://localhost:9090/api/v1/alerts' 2>/dev/null | jq '.data.alerts[] | select(.state=="firing") | {alertname: .labels.alertname, severity: .labels.severity, message: .annotations.message}' 2>/dev/null | head -50
```

If Prometheus/Alertmanager are down, you lose observability — this is Warning at minimum.

---

### Phase 10 — Image registry

```bash
oc describe clusteroperator image-registry
oc get pods -n openshift-image-registry -o wide
oc get configs.imageregistry.operator.openshift.io cluster -o jsonpath='{.spec.storage}' | jq .
oc get configs.imageregistry.operator.openshift.io cluster -o jsonpath='{.spec.managementState}'
```

Check:

- Registry should not be in `Removed` state on production clusters.
- Storage backend configured (S3, PVC, emptyDir is not suitable for production).
- Registry pods running and ready.

On bare metal, the registry often uses PVC-backed storage or is set to `Removed` if not needed:

```bash
oc get pvc -n openshift-image-registry
```

---

### Phase 11 — Console

```bash
oc describe clusteroperator console
oc get pods -n openshift-console -o wide
oc get routes -n openshift-console
```

Console depends on authentication and ingress. If either is degraded, console will likely be affected.

---

### Phase 12 — Certificate health

Check for expiring certificates:

```bash
# Check kube-apiserver serving certs
oc get secret -n openshift-kube-apiserver -o json | jq -r '.items[] | select(.type=="kubernetes.io/tls") | .metadata.name'

# Check router/ingress certs
oc get secret -n openshift-ingress -o json | jq -r '.items[] | select(.type=="kubernetes.io/tls") | .metadata.name'

# Check certificate signing requests
oc get csr
oc get csr -o json | jq '.items[] | select(.status.conditions == null or (.status.conditions | length == 0)) | {name: .metadata.name, requestor: .spec.username, created: .metadata.creationTimestamp}'
```

Check for pending (unapproved) CSRs — common after node restarts or reinstalls:

```bash
oc get csr | grep -i pending
```

Check API server certificate expiry:

```bash
oc -n openshift-kube-apiserver-operator get secret kube-apiserver-to-kubelet-signer -o jsonpath='{.metadata.annotations.auth\.openshift\.io/certificate-not-after}' 2>/dev/null
```

Signs of trouble:

- Unapproved CSRs → nodes cannot join or communicate properly.
- Expired certs → API, auth, or ingress failures.
- Certificate renewal loops in operator logs.

---

### Phase 13 — Platform-specific checks

Based on the platform detected in Phase 0, run the applicable section.

#### 13a — Bare metal (IPI with Metal3/Ironic)

```bash
# BareMetalHost resources
oc get baremetalhosts -n openshift-machine-api
oc get bmh -n openshift-machine-api -o wide

# Check for provisioning failures
oc get bmh -n openshift-machine-api -o json | jq '.items[] | select(.status.provisioning.state != "provisioned" and .status.provisioning.state != "externally provisioned") | {name: .metadata.name, state: .status.provisioning.state, errorMessage: .status.errorMessage}'

# Metal3 and Ironic pods
oc get pods -n openshift-machine-api -l baremetal.openshift.io/cluster-baremetal-operator=metal3
oc get pods -n openshift-machine-api | grep -E "metal3|ironic"

# Provisioning network / config
oc get provisioning cluster -o yaml

# Machine resources
oc get machines -n openshift-machine-api -o wide
oc get machinesets -n openshift-machine-api

# BMO (Bare Metal Operator) logs
oc logs -n openshift-machine-api deployment/metal3 -c metal3-baremetal-operator --tail=100
oc logs -n openshift-machine-api deployment/metal3 -c metal3-ironic-conductor --tail=100
```

Look for:

- BMH stuck in `inspecting`, `preparing`, `registering` → Ironic/IPMI issues.
- BMH in `error` state → check `errorMessage` and `errorType`.
- Ironic pods not running → no provisioning or deprovisioning possible.
- IPMI/BMC connectivity issues in logs.
- Provisioning network misconfiguration.
- Machine objects not matching to nodes.

#### 13b — Bare metal (UPI / platform=None)

UPI bare metal typically has no Machine API integration. Check:

```bash
# Machines may not exist
oc get machines -n openshift-machine-api 2>/dev/null
# Nodes are managed manually
oc get nodes -o wide
# CSRs may need manual approval after node restarts
oc get csr | grep -i pending
```

#### 13c — vSphere

```bash
# vSphere cloud provider and machine API
oc get pods -n openshift-cloud-controller-manager -o wide 2>/dev/null
oc get pods -n openshift-machine-api -o wide

# Machine resources
oc get machines -n openshift-machine-api -o wide
oc get machinesets -n openshift-machine-api

# Machines stuck provisioning
oc get machines -n openshift-machine-api -o json | jq '.items[] | select(.status.phase != "Running") | {name: .metadata.name, phase: .status.phase, errorReason: .status.errorReason, errorMessage: .status.errorMessage}'

# vSphere CSI
oc get pods -n openshift-cluster-csi-drivers -l app=vsphere-csi-driver-controller -o wide
oc logs -n openshift-cluster-csi-drivers -l app=vsphere-csi-driver-controller --tail=100 --prefix 2>&1 | grep -i "error\|failed\|timeout"

# vSphere connection config (does not reveal passwords)
oc get cm -n openshift-config cloud-provider-config -o yaml 2>/dev/null
```

Look for:

- Machine objects stuck in `Provisioning` or `Failed` → vCenter connectivity or resource issues.
- vSphere CSI controller errors → storage provisioning broken.
- Cloud controller manager not running → node addresses, zones, or load balancers not managed.
- vCenter certificate issues in logs.

#### 13d — AWS

```bash
oc get pods -n openshift-cloud-controller-manager -o wide
oc get machines -n openshift-machine-api -o wide
oc get machinesets -n openshift-machine-api

# Machines not running
oc get machines -n openshift-machine-api -o json | jq '.items[] | select(.status.phase != "Running") | {name: .metadata.name, phase: .status.phase}'

# EBS CSI
oc get pods -n openshift-cluster-csi-drivers -l app=aws-ebs-csi-driver-controller

# AWS Load Balancers / ingress
oc get svc -A -o json | jq '.items[] | select(.spec.type=="LoadBalancer") | {namespace: .metadata.namespace, name: .metadata.name, lb: .status.loadBalancer.ingress}'

# Cloud credential operator
oc describe clusteroperator cloud-credential
```

#### 13e — Azure / GCP

Similar to AWS pattern — check cloud controller manager, machine API, CSI drivers, and cloud-credential operator. Adapt namespace and label selectors for the specific platform.

```bash
oc describe clusteroperator cloud-credential
oc get pods -n openshift-cloud-controller-manager -o wide
oc get machines -n openshift-machine-api -o wide
```

---

### Phase 14 — Control-plane namespace sweep

Check the most important namespaces for pod health:

```bash
for ns in openshift-etcd openshift-kube-apiserver openshift-kube-controller-manager openshift-kube-scheduler openshift-apiserver openshift-authentication openshift-ingress openshift-monitoring openshift-machine-api openshift-machine-config-operator openshift-dns openshift-ovn-kubernetes openshift-image-registry openshift-console openshift-oauth-apiserver; do
  echo "=== $ns ==="
  oc get pods -n $ns --no-headers 2>/dev/null | grep -v "Running\|Completed" || echo "  All pods healthy"
done
```

For any namespace showing problems:

```bash
oc get events -n <namespace> --sort-by=.lastTimestamp | tail -20
oc describe pod <pod> -n <namespace>
oc logs <pod> -n <namespace> --tail=100
```

---

### Phase 15 — Pending and crashing pod analysis

Scan cluster-wide for pods that are not running normally, then classify each failure as **quota/limits**, **platform/infrastructure**, or **application-level**.

#### 15a — Identify unhealthy pods

```bash
# All non-running, non-completed pods across the cluster
oc get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null | grep -v Completed

# Specifically Pending pods
oc get pods -A --field-selector=status.phase=Pending -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name)\t\(.status.conditions[]? | select(.type=="PodScheduled") | .reason // "unknown")\t\(.status.conditions[]? | select(.type=="PodScheduled") | .message // "no message")"'

# CrashLoopBackOff and Error pods
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .state.waiting.reason == "CrashLoopBackOff" or .state.waiting.reason == "CreateContainerConfigError" or .state.waiting.reason == "ImagePullBackOff" or .state.waiting.reason == "ErrImagePull" or .state.waiting.reason == "CreateContainerError") | "\(.metadata.namespace)/\(.metadata.name)\t\(.status.containerStatuses[] | select(.state.waiting) | .state.waiting.reason)\t\(.status.containerStatuses[] | select(.state.waiting) | .state.waiting.message // "no message")"'

# High restart-count pods (possible crash loops that recovered temporarily)
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .restartCount > 10) | "\(.metadata.namespace)/\(.metadata.name)\trestarts=\(.status.containerStatuses[] | select(.restartCount > 10) | .restartCount)"'

# OOMKilled containers (recent)
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .lastState.terminated.reason == "OOMKilled") | "\(.metadata.namespace)/\(.metadata.name)\tOOMKilled\texitCode=\(.status.containerStatuses[] | select(.lastState.terminated.reason == "OOMKilled") | .lastState.terminated.exitCode)"'
```

#### 15b — Classify Pending pods: quota vs platform

For each Pending pod, inspect the scheduling failure reason via `oc describe pod`. The reason determines root cause category.

**Quota / resource-limits causes** — these are namespace-scoped or user-config issues, not platform failures:

```bash
# Check ResourceQuota usage across namespaces with Pending pods
PENDING_NS=$(oc get pods -A --field-selector=status.phase=Pending -o jsonpath='{range .items[*]}{.metadata.namespace}{"\n"}{end}' | sort -u)
for ns in $PENDING_NS; do
  echo "=== $ns ==="
  oc get resourcequota -n $ns 2>/dev/null || echo "  No ResourceQuota"
  oc get limitrange -n $ns 2>/dev/null || echo "  No LimitRange"
done
```

Indicators that a Pending pod is quota-blocked:

- Event message contains `exceeded quota` or `forbidden: exceeded quota`.
- Event message contains `must specify limits` or `must specify requests` (LimitRange enforcement).
- Pod requests exceed ResourceQuota `requests.cpu`, `requests.memory`, `limits.cpu`, `limits.memory`, `pods`, or `count/` quotas.
- `oc describe pod` shows `FailedScheduling` with `didn't match pod's node affinity/selector` when the pod is pinned to nodes that don't exist or have taints — this is user config, not platform.

To confirm quota exhaustion:

```bash
oc describe pod <pod> -n <ns> | grep -A5 "Events:"
# Look for: "exceeded quota", "forbidden", "insufficient quota"

oc get resourcequota -n <ns> -o json | jq '.items[] | {name: .metadata.name, status: .status}'
# Compare .status.used vs .status.hard — if used >= hard on any resource, quota is exhausted
```

**Platform / infrastructure causes** — these indicate real cluster-level problems:

```bash
# Describe a Pending pod to get the scheduler reason
oc describe pod <pod> -n <ns> | tail -20
```

Indicators that a Pending pod is platform-blocked:

- `Insufficient cpu` or `Insufficient memory` at the **node level** (not quota) → cluster lacks total schedulable capacity.
- `no nodes available to schedule pods` → all nodes are full, tainted, or cordoned.
- `0/N nodes are available: N node(s) had taint {key=value}, that the pod didn't tolerate` → node taints blocking scheduling, but the cause may be platform-driven (e.g., node NotReady applies `node.kubernetes.io/not-ready` taint automatically).
- `didn't find available persistent volumes to bind` or `unbound immediate PersistentVolumeClaims` → storage provisioner failure or missing PVs. Cross-reference Phase 8 (Storage).
- `FailedAttachVolume` or `FailedMount` → storage backend or CSI driver issue.
- `ErrImagePull` / `ImagePullBackOff` with registry connectivity errors → platform networking or registry issue. But if only one image is affected, it may be user-config (wrong image name/tag).
- `NetworkNotReady` → CNI plugin not initialized on the node.
- `Back-off restarting failed container` (CrashLoopBackOff) in `openshift-*` namespaces → platform-level component failure.

#### 15c — Classify CrashLoopBackOff: platform vs application

Differentiation logic:

| Signal | Classification | Reasoning |
|---|---|---|
| Crash in `openshift-*` namespace | **Platform** | Core operator or control-plane component failing |
| Crash in user namespace with OOMKilled | **Check both** | May be app under-requesting memory OR node under real pressure |
| Crash in user namespace with exit code 1/137 and app-specific logs | **Application** | App bug, misconfiguration, or dependency issue |
| Crash with `CreateContainerConfigError` | **Check both** | Often missing Secret/ConfigMap (user-config), but could be RBAC or platform issue |
| Crash with `ImagePullBackOff` affecting many pods across namespaces | **Platform** | Registry, DNS, or network issue |
| Crash with `ImagePullBackOff` affecting one pod/image | **Application** | Wrong image reference, missing credentials |
| Multiple unrelated pods crashing on the same node | **Platform** | Node instability, disk, or kernel issue — correlate with Phase 2 |
| OOMKilled across many pods on the same node | **Platform** | Node memory exhaustion, possible memory leak in kubelet or system process |

For pods crashing in platform namespaces:

```bash
oc logs <pod> -n <namespace> --previous --tail=100
oc describe pod <pod> -n <namespace>
```

#### 15d — Aggregate view

Build a summary count to understand the scale:

```bash
echo "=== Pending pods by namespace ==="
oc get pods -A --field-selector=status.phase=Pending --no-headers 2>/dev/null | awk '{print $1}' | sort | uniq -c | sort -rn

echo "=== CrashLoopBackOff pods by namespace ==="
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .state.waiting.reason == "CrashLoopBackOff") | .metadata.namespace' | sort | uniq -c | sort -rn

echo "=== ImagePullBackOff pods by namespace ==="
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .state.waiting.reason == "ImagePullBackOff" or .state.waiting.reason == "ErrImagePull") | .metadata.namespace' | sort | uniq -c | sort -rn

echo "=== OOMKilled (recent) by namespace ==="
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .lastState.terminated.reason == "OOMKilled") | .metadata.namespace' | sort | uniq -c | sort -rn

echo "=== Pending pods by node-scheduling reason ==="
oc get events -A --field-selector reason=FailedScheduling -o json | jq -r '.items[].message' | sed 's/^[0-9]* //' | sort | uniq -c | sort -rn | head -10
```

#### 15e — Decision matrix

Use this to set severity:

- **Pending/crashing in `openshift-*` namespaces** → always investigate, usually Warning or Critical depending on which component.
- **Quota-blocked pods in user namespaces only** → typically not a cluster health issue. Report as informational. Recommend the namespace owner adjust quota or pod resource requests.
- **Platform-blocked Pending pods (insufficient node capacity)** → Warning if only a few workloads affected, Critical if cluster is saturated and control-plane pods cannot schedule.
- **Widespread CrashLoopBackOff across multiple namespaces** → investigate common cause (node, storage, network, image registry). Likely platform issue.
- **CrashLoopBackOff isolated to one namespace/app** → application issue. Note it but do not elevate cluster health status.
- **OOMKilled in platform namespaces** → Warning or Critical. Platform components running out of memory can cascade.
- **OOMKilled in user namespaces only** → informational unless it correlates with node memory pressure (Phase 2).

---

### Phase 16 — Cluster-wide events

```bash
oc get events -A --sort-by=.lastTimestamp | tail -50
```

Prioritize:

- Repeated events over one-off noise.
- Events in `openshift-*` namespaces over application namespaces.
- `FailedMount`, `ImagePull`, `BackOff`, `NodeNotReady`, `OOMKilled`, `Evicted`, `FailedScheduling`.
- Certificate or CSR events.
- Network plugin errors.

---

## Reasoning rules

1. Control-plane evidence > app-namespace noise.
2. Operator condition data > pod counts alone.
3. A single worker issue is usually Warning unless it affects storage, ingress, or quorum-sensitive services.
4. A degraded MCP during planned rollout is not automatically Critical.
5. etcd concerns always elevate severity quickly.
6. Authentication broken = Critical (no one can log in or manage the cluster).
7. Ingress broken = Critical for workloads even if control plane is healthy.
8. On SNO, any control-plane issue is automatically Critical — no redundancy.
9. On compact 3-node, a single node down means both control-plane and worker capacity are degraded.
10. When multiple symptoms exist, identify the most upstream failure instead of listing everything independently. Chain: etcd → apiserver → operators → workloads.
11. Platform-specific issues (e.g., Ironic down on bare metal) can block recovery actions like scaling or reprovisioning.
12. Certificate expiry can cascade across multiple subsystems simultaneously.
13. Pending pods due to ResourceQuota or LimitRange exhaustion are namespace-scoped problems, not cluster health issues — report them but do not elevate cluster severity unless they block platform components.
14. Pending pods due to insufficient node capacity, missing PVs, or CNI issues are platform problems — elevate severity based on blast radius.
15. CrashLoopBackOff in `openshift-*` namespaces is always a platform concern. CrashLoopBackOff isolated to a single user namespace is application-level unless correlated with node or storage issues.
16. Widespread OOMKilled across multiple namespaces or nodes suggests systemic memory pressure — treat as platform. Isolated OOMKilled in one app is informational.

---

## Output contract

Always return:

### Overall status

One of: **Healthy**, **Warning**, **Critical**

### Executive summary

2-4 sentences covering:

- What is healthy.
- What is unhealthy.
- Likely blast radius.
- Whether immediate action is needed.

### Platform context

One line: platform type, topology, OCP version, node count breakdown.

### Findings table

| Area | Status | Evidence | Impact | Next check |
|---|---|---|---|---|
| Cluster version | Healthy/Warning/Critical | concrete result | what it affects | next step |
| Cluster operators | ... | ... | ... | ... |
| Nodes | ... | ... | ... | ... |
| MCP | ... | ... | ... | ... |
| etcd | ... | ... | ... | ... |
| Authentication | ... | ... | ... | ... |
| Ingress | ... | ... | ... | ... |
| DNS | ... | ... | ... | ... |
| Networking | ... | ... | ... | ... |
| Storage | ... | ... | ... | ... |
| Monitoring | ... | ... | ... | ... |
| Image registry | ... | ... | ... | ... |
| Console | ... | ... | ... | ... |
| Certificates | ... | ... | ... | ... |
| Pod health (pending/crash) | ... | ... | quota vs platform classification | ... |
| Platform-specific | ... | ... | ... | ... |

Omit rows that are not applicable (e.g., skip bare-metal row for AWS clusters).

### Priority actions

Up to 5 actions, ordered by impact:

1. Highest-value diagnostic or immediate mitigation.
2. Containment step if risk is high.
3. Deeper subsystem follow-up.
4. Medium-term fix.
5. Preventive recommendation.

### Uncertainty

Explicitly note:

- Missing permissions or RBAC limitations.
- Missing namespaces or CRDs (e.g., Metal3 not present).
- Version-specific command differences.
- Checks that could not complete.
- Inferences vs. verified facts.

---

## Response style

- Be concise, technical, and evidence-driven.
- Do not dump raw command output unless the user asks.
- Convert raw signals into risk language: Healthy, Warning, Critical.
- Distinguish verified facts from hypotheses — label inferences.
- Avoid recommending disruptive remediation until diagnosis is clear.
- For bare-metal clusters, always surface BMH and Ironic status since reprovisioning depends on them.
- For virtual/cloud clusters, always surface Machine API health since auto-healing depends on it.

---

## Fast path checklist

Minimum viable health pass (covers 80% of common issues):

```bash
# Platform and topology
oc get infrastructure cluster -o jsonpath='{.status.platformStatus.type}'
oc get nodes -o wide

# Core cluster state
oc get clusterversion
oc get clusteroperators
oc get machineconfigpools

# Control plane
oc get pods -n openshift-etcd
oc get pods -n openshift-kube-apiserver
oc get pods -n openshift-authentication

# Data path
oc get pods -n openshift-ingress
oc get pods -n openshift-dns -l dns.operator.openshift.io/daemonset-dns=default --no-headers | wc -l

# Certificates
oc get csr | grep -ci pending

# Pending and crashing pods (cluster-wide)
oc get pods -A --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l
oc get pods -A -o json | jq '[.items[] | select(.status.containerStatuses[]? | .state.waiting.reason == "CrashLoopBackOff")] | length'

# Events
oc get events -A --sort-by=.lastTimestamp | tail -30
```

---

## Done criteria

This skill is complete when:

- Platform type and topology are identified.
- Overall status is classified (Healthy / Warning / Critical).
- All applicable subsystems are checked and findings are recorded.
- Degraded areas have evidence attached.
- Blast radius is explained.
- Pending and crashing pods are classified as quota, platform, or application issues.
- Platform-specific checks ran (bare metal, virtual, or cloud as appropriate).
- The next 1-5 priority actions are clear.
- Uncertainty is documented.
