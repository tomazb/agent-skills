# Platform Ingress And API Certificates

Use this runbook only after HTTP-01 or DNS-01 **staging** proof succeeded, and only with **production** DNS-01 Certificates that are `Ready=True`. Explicit user confirmation is required for the named `oc` context.

`*.apps` **must** use DNS-01. The public API serving cert **must** use DNS-01.

## Discover Current Platform TLS

```bash
python3 scripts/discover_tls.py --context "<oc-context>" --execute
```

Record and keep for rollback:

- ingress domain and API FQDN
- current `IngressController.spec.defaultCertificate` (secret name, or unset)
- current `APIServer.spec.servingCerts` (full object, or unset)

Do not delete `router-certs-default` in `openshift-ingress`. Capture the prior values before any patch:

```bash
PRIOR_DEFAULT_CERT="$(oc --context "<oc-context>" -n openshift-ingress-operator get ingresscontroller default -o jsonpath='{.spec.defaultCertificate.name}')"
# jsonpath on an object can print Go map[...] text; capture real JSON for rollback.
PRIOR_SERVING_CERTS="$(oc --context "<oc-context>" get apiserver cluster -o json | jq -c '.spec.servingCerts // empty')"
```

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

### Ingress rollback

Restore the **recorded** prior default certificate. Do not blindly remove the field when a non-default secret was already in use.

If `PRIOR_DEFAULT_CERT` was set (for example `custom-apps-tls`):

```bash
oc --context "<oc-context>" -n openshift-ingress-operator patch ingresscontroller default --type=merge -p "{\"spec\":{\"defaultCertificate\":{\"name\":\"${PRIOR_DEFAULT_CERT}\"}}}"
```

If `PRIOR_DEFAULT_CERT` was empty (operator was using `router-certs-default`):

```bash
oc --context "<oc-context>" -n openshift-ingress-operator patch ingresscontroller default --type=json -p '[{"op":"remove","path":"/spec/defaultCertificate"}]'
```

Removing an unset-or-empty prior returns the operator to `router-certs-default`. Keep `router-certs-default` present either way.

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

Wait for Ready. Before patching, build `namedCertificates` from the **discovered** list so other API aliases keep their entries:

1. Start from the recorded `PRIOR_SERVING_CERTS.namedCertificates` array (or an empty list if unset).
2. Remove any existing entry whose `names` include `<api-fqdn>` (replace in place).
3. Append `{"names":["<api-fqdn>"],"servingCertificate":{"name":"api-serving-tls"}}`.
4. Merge-patch with that full array — never a one-element array that drops other names.

Example when no prior entries exist:

```bash
oc --context "<oc-context>" patch apiserver cluster --type=merge -p '{"spec":{"servingCerts":{"namedCertificates":[{"names":["<api-fqdn>"],"servingCertificate":{"name":"api-serving-tls"}}]}}}'
```

Example when other named certificates already exist, keep them and only replace the API FQDN entry (edit the JSON to match discovery):

```bash
oc --context "<oc-context>" patch apiserver cluster --type=merge -p '{"spec":{"servingCerts":{"namedCertificates":[<prior-entries-without-api-fqdn>,{"names":["<api-fqdn>"],"servingCertificate":{"name":"api-serving-tls"}}]}}}'
```

On SNO, warn that a bad API serving-cert mispatch can lock out `oc` until kubeconfig/CA trust is fixed.

Kubeconfigs that embed `certificate-authority-data` for the old `kube-apiserver-lb-signer` will fail after the swap. Remove the CA pin (or replace it with the Let's Encrypt ISRG root the workstation already trusts) and reconnect. Do not leave users on `--insecure-skip-tls-verify` except as a brief recovery step.

### API rollback

Restore the **exact** recorded `PRIOR_SERVING_CERTS` value.

If `PRIOR_SERVING_CERTS` was set, write it back (prefer `oc patch` / `oc apply` of the captured JSON rather than deleting the whole field):

```bash
# Restore the captured servingCerts object verbatim (example shape).
oc --context "<oc-context>" patch apiserver cluster --type=merge -p "{\"spec\":{\"servingCerts\":${PRIOR_SERVING_CERTS}}}"
```

If `PRIOR_SERVING_CERTS` was empty:

```bash
oc --context "<oc-context>" patch apiserver cluster --type=json -p '[{"op":"remove","path":"/spec/servingCerts"}]'
```

Do not use the empty-path remove when other named certificates existed before the change.

## Order Of Operations

1. Production DNS-01 issuer Ready (`references/acme-dns01.md`)
2. Record prior `defaultCertificate` and `servingCerts`
3. Ingress wildcard Certificate Ready, then IngressController patch
4. API Certificate Ready, then APIServer patch that preserves other named certificates (separate confirmation)
5. Validate both names and kubeconfig

## Stop Conditions

- Target `Certificate` not `Ready=True`
- Issuer is staging
- User did not confirm the named context
- Prior `defaultCertificate` / `servingCerts` not recorded before patch
- `router-certs-default` missing and no documented rollback secret
