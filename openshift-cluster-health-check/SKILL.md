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

Classify every finding as **Healthy**, **Warning**, or **Critical**. See [references/severity-calibration.md](references/severity-calibration.md) for full tier definitions, SNO and compact-3 topology overrides, and upstream failure-chaining rules.

### Healthy
All cluster operators available and not degraded, nodes ready, MCPs updated, etcd nominal, API/auth/ingress stable, no expired certificates.

### Warning
Localised or low-blast-radius issues: single worker node problems, non-critical operator degraded, MCP updating in a planned window, certificate expiring in 7–30 days, quota-blocked pods in user namespaces.

### Critical
Any of: etcd quorum at risk, API/auth/ingress cluster-wide failure, control-plane node NotReady, multiple core operators degraded, certificate expired or expiring within 7 days, storage backend unreachable, widespread OOMKilled.

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

### Degraded Discovery Mode

When platform type cannot be determined — `oc get infrastructure cluster` returns `None`, an empty value, or `Forbidden` — enter degraded discovery mode:

1. **Skip platform-specific checks** — Do not run Phase 13 (platform-specific checks). There is no reliable way to select the correct checks without a confirmed platform type.
2. **Run all generic phases normally** — Phases 1–12 and 14–16 do not depend on platform type. Execute them as usual.
3. **Attempt platform inference** — Check node labels (`node.kubernetes.io/instance-type`, `topology.kubernetes.io/zone`, cloud-provider annotations) to infer the likely platform. Label any inference explicitly.
4. **Document in Uncertainty** — Add a dedicated entry in the Uncertainty section explaining what was attempted, what was inferred, and what was skipped. Distinguish inference from verified fact.

Example uncertainty entry for degraded discovery:

> - **Platform type: inferred** — `oc get infrastructure cluster` returned `Forbidden`. Node labels suggest bare-metal topology (no cloud-provider annotations, `kubernetes.io/arch=amd64` only). Platform-specific checks (Phase 13) were skipped. This is an **inference**, not a verified fact.

---

### Phase 1 — Cluster version and operators

```bash
oc get clusterversion
oc get clusteroperators
oc get clusteroperators -o json | jq '.items[] | select(.status.conditions[] | select(.type=="Degraded" and .status=="True")) | .metadata.name'
oc get clusteroperators -o json | jq '.items[] | select(.status.conditions[] | select(.type=="Available" and .status=="False")) | .metadata.name'
oc get clusteroperators -o json | jq '.items[] | select(.status.conditions[] | select(.type=="Progressing" and .status=="True")) | .metadata.name'
```

For any degraded or unavailable operator:

```bash
oc describe clusteroperator <name>
```

- `Available=False` → that capability is down.
- `Degraded=True` → partial failure, may still function.
- `Progressing=True` for extended time → stuck rollout.
- Check `.status.conditions[].message` for root cause hints.

See [references/checklist-cluster-operators.md](references/checklist-cluster-operators.md) for operator condition interpretation, common failure patterns by operator name, and dependency relationship mapping.

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

Look for `NotReady`, `SchedulingDisabled`, `MemoryPressure`, `DiskPressure`, `PIDPressure`, or resource saturation. Control-plane nodes are highest priority. On SNO, any node issue is automatically Critical.

See [references/checklist-nodes.md](references/checklist-nodes.md) for node condition interpretation, allocatable-vs-capacity analysis, and node drain impact assessment guidance.

---

### Phase 3 — Machine config and rollout health

```bash
oc get machineconfigpools
```

- `UPDATED=False` → config not applied. `UPDATING=True` outside a planned change → unexpected rollout. `DEGRADED=True` → rollout failed.

If a pool is degraded:

```bash
oc describe machineconfigpool <pool-name>
oc logs -n openshift-machine-config-operator -l k8s-app=machine-config-daemon --tail=100 --prefix
oc get nodes -o json | jq '.items[] | select(.metadata.annotations["machineconfiguration.openshift.io/state"] != "Done") | {name: .metadata.name, state: .metadata.annotations["machineconfiguration.openshift.io/state"]}'
```

---

### Phase 4 — etcd health

etcd is the most critical subsystem. Check it proactively.

```bash
oc describe clusteroperator etcd
oc get pods -n openshift-etcd -o wide
```

Verify: all etcd pods Running, one per control-plane node, no unexpected restarts. Alert on DB size > 4 GB (Warning) or > 6 GB (Critical), members down, or leader election churn.

See [references/checklist-etcd.md](references/checklist-etcd.md) for etcdctl member/endpoint commands, DB size thresholds, performance signal patterns, and SNO-specific notes.

---

### Phase 5 — Authentication and OAuth

```bash
oc describe clusteroperator authentication
oc get pods -n openshift-authentication -o wide
oc get pods -n openshift-authentication -l app=oauth-openshift -o wide
oc get route -n openshift-authentication
oc get oauth cluster -o jsonpath='{.spec.identityProviders[*].name}'
```

`oauth-openshift` pods in CrashLoopBackOff → users cannot log in (Critical). `authentication` operator degraded → `oc login` and console broken. See [references/checklist-authentication.md](references/checklist-authentication.md) for OAuth deep-dive and identity provider diagnostics.

