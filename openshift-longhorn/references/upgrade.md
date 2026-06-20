# Upgrade

Use this runbook for Longhorn version discovery, upgrade planning, manager upgrades, engine upgrades, and post-upgrade validation.

## Version Discovery

Discover installed version first:

```bash
oc -n longhorn-system get ds longhorn-manager \
  -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
oc -n longhorn-system get deploy longhorn-driver-deployer \
  -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
oc -n longhorn-system get engineimages.longhorn.io -o wide
```

When network access is available, cross-check target versions:

```bash
curl -fsSL https://api.github.com/repos/longhorn/longhorn/releases/latest | jq -r '.tag_name'
helm repo add longhorn https://charts.longhorn.io 2>/dev/null || true
helm repo update longhorn
helm search repo longhorn/longhorn --versions | head
```

Read the pinned target upgrade page and release notes before commands.

## Upgrade Rules

- Do not downgrade Longhorn.
- Do not skip unsupported minor versions. Upgrade one minor at a time, or patch within the same minor.
- Prefer the latest patch in the current minor before moving to a newer minor.
- For V2 Data Engine, verify all V2 Data Engine volumes are detached and replicas are stopped before upgrading; V2 does not support live upgrades in the documented v1.12.0 path.
- Create or verify a recent Longhorn system backup before upgrading.
- For SNO, declare a maintenance window. A single-replica SNO has no node-level redundancy during reboots or Longhorn disruption.

## Prechecks

```bash
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc -n longhorn-system get pods -o wide
oc -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io -o wide
oc -n longhorn-system get backups.longhorn.io,systembackups.longhorn.io 2>/dev/null || true
```

Check for:

- faulted or degraded volumes;
- failed BackingImages;
- active V2 volumes;
- missing backup target;
- unexpected default StorageClass;
- degraded MCP or non-ready nodes;
- Longhorn settings drift from the desired SNO or multi-node policy.

## Manager Upgrade

For Helm installs, use the chart version that matches the target app version. Preserve OpenShift values:

```bash
helm upgrade longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --version <chart-version> \
  --set openshift.enabled=true \
  --set image.openshift.oauthProxy.repository=quay.io/openshift/origin-oauth-proxy \
  --set image.openshift.oauthProxy.tag=<openshift-minor>
```

For manifest installs on OpenShift/OKD, fetch pinned `deploy/longhorn-okd.yaml`, patch oauth-proxy with YAML-aware manifest patching, run server dry-run, then apply.

## Engine Upgrade

After manager health is confirmed, upgrade engine images deliberately. Do not assume automatic engine upgrade is acceptable for production workloads. Record:

- current engine image;
- target engine image;
- volume attachment state;
- maintenance window;
- rollback constraints.

## Post-Upgrade Validation

Verify:

- Longhorn manager, CSI plugin, driver deployer, UI, instance managers, and engine image pods are healthy.
- `default-replica-count`, `create-default-disk-labeled-nodes`, `default-data-path`, V1/V2 data-engine settings, and data-engine memory/hugepage settings match the intended policy.
- `longhorn-storageclass` ConfigMap matches the live StorageClass.
- Exactly one default StorageClass exists.
- V2 volumes were reattached intentionally only after upgrade.
- Canary PVC succeeds before production workloads resume.
