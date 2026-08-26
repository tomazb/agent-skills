# Maintenance And Uninstall

Uninstall only after reverting platform certificates. Leaving `IngressController` or `APIServer` pointing at Secrets that cert-manager will delete causes TLS outages. On SNO, warn that an API serving-cert mispatch can lock out `oc` until kubeconfig/CA trust is fixed.

## Revert Platform Certs First

Use the conditional rollback in `references/platform-certs.md`. Do **not** unconditionally delete `spec.defaultCertificate` or `spec.servingCerts` — that discards any pre-existing custom ingress cert or other API named certificates.

1. Confirm `router-certs-default` still exists in `openshift-ingress`.
2. Restore `IngressController.spec.defaultCertificate` from the recorded `PRIOR_DEFAULT_CERT` (set the prior secret name, or remove the field only when it was previously unset).
3. Restore `APIServer.spec.servingCerts` from the recorded `PRIOR_SERVING_CERTS` JSON (merge the exact prior object, or remove the field only when it was previously empty).
4. Validate console and `oc` still work with the restored trust chain.
5. Only then delete `Certificate` objects `apps-wildcard-tls` and `api-serving-tls`.

If `PRIOR_*` values were never captured, stop and rediscover current platform TLS before changing anything. Do not delete `router-certs-default`.

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
oc --context "<oc-context>" get apiserver cluster -o json | jq -c '.spec.servingCerts // empty'
```

Stop if platform patches still reference deleted Secret names.