---

### Phase 6 — Ingress and DNS

```bash
oc describe clusteroperator ingress
oc get ingresscontroller -n openshift-ingress-operator
oc get pods -n openshift-ingress -o wide
oc describe ingresscontroller default -n openshift-ingress-operator
```

Verify router pods Running with expected replica count and distributed across nodes. On bare metal, confirm VIPs are reachable externally.

```bash
oc describe clusteroperator dns
oc get pods -n openshift-dns -l dns.operator.openshift.io/daemonset-dns=default
oc debug node/<any-node> -- chroot /host nslookup api-int.$(oc get dns cluster -o jsonpath='{.spec.baseDomain}')
```

DNS daemonset pods must be Running on every node.

---

### Phase 7 — Networking (OVN-Kubernetes / OpenShiftSDN)

```bash
oc get network.config cluster -o jsonpath='{.status.networkType}'
oc describe clusteroperator network
oc get pods -n openshift-ovn-kubernetes -o wide
oc get pods -n openshift-ovn-kubernetes | grep -v Running
```

`ovnkube-node` must be Running on every node. `ovnkube-control-plane` must be Running on control-plane nodes. See [references/checklist-networking.md](references/checklist-networking.md) for OVN database health, SDN checks, connectivity tests, and common failure patterns.

---

### Phase 8 — Storage

```bash
oc describe clusteroperator storage
oc get storageclasses
oc get pv -o json | jq '.items[] | select(.status.phase != "Bound" and .status.phase != "Available") | {name: .metadata.name, phase: .status.phase}'
oc get pvc -A -o json | jq '.items[] | select(.status.phase == "Pending") | {namespace: .metadata.namespace, name: .metadata.name}'
```

PVs in `Failed`/`Released` or PVCs stuck in `Pending` indicate provisioner or backend problems. See [references/checklist-storage.md](references/checklist-storage.md) for platform-specific CSI driver checks, ODF/Ceph health, and volume attachment triage.

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

```bash
# Pending (unapproved) CSRs — common after node restarts
oc get csr | grep -i pending
oc get csr -o json | jq '.items[] | select(.status.conditions == null or (.status.conditions | length == 0)) | {name: .metadata.name, requestor: .spec.username}'

# API server signer expiry
oc -n openshift-kube-apiserver-operator get secret kube-apiserver-to-kubelet-signer -o jsonpath='{.metadata.annotations.auth\.openshift\.io/certificate-not-after}' 2>/dev/null
```

Unapproved CSRs prevent nodes from joining or communicating. Expired certs cause API, auth, or ingress failures. Certificate renewal loops appear in operator logs.

See [references/checklist-certificates.md](references/checklist-certificates.md) for expiry thresholds, CSR workflow, and common certificate failure cascade diagnostics.

---

### Phase 13 — Platform-specific checks

Run platform-appropriate commands based on the platform detected in Phase 0. Universal checks:

```bash
oc describe clusteroperator cloud-credential
oc get machinesets -n openshift-machine-api
oc get machines -n openshift-machine-api -o wide
oc get machines -n openshift-machine-api -o json | jq '.items[] | select(.status.phase != "Running") | {name: .metadata.name, phase: .status.phase, errorMessage: .status.errorMessage}'
```

See [references/checklist-platform-specific.md](references/checklist-platform-specific.md) for bare-metal IPI/UPI (BMH/Ironic), vSphere CSI, AWS ELB, and Azure/GCP checks.

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

Identify unhealthy pods, then classify each failure as **quota/limits**, **platform/infrastructure**, or **application-level**.

```bash
# All non-running pods
oc get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null | grep -v Completed

# Pending pods with scheduling reason
oc get pods -A --field-selector=status.phase=Pending -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name)\t\(.status.conditions[]? | select(.type=="PodScheduled") | .reason // "unknown")\t\(.status.conditions[]? | select(.type=="PodScheduled") | .message // "no message")"'

# CrashLoopBackOff and ImagePullBackOff pods
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .state.waiting.reason == "CrashLoopBackOff" or .state.waiting.reason == "ImagePullBackOff") | "\(.metadata.namespace)/\(.metadata.name)\t\(.status.containerStatuses[] | select(.state.waiting) | .state.waiting.reason)"'

# OOMKilled (recent)
oc get pods -A -o json | jq -r '.items[] | select(.status.containerStatuses[]? | .lastState.terminated.reason == "OOMKilled") | "\(.metadata.namespace)/\(.metadata.name)\tOOMKilled"'
```

See [references/checklist-pods-analysis.md](references/checklist-pods-analysis.md) for quota vs platform classification logic, CrashLoopBackOff triage table, aggregate view commands, and the severity decision matrix.

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

Always return: overall status (**Healthy** / **Warning** / **Critical**), a 2-4 sentence executive summary, a one-line platform context, the findings table below, up to 5 priority actions, and an uncertainty block.

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

Omit rows not applicable to the detected platform. See [references/output-contract.md](references/output-contract.md) for full section schemas, response style rules, and an example findings row.

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
