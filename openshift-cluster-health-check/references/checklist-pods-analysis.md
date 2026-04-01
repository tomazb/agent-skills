# Pending and Crashing Pod Analysis

Extended classification logic for Phase 15 of the OpenShift cluster health check.

---

## 15b — Classify Pending pods: quota vs platform

### Step 1 — Get the scheduler failure reason

```bash
oc describe pod <pod> -n <ns> | grep -A 10 "Events:"
```

### Step 2 — Check ResourceQuota usage in the namespace

```bash
PENDING_NS=$(oc get pods -A --field-selector=status.phase=Pending \
  -o jsonpath='{range .items[*]}{.metadata.namespace}{"\n"}{end}' | sort -u)
for ns in $PENDING_NS; do
  echo "=== $ns ==="
  oc get resourcequota -n "$ns" 2>/dev/null || echo "  No ResourceQuota"
  oc get limitrange -n "$ns" 2>/dev/null || echo "  No LimitRange"
done
```

### Step 3 — Confirm quota exhaustion

```bash
oc describe pod <pod> -n <ns> | grep -A 5 "Events:"
# Look for: "exceeded quota", "forbidden", "insufficient quota"

oc get resourcequota -n <ns> -o json | \
  jq '.items[] | {name: .metadata.name, status: .status}'
# Compare .status.used vs .status.hard on every resource type
```

### Quota / resource-limits indicators (namespace-scoped, not cluster health)

- Event contains `exceeded quota` or `forbidden: exceeded quota`.
- Event contains `must specify limits` or `must specify requests` (LimitRange enforcement).
- Pod requests exceed `requests.cpu`, `requests.memory`, `limits.cpu`, `limits.memory`, `pods`, or `count/` quotas.
- `FailedScheduling` with `didn't match pod's node affinity/selector` when the constraint is in the pod spec — user configuration, not platform.

### Platform / infrastructure indicators (cluster health issue)

- `Insufficient cpu` or `Insufficient memory` **at the node level** → cluster lacks schedulable capacity.
- `no nodes available to schedule pods` → all nodes full, tainted, or cordoned.
- `0/N nodes are available: N node(s) had taint {node-role/not-ready}` → node readiness issue driving taint.
- `didn't find available persistent volumes to bind` → storage provisioner failure or missing PVs.
- `FailedAttachVolume` or `FailedMount` → CSI driver or storage backend issue.
- `NetworkNotReady` → CNI plugin not initialized on the target node.
- `ErrImagePull` / `ImagePullBackOff` with registry errors **across many pods** → platform network or registry issue.

---

## 15c — Classify CrashLoopBackOff: platform vs application

| Signal | Classification | Reasoning |
|---|---|---|
| Crash in `openshift-*` namespace | **Platform** | Core operator or control-plane component failing |
| Crash in user namespace, OOMKilled | **Check both** | May be app under-requesting memory OR node under real pressure |
| Crash in user namespace, exit code 1/137, app-specific logs | **Application** | App bug, misconfiguration, or dependency issue |
| `CreateContainerConfigError` | **Check both** | Often missing Secret/ConfigMap (user-config) but can be RBAC or platform issue |
| `ImagePullBackOff` affecting many pods across namespaces | **Platform** | Registry, DNS, or network issue |
| `ImagePullBackOff` affecting one pod or image | **Application** | Wrong image reference or missing pull secret |
| Multiple unrelated pods crashing on the same node | **Platform** | Node instability; disk, kernel, or kubelet issue — correlate with Phase 2 |
| OOMKilled across many pods on the same node | **Platform** | Node memory exhaustion; possible system-level memory leak |

```bash
# Logs from a crashing platform-namespace pod
oc logs <pod> -n <namespace> --previous --tail=100
oc describe pod <pod> -n <namespace>
```

---

## 15d — Aggregate view

Build a cross-namespace summary to understand scale:

```bash
echo "=== Pending pods by namespace ==="
oc get pods -A --field-selector=status.phase=Pending --no-headers 2>/dev/null \
  | awk '{print $1}' | sort | uniq -c | sort -rn

echo "=== CrashLoopBackOff pods by namespace ==="
oc get pods -A -o json | jq -r \
  '.items[] | select(.status.containerStatuses[]? |
    .state.waiting.reason == "CrashLoopBackOff") | .metadata.namespace' \
  | sort | uniq -c | sort -rn

echo "=== ImagePullBackOff pods by namespace ==="
oc get pods -A -o json | jq -r \
  '.items[] | select(.status.containerStatuses[]? |
    .state.waiting.reason == "ImagePullBackOff" or
    .state.waiting.reason == "ErrImagePull") | .metadata.namespace' \
  | sort | uniq -c | sort -rn

echo "=== OOMKilled (recent) by namespace ==="
oc get pods -A -o json | jq -r \
  '.items[] | select(.status.containerStatuses[]? |
    .lastState.terminated.reason == "OOMKilled") | .metadata.namespace' \
  | sort | uniq -c | sort -rn

echo "=== FailedScheduling reasons ==="
oc get events -A --field-selector reason=FailedScheduling -o json | \
  jq -r '.items[].message' | sed 's/^[0-9]* //' | sort | uniq -c | sort -rn | head -10
```

---

## 15e — Severity decision matrix

| Situation | Severity | Reasoning |
|---|---|---|
| Pending / crashing in `openshift-*` namespaces | Warning to Critical | Core platform component affected; investigate immediately |
| Quota-blocked pods in user namespaces only | Informational | Namespace-scoped; not a cluster health issue |
| Platform-blocked Pending (insufficient node capacity) | Warning to Critical | Warning if a few workloads; Critical if control-plane pods cannot schedule |
| Widespread CrashLoopBackOff across multiple namespaces | Warning to Critical | Investigate root cause: node, storage, network, or registry |
| CrashLoopBackOff isolated to one namespace or app | Informational | Application issue; note it but do not elevate cluster severity |
| OOMKilled in platform namespaces | Warning to Critical | Platform components out of memory can cascade |
| OOMKilled in user namespaces only | Informational | Track volume; escalate if correlated with node memory pressure (Phase 2) |
| `ImagePullBackOff` affecting one image | Informational | Application configuration issue |
| `ImagePullBackOff` across many pods/namespaces | Warning to Critical | Likely registry, DNS, or network failure |
