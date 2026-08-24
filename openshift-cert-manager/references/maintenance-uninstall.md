# Maintenance And Uninstall

Uninstall only after reverting platform certificates. Leaving `IngressController` or `APIServer` pointing at Secrets that cert-manager will delete causes TLS outages. On SNO, warn that an API serving-cert mispatch can lock out `oc` until kubeconfig/CA trust is fixed.

## Revert Platform Certs First

1. Confirm `router-certs-default` still exists in `openshift-ingress`.
2. Remove `spec.defaultCertificate` from IngressController `default` (see `references/platform-certs.md` rollback).
3. Remove `spec.servingCerts` from `APIServer` `cluster`.
4. Validate console and `oc` still work with original cluster CAs.
5. Only then delete `Certificate` objects `apps-wildcard-tls` and `api-serving-tls`.

Do not delete `router-certs-default`.

## Uninstall Operator

After platform revert:

```bash
oc --context "<oc-context>" -n cert-manager-operator delete subscription openshift-cert-manager-operator --ignore-not-found
oc --context "<oc-context>" -n cert-manager-operator delete csv --all --ignore-not-found
oc --context "<oc-context>" delete clusterissuer letsencrypt-staging letsencrypt-production letsencrypt-staging-dns letsencrypt-production-dns --ignore-not-found
oc --context "<oc-context>" delete ns cert-manager cert-manager-operator --wait=false
```

CRDs (`certificates.cert-manager.io`, `issuers.cert-manager.io`, `clusterissuers.cert-manager.io`, `challenges.acme.cert-manager.io`, `orders.acme.cert-manager.io`) may remain. Delete CRDs only with explicit confirmation: that removes all remaining Certificates cluster-wide.

Do not delete OpenShift Virtualization `kubemacpool-cert-manager` resources.

## Leftover Audit

```bash
oc --context "<oc-context>" get crd | grep cert-manager || true
oc --context "<oc-context>" get clusterissuer,certificate -A 2>/dev/null || true
oc --context "<oc-context>" get ingresscontroller default -n openshift-ingress-operator -o jsonpath='{.spec.defaultCertificate}{"\n"}'
oc --context "<oc-context>" get apiserver cluster -o jsonpath='{.spec.servingCerts}{"\n"}'
```

Stop if platform patches still reference deleted Secret names.
