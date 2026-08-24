# ACME DNS-01

Use this runbook for wildcard `*.apps` certificates and the public API FQDN. Parameterize the DNS provider. Default template is **Cloudflare** (`dns01.cloudflare`) because many public OpenShift zones (including `all-it.tech`) use Cloudflare nameservers. Other providers get a solver swap, not a different Certificate layout.

## Inputs

- ACME email (same as staging proof when possible)
- DNS provider API credential stored as a Kubernetes Secret (never commit tokens)
- Zone that can create `_acme-challenge` TXT records for the API and apps names

Place solver Secrets in the `cert-manager` namespace unless the ClusterIssuer `solvers[].dns01` docs for that provider say otherwise.

## Cloudflare Template (Default)

Create a Cloudflare API token with Zone DNS Edit on the hosted zone. Then:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-api-token-secret
  namespace: cert-manager
type: Opaque
stringData:
  api-token: "<cloudflare-api-token>"
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging-dns
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: "<acme-email>"
    privateKeySecretRef:
      name: letsencrypt-staging-dns-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token-secret
            key: api-token
```

Prove DNS-01 on staging with a non-production hostname or a staging wildcard Certificate that is **not** patched onto IngressController/APIServer.

After staging DNS-01 succeeds, create `letsencrypt-production-dns` pointing at `https://acme-v02.api.letsencrypt.org/directory` with a distinct account key Secret. Platform certs in `references/platform-certs.md` must reference this production DNS issuer.

## Other Providers

Replace only the `solvers[].dns01` block. Keep issuer names and Certificate objects stable.

| Provider | Solver key | Typical Secret |
|----------|------------|----------------|
| Cloudflare | `cloudflare.apiTokenSecretRef` | API token |
| AWS Route53 | `route53` | access key or IRSA/pod identity |
| Azure DNS | `azureDNS` | client secret / workload identity |
| Google Cloud DNS | `cloudDNS` | service account JSON |
| RFC2136 | `rfc2136` | TSIG secret |

Do not invent provider fields. Copy from current cert-manager DNS-01 docs for the installed operand version.

## Recursive Nameservers (Self-Check)

If Challenges hang on DNS self-check (split-horizon or in-cluster DNS that cannot see public TXT yet), set recursive nameservers on the `CertManager` CR. Example:

```yaml
apiVersion: operator.openshift.io/v1alpha1
kind: CertManager
metadata:
  name: cluster
spec:
  controllerConfig:
    overrideArgs:
    - "--dns01-recursive-nameservers=1.1.1.1:53,8.8.8.8:53"
    - "--dns01-recursive-nameservers-only"
```

Confirm the `apiVersion` against the installed Operator CRD before apply.

## Stop Conditions

- No DNS API credential from the user
- Staging DNS-01 Certificate not Ready
- Attempt to use HTTP-01 for a wildcard or API serving cert
