# etcd Deep-Dive Diagnostics

Extended commands and signal patterns for Phase 4 of the OpenShift cluster health check.

---

## etcdctl member and endpoint checks

Exec into a running etcd pod for quorum-level inspection:

```bash
# Identify a running etcd pod
ETCD_POD=$(oc get pods -n openshift-etcd -l k8s-app=etcd -o jsonpath='{.items[0].metadata.name}')

# Member list — all members must appear
oc rsh -n openshift-etcd $ETCD_POD etcdctl member list -w table

# Endpoint health — check for any unhealthy member
oc rsh -n openshift-etcd $ETCD_POD etcdctl endpoint health --cluster -w table

# Endpoint status — DB size, leader ID, raft applied index
oc rsh -n openshift-etcd $ETCD_POD etcdctl endpoint status --cluster -w table
```

---

## What to look for

| Signal | Severity | Action |
|---|---|---|
| All members `healthy: true` | Healthy | No action |
| One member unhealthy, two healthy | Warning | Investigate that member immediately — quorum holds but zero fault tolerance |
| Two members unhealthy | Critical | Quorum lost — cluster read-only or unresponsive |
| DB size 4–6 GB | Warning | Schedule compaction; monitor growth rate |
| DB size > 6 GB | Critical | Immediate compaction required — risk of DB quota hit causing etcd panic |
| Raft term divergence between members | Warning | Indicates recent leader elections or network partitions |
| Raft applied index far behind on one member | Warning | Member catching up; do not restart unless stalled |

### DB size thresholds

etcd defaults to an 8 GB quota. OpenShift sets this to 8 GB. Treat the following as guidance:

- **< 4 GB** — nominal
- **4–6 GB** — warning; plan a defrag and compaction
- **> 6 GB** — high risk; act before etcd hits quota and becomes read-only

To check current DB size without exec:

```bash
oc get etcd cluster -o jsonpath='{.status.conditions}' | jq .
```

---

## Performance signals

Slow disk I/O is the most common cause of etcd instability on virtualised and shared storage environments.

```bash
oc logs -n openshift-etcd $ETCD_POD --tail=500 | \
  grep -E "apply request took too long|slow fdatasync|failed to send out heartbeat|overloaded"
```

| Log pattern | Meaning |
|---|---|
| `apply request took too long` | etcd write path is slow; likely disk latency |
| `slow fdatasync` | Disk fsync taking >100 ms; risk of election timeout |
| `failed to send out heartbeat on time` | Leader cannot heartbeat followers fast enough |
| `overloaded network` | Network saturation or CPU contention on etcd nodes |

Correlate with node disk throughput (Phase 2) and platform storage health (Phase 8).

---

## Leader election history

Frequent leader elections indicate instability:

```bash
oc logs -n openshift-etcd $ETCD_POD --tail=500 | grep -i "leader\|election\|compaction"
```

A single election during a node restart is normal. Multiple elections in a short window are Warning.

---

## etcd operator backups

OpenShift automatically backs up etcd via the etcd-operator. Verify backup status:

```bash
oc get etcd cluster -o jsonpath='{.status.conditions[?(@.type=="BackupAvailable")].status}'
oc get etcd cluster -o jsonpath='{.status.conditions[?(@.type=="BackupAvailable")].message}'
```

---

## SNO-specific notes

On Single Node OpenShift there is exactly one etcd member. Any etcd issue is **Critical** because:

- No quorum redundancy exists.
- A leader election cannot succeed — the single node IS the leader.
- DB size warnings become urgent faster since there is no ability to redistribute load.
- Disk pressure on the single node directly threatens etcd stability.

Check disk usage on the node:

```bash
oc debug node/<sno-node> -- chroot /host df -h /var/lib/etcd
```
