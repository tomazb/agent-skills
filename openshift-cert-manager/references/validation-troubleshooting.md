# Validation And Troubleshooting

Use this runbook after install, after ACME proof, and after platform cert patches. Prefer helpers before ad-hoc `oc` loops.

```bash
python3 scripts/discover_tls.py --context "<oc-context>"
python3 scripts/check_http01_reachability.py --hostname "<challenge-hostname>"
```

## Healthy Baseline

- CSV `openshift-cert-manager-operator` is `Succeeded` in `cert-manager-operator`
- Operand pods Running in `cert-manager` (controller, webhook, cainjector)
- CRDs `certificates.cert-manager.io` and `clusterissuers.cert-manager.io` exist
- `ClusterIssuer` has ACME account registered (status Ready)
- Target `Certificate` `Ready=True`; Secret has `tls.crt`/`tls.key`
- Platform patches: `IngressController.spec.defaultCertificate.name` and `APIServer.spec.servingCerts.namedCertificates` match those Secrets when that was the intent

## Common HTTP-01 Failures

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| Challenge pending, no HTTP hit | Port 80 filtered on A or AAAA | `check_http01_reachability.py`; Hetzner/cloud firewall |
| Wrong address family | AAAA exists but :80 closed on IPv6 | Dual-stack probe; LE prefers IPv6 |
| 404 on `/.well-known/acme-challenge` | Solver Ingress/Route not admitted | `oc get ingress,route,challenge -A` |
| Redirect loop / TLS error on challenge | Router forces HTTPS | Allow HTTP on solver Route; disable SSL redirect |
| `ingressClassName` ignored | Operand expects `class` | Match installed cert-manager version |

## Common DNS-01 Failures

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| TXT not visible | Token lacks Zone DNS Edit | Cloudflare token scope; Secret namespace |
| Self-check timeout | In-cluster DNS cannot see public TXT | `CertManager` recursive nameservers override |
| Wrong zone | Nested zone (`ocp1.htz2.all-it.tech` vs `all-it.tech`) | Which zone actually serves the FQDN |
| Rate limited | Production ACME retries | Stop; wait; stay on staging until stable |

## CertificateRequest And Order

```bash
oc --context "<oc-context>" get certificaterequest,order,challenge -A
oc --context "<oc-context>" describe challenge -n "<ns>" "<name>"
```

Do not delete production Orders in a retry loop. Fix the solver, then let cert-manager reconcile.

## Platform Cert Drift

If console still shows the ingress-operator CA, the IngressController patch did not apply or the router has not reloaded. If `oc` TLS fails after API patch, fix kubeconfig CA pin before further API writes. On SNO, do not reboot as a TLS fix.

## Renewal

Let's Encrypt certificates renew in-place in the same Secret. Ingress and APIServer consume Secret updates without a second patch when `defaultCertificate` / `namedCertificates` already point at those names. Investigate if `Certificate` Ready flips False near expiry.
