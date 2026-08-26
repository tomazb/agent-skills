# Install And Preflight

Use this runbook for discovery, OperatorHub checks, and first install of the **Red Hat** cert-manager Operator (`openshift-cert-manager-operator`). Do not install the community `cert-manager` package on the same cluster.

## Live Discovery

Collect current state before choosing a path. Prefer the helper so FQDNs, cert issuers, and port probes are not guessed:

```bash
python3 scripts/discover_tls.py --context "<oc-context>" --execute
```

Equivalent manual commands:

```bash
oc --context "<oc-context>" whoami
oc --context "<oc-context>" get clusterversion
oc --context "<oc-context>" get nodes -o wide
oc --context "<oc-context>" get infrastructure cluster -o jsonpath='{.status.apiServerURL}{"\n"}'
oc --context "<oc-context>" get ingress.config cluster -o jsonpath='{.spec.domain}{"\n"}'
oc --context "<oc-context>" get ingresscontroller default -n openshift-ingress-operator -o yaml
oc --context "<oc-context>" get apiserver cluster -o yaml
oc --context "<oc-context>" get packagemanifests -n openshift-marketplace | grep -i cert-manager
oc --context "<oc-context>" api-resources --api-group=cert-manager.io
oc --context "<oc-context>" get crd | grep cert-manager || true
oc --context "<oc-context>" get ns cert-manager-operator cert-manager 2>/dev/null || true
oc --context "<oc-context>" -n cert-manager-operator get operatorgroup,subscription,csv 2>/dev/null || true
oc --context "<oc-context>" -n cert-manager get pods 2>/dev/null || true
```

Ignore OpenShift Virtualization `kubemacpool-cert-manager` pods. They are not `cert-manager.io`.

Record:

- API FQDN and ingress apps domain
- Whether `IngressController` uses `HostNetwork` (typical SNO) or a load balancer
- OperatorHub channels for `openshift-cert-manager-operator` (often `stable-v1`)
- Existing `ClusterIssuer` / `Certificate` objects if this is a reinstall

## OLM Install (Red Hat Operator)

Install via OLM from `redhat-operators`. Create resources in order: namespace, `OperatorGroup`, then `Subscription`. A `Subscription` with no `OperatorGroup` never produces a CSV.

Default Operator namespace is `cert-manager-operator`. The operand typically lands in `cert-manager`.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cert-manager-operator
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-cert-manager-operator
  namespace: cert-manager-operator
spec:
  targetNamespaces:
  - cert-manager-operator
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: openshift-cert-manager-operator
  namespace: cert-manager-operator
spec:
  channel: stable-v1
  name: openshift-cert-manager-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

Wait for the CSV and operand:

```bash
oc --context "<oc-context>" -n cert-manager-operator get subscription,csv,pods
oc --context "<oc-context>" -n cert-manager get pods
oc --context "<oc-context>" get crd certificates.cert-manager.io clusterissuers.cert-manager.io
```

Success looks like CSV `Succeeded` and Running pods for controller, webhook, and cainjector in `cert-manager`.

Do not install the Operator in multiple namespaces. Do not also subscribe to community `cert-manager`.

## Optional CertManager CR

The Operator may create `CertManager` named `cluster`. Use it later for DNS-01 recursive nameserver overrides (`references/acme-dns01.md`). Do not set `spec.unsupportedConfigOverrides` unless the user explicitly accepts an unsupported path.

## Stop Conditions

- Marketplace catalog missing `openshift-cert-manager-operator`
- Existing community cert-manager CRDs/CSV already managing `cert-manager.io`
- User has not confirmed mutating install on this context
