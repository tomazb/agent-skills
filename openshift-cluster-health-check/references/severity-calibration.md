# Severity Calibration

Detailed health tier definitions, topology modifiers, and reasoning guidelines for the OpenShift cluster health check.

---

## Health tier definitions

### Healthy

All of the following must be true:

- No control-plane blockers.
- All cluster operators Available=True, Degraded=False.
- All nodes Ready.
- All MCPs Updated=True, Degraded=False, machine counts consistent.
- etcd members all healthy; DB size nominal.
- API server, auth, ingress, DNS all reachable and operational.
- No certificate expired or expiring within 7 days.
- No storage backend degraded.
- No `openshift-*` namespace pods in persistent error states.

A single transient event that resolves within minutes does not prevent a Healthy rating.

---

### Warning

One or more of:

- Single-node or localized issue with limited blast radius.
- Non-critical operator Degraded but cluster still functional (e.g., console degraded while API and auth are fine).
- Worker node with NotReady or Pressure conditions — not a control-plane node.
- MCP updating or degraded within an expected change window.
- Certificate expiring in 7–30 days.
- Non-critical storage or registry warnings.
- etcd DB size 4–6 GB.
- Pending pods blocked by ResourceQuota (namespace-scoped, not platform).
- Isolated CrashLoopBackOff in user namespaces without node or storage correlation.
- Monitoring degraded (loss of observability, not loss of control).
- A few workloads pending due to insufficient node capacity.

---

### Critical

Any one of:

- etcd member down, quorum at risk, DB size > 6 GB, or persistent leader election churn.
- `kube-apiserver`, scheduler, or controller-manager degraded or unavailable.
- Authentication completely broken (users cannot log in or `oc` commands fail).
- Ingress down cluster-wide (workload traffic blocked).
- Multiple core operators degraded simultaneously.
- Cluster version update blocked or failing.
- Certificate expired or expiring within 7 days.
- Storage backend unreachable or degraded (persistent volumes inaccessible).
- Control-plane node NotReady.
- Cluster-wide scheduling failure (all nodes full, tainted, or cordoned — control-plane components cannot schedule).
- Platform components in `openshift-*` namespaces in persistent CrashLoopBackOff.
- Widespread OOMKilled across multiple namespaces or nodes indicating systemic memory pressure.
- Machine API entirely broken on cloud/virtual platforms with no ability to replace nodes.

---

## SNO (Single Node OpenShift) modifiers

On SNO, the blast-radius threshold is zero — there is no redundancy anywhere.

Apply these overrides:

| Condition | Standard cluster | SNO override |
|---|---|---|
| Single node NotReady | Warning | Critical |
| etcd latency or leader election | Warning | Critical |
| Any core `openshift-*` pod crash | Warning+Investigation | Critical |
| Storage backend warning | Warning | Critical (no failover) |
| Disk pressure on the node | Warning | Critical |
| Monitoring degraded | Warning | Critical (no redundant observability) |

---

## Compact 3-node cluster modifiers

Control-plane nodes also serve as workers. A single node failure impacts both control-plane quorum and worker capacity.

| Condition | Standard cluster | Compact 3-node override |
|---|---|---|
| Single control-plane node NotReady | Warning to Critical | Critical (etcd quorum at risk) |
| Single worker node NotReady | Warning | Warning to Critical (worker = control plane) |
| etcd quorum: 2/3 healthy | Warning (quorum holds) | Warning (zero fault tolerance) |
| MCP degraded on one node | Warning | Warning to Critical if node is unschedulable |

---

## Severity modifiers by subsystem

| Subsystem | Severity floor | Rationale |
|---|---|---|
| etcd | Warning minimum for any abnormality | All cluster state depends on etcd |
| kube-apiserver | Critical if unavailable | API is the control plane entry point |
| Authentication | Critical if broken | No one can manage or access the cluster |
| Ingress | Critical if cluster-wide outage | All routed workload traffic lost |
| DNS | Critical if cluster-wide failure | Service discovery broken |
| Machine API | Warning on cloud; lower on UPI | Auto-replacement capability lost |
| Monitoring | Warning | Observability is operational safety |
| Console | Informational to Warning | Operational convenience; does not affect workloads |
| Image registry | Warning | New deployments blocked; existing pods unaffected |
| Certificates | Warning at 7–30 days; Critical at < 7 days | Cascading failures across multiple subsystems |

---

## Upstream failure chaining

When multiple symptoms are present, identify the most upstream failure rather than listing every symptom independently.

Common cascade chains:

1. **Disk → etcd → apiserver → operators → workloads**: Slow disk on a control-plane node causes etcd write latency, which causes apiserver request timeouts, which causes operator reconcile failures, which causes workload degradation.

2. **Network → DNS → service discovery → workloads**: Network plugin instability breaks DNS resolution, breaks service-to-service communication, breaks application health checks.

3. **Certificate expiry → authentication → console → all user access**: An expired serving certificate breaks TLS on the OAuth route, breaking all browser and CLI logins.

4. **Node failure → etcd quorum → control-plane → cluster-wide**: A control-plane node going NotReady reduces etcd to 2-of-3, eliminating fault tolerance and potentially cascading to read-only.

Always trace symptoms upward before listing them as independent findings.
