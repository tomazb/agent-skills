# Node and Capacity Deep-Dive Diagnostics

Extended commands and interpretation patterns for Phase 2 of the OpenShift cluster health check.

---

## Node condition interpretation

Inspect both `kubectl`-style condition states and recent events.

```bash
oc get nodes -o wide
oc get nodes -o json | jq -r '.items[] | .metadata.name as $n | .status.conditions[] | select(.type=="Ready" or .type=="MemoryPressure" or .type=="DiskPressure" or .type=="PIDPressure") | [$n, .type, .status, .reason] | @tsv'
oc describe node <node>
oc get events --field-selector involvedObject.kind=Node --sort-by=.lastTimestamp | tail -50
```

| Condition | Healthy Signal | Risk Signal | Typical Impact |
|---|---|---|---|
| `Ready` | `True` | `False` / `Unknown` | Scheduling and existing workload instability |
| `MemoryPressure` | `False` | `True` | Evictions, OOMKills, degraded scheduling |
| `DiskPressure` | `False` | `True` | Image pull failures, pod eviction, node taints |
| `PIDPressure` | `False` | `True` | Process creation failures, kubelet instability |

Control-plane node condition problems carry higher cluster-level severity than isolated worker issues.

---

## Capacity vs allocatable analysis

`Capacity` is raw hardware; `Allocatable` is schedulable budget after reservations and overhead.

```bash
oc get nodes -o json | jq -r '.items[] | [.metadata.name, .status.capacity.cpu, .status.allocatable.cpu, .status.capacity.memory, .status.allocatable.memory] | @tsv'
oc adm top nodes
```

### Checklist
- [ ] Compare current usage from `oc adm top nodes` against allocatable, not capacity
- [ ] Investigate large capacity-to-allocatable deltas (system/kube reservations, daemon overhead)
- [ ] Validate pod requests/limits align with real node allocatable budget
- [ ] Identify nodes nearing sustained saturation before `NotReady` symptoms appear
- [ ] Correlate resource pressure with pod pending/eviction patterns

### Common Signals
- High allocatable utilization + rising pending pods = scheduling bottleneck
- Memory allocatable near exhaustion + OOMKilled pods = memory pressure-driven instability
- Disk pressure + image GC/reclaim events = storage exhaustion risk

---

## Node drain impact assessment

Before draining, estimate blast radius and control-plane safety.

```bash
oc adm node-logs <node> --role=master --path=kubelet.log 2>/dev/null | tail -50
oc get pods -A --field-selector spec.nodeName=<node>
oc get poddisruptionbudgets -A
```

### Drain impact checklist
- [ ] Determine if node hosts control-plane components or critical platform pods
- [ ] Check PodDisruptionBudget constraints for resident workloads
- [ ] Confirm replacement capacity exists on remaining schedulable nodes
- [ ] Evaluate storage attachment implications for stateful pods
- [ ] For compact/SNO topologies, assume much higher disruption risk
- [ ] Record expected user/platform impact before any remediation action

### Risk cues
- Multiple platform daemonsets already degraded + planned drain = high outage risk
- Single remaining healthy control-plane node in compact/SNO = drain may be unsafe
- Stateful workloads with strict zone/node affinity may not reschedule cleanly
