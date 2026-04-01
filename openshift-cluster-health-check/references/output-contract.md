# Output Contract and Response Style

Full output format specification for the OpenShift cluster health check.

---

## Required output sections

### 1. Overall status

One of: **Healthy** | **Warning** | **Critical**

State the overall status on its own line at the top of the response. Include the SNO or compact-3 designation if applicable, as it changes the severity thresholds.

---

### 2. Executive summary

2–4 sentences covering:

- What is healthy and functioning normally.
- What is unhealthy, degraded, or at risk.
- Likely blast radius (who or what is affected).
- Whether immediate action is needed.

Keep this factual and evidence-driven. Avoid hedging language unless uncertainty is genuine and documented.

---

### 3. Platform context

One line:
> **Platform:** `<BareMetal|VSphere|AWS|Azure|GCP|None>` | **Topology:** `<HighlyAvailable|SNO|Compact-3>` | **OCP:** `<version>` | **Nodes:** `<master_count>m / <worker_count>w`

---

### 4. Findings table

Use this table format with one row per subsystem. Omit rows that are not applicable (e.g., skip BareMetalHost row for AWS clusters; skip cloud-credential row for bare metal UPI).

| Area | Status | Evidence | Impact | Next check |
|---|---|---|---|---|
| Cluster version | Healthy/Warning/Critical | `<concrete oc output or observation>` | `<what it affects>` | `<next diagnostic step>` |
| Cluster operators | — | — | — | — |
| Nodes | — | — | — | — |
| MCP | — | — | — | — |
| etcd | — | — | — | — |
| Authentication | — | — | — | — |
| Ingress | — | — | — | — |
| DNS | — | — | — | — |
| Networking | — | — | — | — |
| Storage | — | — | — | — |
| Monitoring | — | — | — | — |
| Image registry | — | — | — | — |
| Console | — | — | — | — |
| Certificates | — | — | — | — |
| Pod health (pending/crash) | — | — | quota vs platform classification | — |
| Platform-specific | — | — | — | — |

**Status column values**: `Healthy` | `Warning` | `Critical` | `Not checked` | `N/A`

---

### 5. Priority actions

Up to 5 actions, ordered by impact. Use this format:

1. **[subsystem]** — `<specific command or action>` — `<why: blast radius or risk>`
2. — — —
3. — — —

Do not exceed 5. Choose the highest-leverage actions. If the cluster is Healthy, these become preventive recommendations.

---

### 6. Uncertainty

Explicitly note:

- Missing permissions or RBAC limitations that prevented a check.
- Missing namespaces or CRDs (e.g., Metal3 not present on non-bare-metal cluster).
- Version-specific command differences (e.g., OCP 4.11 vs 4.16+ changes).
- Checks that could not complete due to connectivity or timeout.
- Inferences vs. verified facts — label anything that is an inference rather than a direct observation.

If there is no uncertainty, omit this section.

---

## Response style guidelines

### Do

- Be concise, technical, and evidence-driven.
- Convert raw signals into risk language: Healthy / Warning / Critical.
- Distinguish verified facts from hypotheses — label inferences explicitly.
- Surface the most upstream failure when multiple symptoms exist.
- For bare-metal clusters: always include BMH and Ironic status since reprovisioning depends on them.
- For virtual/cloud clusters: always include Machine API health since auto-healing depends on it.

### Do not

- Dump raw command output unless the user explicitly asks for it.
- Recommend disruptive remediation (drain, delete, restart, patch) before completing diagnosis.
- List every symptom independently when they share a common upstream cause — chain them.
- Use vague language like "there might be an issue" — either there is evidence or there is not.
- Elevate cluster severity based on quota-blocked user-namespace pods — report those as informational.

---

## Example: findings table row

| Area | Status | Evidence | Impact | Next check |
|---|---|---|---|---|
| etcd | Warning | DB size 5.1 GB (threshold: 4 GB) | Approaching 8 GB quota; etcd becomes read-only at quota | Schedule defrag: `etcdctl defrag --cluster` |
