# Networking Deep-Dive Diagnostics

Extended commands and signal patterns for Phase 7 of the OpenShift cluster health check.

---

## OVN-Kubernetes deep-dive

### Pod health

```bash
# All OVN pods and node assignment
oc get pods -n openshift-ovn-kubernetes -o wide

# Non-running pods only
oc get pods -n openshift-ovn-kubernetes | grep -v Running

# ovnkube-node must be Running on every node — compare counts
oc get pods -n openshift-ovn-kubernetes -l app=ovnkube-node --no-headers | wc -l
oc get nodes --no-headers | wc -l
```

### OVN database health

```bash
# Northbound and Southbound DB pods on control-plane nodes
oc get pods -n openshift-ovn-kubernetes -l app=ovnkube-control-plane -o wide

# Errors in ovnkube-node logs
oc logs -n openshift-ovn-kubernetes -l app=ovnkube-node \
  --tail=100 --prefix 2>&1 | grep -i "error\|failed\|timeout\|panic"

# Errors in ovnkube-control-plane logs
oc logs -n openshift-ovn-kubernetes -l app=ovnkube-control-plane \
  --tail=100 --prefix 2>&1 | grep -i "error\|failed\|timeout\|panic"
```

### OVN-specific CRD status

```bash
# EgressIP assignments
oc get egressips 2>/dev/null

# Network policies — check for misconfigured deny-all catching control-plane traffic
oc get networkpolicies -A --no-headers | wc -l
```

---

## OpenShiftSDN (legacy) deep-dive

```bash
# All SDN pods and nodes
oc get pods -n openshift-sdn -o wide

# Non-running pods
oc get pods -n openshift-sdn | grep -v Running

# SDN controller logs
oc logs -n openshift-sdn -l app=sdn-controller --tail=100 --prefix 2>&1 \
  | grep -i "error\|failed"
```

---

## Network operator status

```bash
# Full operator condition output
oc get network.operator cluster -o jsonpath='{.status.conditions}' | jq .

# Applied network config
oc get network.config cluster -o jsonpath='{.status}' | jq .
```

---

## Connectivity tests

Run from within a debug pod to avoid false positives from restricted client networks:

```bash
# DNS resolution test
oc debug node/<node> -- chroot /host nslookup \
  kubernetes.default.svc.cluster.local

# API server reachability from a node
oc debug node/<node> -- chroot /host curl -sk \
  https://$(oc get infrastructure cluster \
    -o jsonpath='{.status.apiServerInternalURL}')/healthz
```

---

## Common failure patterns

| Symptom | Likely cause | Check |
|---|---|---|
| `ovnkube-node` not running on a node | Node joined before OVN pods deployed; CNI init failure | `oc describe pod`, node events |
| Pod-to-pod communication broken on one node | OVN node pod crashed or restarting | Restart count + logs |
| All networking broken on a node | Node `NetworkReady=false` condition | `oc describe node` conditions |
| EgressIP not working | OVN-K egressip assignment or node label mismatch | `oc get egressip` |
| NetworkPolicy blocking unexpected traffic | Overly broad `deny-all` policy | `oc get networkpolicy -A` |
| SDN controller not terminating cleanly | Migration in progress or OVN transition | Check operator progressing condition |
