# ACME HTTP-01 Proof

Use this runbook to prove Let's Encrypt issuance with HTTP-01 **before** any platform `*.apps` or API certificate work. Staging first. Production HTTP-01 is only for non-wildcard app Routes or Ingresses.

HTTP-01 cannot issue `*.apps` wildcards. HTTP-01 cannot issue the public API cert on `:6443`.

## Port 80 Preflight

Let's Encrypt validators connect to TCP **80** on every public address for the hostname. Dual-stack names must pass on **A and AAAA**. Fail closed if either family times out.

```bash
python3 scripts/check_http01_reachability.py --hostname "<proof-hostname>"
```

Example proof hostname: `acme-proof.<apps-domain>`.

If port 80 is filtered (common on Hetzner SNO when only 443/6443 are open), stop. Opening :80 is a user firewall change, not something this skill applies. Re-run the helper after :80 is reachable.

OpenShift default routers often redirect HTTP to HTTPS. The solver Ingress must allow HTTP. Prefer annotations that disable SSL redirect / allow insecure edge termination on the challenge Route.

## Staging ClusterIssuer (HTTP-01)

Collect ACME email from the user. Do not invent an address.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: "<acme-email>"
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: openshift-default
```

On older cert-manager operands, `class: openshift-default` may still appear instead of `ingressClassName`. Match the installed operand.

## Proof Certificate

Create a disposable namespace, HTTP app, Route or Ingress hostname, and `Certificate` that references `letsencrypt-staging`. Wait for `Certificate` `Ready=True`. Inspect `Order`, `Challenge`, and solver pods if it stalls.

```bash
oc --context "<oc-context>" get clusterissuer letsencrypt-staging
oc --context "<oc-context>" get certificate,certificaterequest,order,challenge -A
```

Staging certificates are untrusted by browsers. Success means ACME HTTP-01 works, not that clients will trust the cert.

## Production HTTP-01 Issuer (App Routes Only)

Only after staging proof succeeds, create `letsencrypt-production` with `https://acme-v02.api.letsencrypt.org/directory` and a distinct account key Secret. Use it for **single-hostname** app certificates. Do not use it for `*.apps` or `api.<cluster>`.

Never retry production ACME in a tight loop. Let's Encrypt rate limits failed authorizations.

## Stop Conditions

- `python3 scripts/check_http01_reachability.py` reports closed :80 on any A or AAAA
- Staging `Certificate` not Ready
- User asked to skip HTTP-01 and go DNS-01 only (then leave this runbook and use `references/acme-dns01.md`)
