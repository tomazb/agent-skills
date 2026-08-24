# Platform Ingress And API Certificates

Use this runbook only after HTTP-01 or DNS-01 **staging** proof succeeded, and only with **production** DNS-01 Certificates that are `Ready=True`. Explicit user confirmation is required for the named `oc` context.

`*.apps` **must** use DNS-01. The public API serving cert **must** use DNS-01.

## Discover Current Platform TLS

```bash
python3 scripts/discover_tls.py --context "<oc-context>"
```

Record the ingress domain, API FQDN, existing `IngressController.spec.defaultCertificate`, and `APIServer.spec.servingCerts`. Do not delete `router-certs-default` in `openshift-ingress`.

## Ingress Wildcard Certificate

Create the Certificate in `openshift-ingress`. `secretName` must match the name you will patch onto the IngressController.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: apps-wildcard-tls
  namespace: openshift-ingress
spec:
  secretName: apps-wildcard-tls
  commonName: "*.<apps-domain>"
  dnsNames:
  - "*.<apps-domain>"
  issuerRef:
    name: letsencrypt-production-dns
    kind: ClusterIssuer
    group: cert-manager.io
```

Wait until Ready:

```bash
oc --context "<oc-context>" -n openshift-ingress get certificate apps-wildcard-tls
oc --context "<oc-context>" -n openshift-ingress get secret apps-wildcard-tls
```

Do not patch while the issuer is staging. Staging certificates must not become cluster platform certs.

Patch only after Ready:

```bash
oc --context "<oc-context>" -n openshift-ingress-operator patch ingresscontroller default --type=merge -p '{"spec":{"defaultCertificate":{"name":"apps-wildcard-tls"}}}'
```

Validate console and a sample Route with `openssl s_client` / browser: issuer should be Let's Encrypt, SAN `*.<apps-domain>`.

Rollback (keeps `router-certs-default`):

```bash
oc --context "<oc-context>" -n openshift-ingress-operator patch ingresscontroller default --type=json -p '[{"op":"remove","path":"/spec/defaultCertificate"}]'
```

If `defaultCertificate` was never set, the operator uses `router-certs-default` again.

## API Serving Certificate

Create the Certificate in `openshift-config`:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-serving-tls
  namespace: openshift-config
spec:
  secretName: api-serving-tls
  commonName: "<api-fqdn>"
  dnsNames:
  - "<api-fqdn>"
  issuerRef:
    name: letsencrypt-production-dns
    kind: ClusterIssuer
    group: cert-manager.io
```

Wait for Ready, then patch:

```bash
oc --context "<oc-context>" patch apiserver cluster --type=merge -p '{"spec":{"servingCerts":{"namedCertificates":[{"names":["<api-fqdn>"],"servingCertificate":{"name":"api-serving-tls"}}]}}}'
```

On SNO, warn that a bad API serving-cert mispatch can lock out `oc` until kubeconfig/CA trust is fixed.

Kubeconfigs that embed `certificate-authority-data` for the old `kube-apiserver-lb-signer` will fail after the swap. Remove the CA pin (or replace it with the Let's Encrypt ISRG root the workstation already trusts) and reconnect. Do not leave users on `--insecure-skip-tls-verify` except as a brief recovery step.

Rollback:

```bash
oc --context "<oc-context>" patch apiserver cluster --type=json -p '[{"op":"remove","path":"/spec/servingCerts"}]'
```

## Order Of Operations

1. Production DNS-01 issuer Ready (`references/acme-dns01.md`)
2. Ingress wildcard Certificate Ready, then IngressController patch
3. API Certificate Ready, then APIServer patch (separate confirmation)
4. Validate both names and kubeconfig

## Stop Conditions

- Target `Certificate` not `Ready=True`
- Issuer is staging
- User did not confirm the named context
- `router-certs-default` missing and no documented rollback secret
