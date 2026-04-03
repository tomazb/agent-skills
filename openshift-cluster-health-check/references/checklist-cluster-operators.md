# Cluster Operator Deep-Dive Diagnostics

Extended commands and interpretation patterns for Phase 1 of the OpenShift cluster health check.

---

## Operator condition interpretation

Use condition combinations instead of any single field in isolation.

| Condition Signal | Meaning | Typical Severity Guidance |
|---|---|---|
| `Available=True`, `Degraded=False`, `Progressing=False` | Operator healthy and steady-state | Healthy |
| `Available=True`, `Degraded=True` | Capability still serving, but partially failing | Warning → Critical based on blast radius |
| `Available=False` | Capability unavailable | Usually Critical for core operators |
| `Progressing=True` (short-lived during known update) | Normal rollout in progress | Warning/Informational |
| `Progressing=True` (extended/stuck) | Rollout stalled or blocked dependency | Warning → Critical if control-plane impact |

Helpful command set:

```bash
oc get clusteroperators
oc get clusteroperators -o json | jq -r '.items[] | [.metadata.name, (.status.conditions[] | select(.type=="Available").status), (.status.conditions[] | select(.type=="Degraded").status), (.status.conditions[] | select(.type=="Progressing").status)] | @tsv'
oc describe clusteroperator <name>
```

---

## Common operator failure patterns by operator name

| Operator | Frequent Failure Pattern | Typical Upstream Cause | First Follow-up |
|---|---|---|---|
| `authentication` | OAuth route/login failures, degraded status | Ingress/DNS/cert issues, IdP backend outage | Check `openshift-authentication` pods, routes, certs |
| `ingress` | Router replicas unavailable, route failures | Node pressure, LB/VIP reachability, DNS mismatch | Inspect ingresscontroller + router pod scheduling |
| `network` | CNI pod failures, pod-to-pod connectivity breaks | OVN DB/control-plane issues, node network problems | Check `openshift-ovn-kubernetes` pods and events |
| `etcd` | quorum/member issues, high latency, leader churn | Control-plane node instability, disk latency/space | Inspect etcd pod placement, member health, node conditions |
| `kube-apiserver` | API availability drops, request failures | etcd or certificate dependency issues | Check etcd and cert expiry signals first |
| `machine-config` | pool degraded/stuck updating | Node drain/reboot failures, MCD state mismatch | Check MCP status and MCD logs |
| `monitoring` | Prometheus/Alertmanager unavailable | Resource pressure, storage issues | Verify monitoring pods and PVC/storage health |
| `image-registry` | registry unavailable/degraded | Storage backend misconfig/outage | Validate registry storage config and PVC state |
| `console` | console unavailable/degraded | authentication/ingress dependency failures | Validate authentication and ingress first |

---

## Dependency relationships between operators

Many \"secondary\" degraded operators are downstream symptoms.

### Common dependency chains

- `etcd` → `kube-apiserver` → most control-plane operators (`authentication`, `ingress`, `console`, `monitoring`)
- `network` + `dns` → route/API reachability → `authentication`/`ingress` user-facing failures
- `machine-config`/node health → operator pod scheduling and daemonset convergence
- certificate subsystem health → API/auth/ingress operator availability

### Triage ordering guidance

1. Start with `etcd`, `kube-apiserver`, `network`, and node readiness.
2. Then evaluate dependent operators (`authentication`, `ingress`, `console`, `monitoring`).
3. Avoid treating every degraded operator as independent root cause when one upstream failure explains many.

---

## Fast triage command bundle

```bash
oc get clusterversion
oc get clusteroperators
oc get nodes -o wide
oc describe clusteroperator etcd
oc describe clusteroperator kube-apiserver
oc describe clusteroperator network
```
