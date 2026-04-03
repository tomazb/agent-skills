# Certificate and CSR Deep-Dive Diagnostics

Extended commands and interpretation patterns for Phase 12 of the OpenShift cluster health check.

---

## Certificate expiry thresholds

Apply consistent severity thresholds to certificate findings.

| Remaining Validity | Severity | Guidance |
|---|---|---|
| `< 7 days` | **Critical** | Treat as urgent incident-level risk; prioritize remediation planning immediately |
| `7-30 days` | **Warning** | Schedule remediation in current maintenance window and monitor daily |
| `> 30 days` | Healthy/Informational | Continue periodic monitoring |

Quick checks:

```bash
# Pending/unapproved CSRs
oc get csr | grep -i pending

# API signer certificate not-after timestamp
oc -n openshift-kube-apiserver-operator get secret kube-apiserver-to-kubelet-signer -o jsonpath='{.metadata.annotations.auth\.openshift\.io/certificate-not-after}' 2>/dev/null
```

---

## CSR approval workflow (diagnostic + controlled remediation)

Default posture is read-only diagnosis first.

### Workflow
1. List pending CSRs and identify requestor/node ownership:
   ```bash
   oc get csr -o json | jq -r '.items[] | select(.status.conditions == null or (.status.conditions | length == 0)) | [.metadata.name, .spec.username, .metadata.creationTimestamp] | @tsv'
   ```
2. Confirm whether CSRs map to expected node lifecycle events (reboot, scale-up, replacement).
3. Validate there is no suspicious/unexpected requestor pattern.
4. If approval is required, obtain explicit operator/user authorization first.
5. After approval, verify node transitions and related operator recovery.

### Safety notes
- Do not bulk-approve unknown CSRs without ownership verification.
- Pending CSRs on control-plane nodes are higher priority than worker-only backlog.
- Repeated CSR churn can signal underlying cert rotation or node identity problems.

---

## Common certificate-related failure cascades

| Initial Cert Problem | Typical Cascade | Verification Focus |
|---|---|---|
| API server signer near expiry/expired | node auth failures, kubelet communication issues, operator degradation | API signer secrets, node readiness, kube-apiserver/operator conditions |
| Ingress/router cert issues | route TLS failures, console/auth access failures | ingress operator status, route endpoint TLS checks |
| OAuth/auth cert issues | `oc login` and console auth failures | authentication operator and oauth-openshift pod/route checks |
| Trust chain mismatch after rotation | inter-component TLS handshake failures | operator logs, cert chain/trust bundle consistency |

---

## Additional checks for renewal instability

```bash
# Certificate-related warnings/errors in key control-plane namespaces
for ns in openshift-kube-apiserver openshift-authentication openshift-ingress openshift-etcd; do
  echo "=== $ns ==="
  oc get events -n "$ns" --sort-by=.lastTimestamp | grep -Ei "cert|tls|x509|csr|expired" | tail -20
done
```

Look for repeated renewal attempts, signer sync failures, or x509 trust errors that indicate an ongoing cascade rather than a one-time warning.
