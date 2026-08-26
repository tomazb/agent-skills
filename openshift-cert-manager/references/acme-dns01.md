# ACME DNS-01

Use this runbook for wildcard `*.apps` certificates and the public API FQDN. Parameterize the DNS provider. Prefer a **Red Hat-supported** DNS-01 solver when possible. Certificate layout stays the same; only the `solvers[].dns01` block changes.

## Supported vs community solvers

Red Hat documents and tests these DNS-01 backends with the cert-manager Operator:

- Amazon Route 53 (`route53`)
- Azure DNS (`azureDNS`)
- Google Cloud DNS (`cloudDNS`)
- External DNS webhooks for providers outside that set

**Cloudflare** (`cloudflare`) and **RFC2136** work with upstream cert-manager on many clusters but are **not** Red Hat-supported for the Operator. If the zone is on Cloudflare (or another unsupported provider), keep using that solver only after the user accepts the unsupported path and after a staging DNS-01 proof succeeds on the installed operand.

## Inputs

- ACME email (same as staging proof when possible)
- DNS provider API credential stored as a Kubernetes Secret (never commit tokens)
- Zone that can create `_acme-challenge` TXT records for the API and apps names
- Whether the chosen solver is Red Hat-supported or an accepted unsupported path

Place solver Secrets in the `cert-manager` namespace unless the ClusterIssuer `solvers[].dns01` docs for that provider say otherwise.

## Red Hat-supported template (Route 53 example)

Replace credentials and zone fields for the target account. Azure DNS and Google Cloud DNS follow the same pattern with their solver keys.

```yaml
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
        route53:
          region: "<aws-region>"
          accessKeyIDSecretRef:
            name: route53-credentials
            key: access-key-id
          secretAccessKeySecretRef:
            name: route53-credentials
            key: secret-access-key
```

## Cloudflare template (unsupported by Red Hat)

Use only when the hosted zone is on Cloudflare and the user accepts the unsupported Operator path. Create a Cloudflare API token with Zone DNS Edit on the hosted zone. Then:

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

| Provider | Solver key | Red Hat Operator support | Typical Secret |
|----------|------------|--------------------------|----------------|
| AWS Route53 | `route53` | Supported | access key or IRSA/pod identity |
| Azure DNS | `azureDNS` | Supported | client secret / workload identity |
| Google Cloud DNS | `cloudDNS` | Supported | service account JSON |
| External webhook | provider webhook | Supported path | webhook-specific |
| Cloudflare | `cloudflare.apiTokenSecretRef` | Unsupported | API token |
| RFC2136 | `rfc2136` | Unsupported | TSIG secret |

Do not invent provider fields. Copy from current cert-manager DNS-01 docs for the installed operand version. For unsupported solvers, verify the installed operand includes that solver before production issuance.

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
- Unsupported solver chosen without explicit user acceptance
- Staging DNS-01 Certificate not Ready
- Attempt to use HTTP-01 for a wildcard or API serving cert
