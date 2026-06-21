# Install And Preflight

Use this runbook for discovery, installation planning, OpenShift/OKD prerequisites, and first Longhorn deployment.

## Live Discovery

Collect current state before choosing a path:

```bash
oc version
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc get ns longhorn-system || true
oc -n longhorn-system get pods,settings.longhorn.io,nodes.longhorn.io 2>/dev/null || true
```

For each candidate disk, use a stable path and capture non-destructive evidence:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${DISK}'
  lsblk -f '${DISK}'
  findmnt -S '${DISK}' || true
  wipefs -n '${DISK}' || true
"
```

Never proceed from `/dev/nvmeXnY`, `/dev/sdX`, or a guessed path alone. Resolve and record the `/dev/disk/by-id/*` identity first.

## Host Prerequisites

Longhorn nodes need root/privileged host access and the expected host tools. Verify with `longhornctl` when possible:

```bash
longhornctl --kubeconfig "${KUBECONFIG}" check preflight
```

For OpenShift V2/SPDK preflight, the checker creates a privileged hostPath/hostPID DaemonSet. Grant privileged SCC only for the preflight service account and remove it afterward:

```bash
oc adm policy add-scc-to-user privileged \
  -z longhorn-preflight-checker \
  -n longhorn-system

longhornctl --kubeconfig "${KUBECONFIG}" check preflight --enable-spdk

oc adm policy remove-scc-from-user privileged \
  -z longhorn-preflight-checker \
  -n longhorn-system
```

If preflight fails, report the missing package, service, kernel module, hugepage, or disk condition before writing remediation commands.

## OpenShift Install Path

Prefer Helm when the user can use charts because OpenShift settings are first-class values:

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update longhorn
helm install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --create-namespace \
  --set openshift.enabled=true \
  --set image.openshift.oauthProxy.repository=quay.io/openshift/origin-oauth-proxy \
  --set image.openshift.oauthProxy.tag=<openshift-minor>
```

For manifest installs, pin the Longhorn version and use the OKD manifest:

```bash
LONGHORN_VERSION="v<version>"
curl -fsSLo /tmp/longhorn-okd.yaml \
  "https://raw.githubusercontent.com/longhorn/longhorn/${LONGHORN_VERSION}/deploy/longhorn-okd.yaml"
```

Patch the oauth-proxy image with YAML-aware manifest patching, for example with `yq`:

```bash
OAUTH_PROXY_IMAGE="quay.io/openshift/origin-oauth-proxy:<openshift-minor>"
yq eval '
  (select(.kind == "Deployment" and .metadata.namespace == "longhorn-system")
   | .spec.template.spec.containers[]
   | select(.name == "oauth-proxy")
   | .image) = strenv(OAUTH_PROXY_IMAGE)
' -i /tmp/longhorn-okd.yaml

oc apply --dry-run=server -f /tmp/longhorn-okd.yaml
oc apply -f /tmp/longhorn-okd.yaml
```

If `yq` is unavailable, use another YAML parser or Helm values. Do not use blind `sed` replacement in the final runbook unless the user asks for a temporary emergency workaround and the exact manifest has been inspected.

## MachineConfig Discipline

MachineConfig changes can reboot nodes. On SNO, warn that API access can disappear until the single node returns. Apply one purpose per MachineConfig where possible, wait for MCP recovery, then verify host state:

```bash
oc apply -f <machineconfig.yaml>
oc wait mcp/<pool> --for=condition=Updated=True --timeout=45m
oc get mcp <pool> -o wide
oc get nodes
```

If the MCP degrades, stop mutating and inspect:

```bash
oc describe mcp/<pool>
oc -n openshift-machine-config-operator get pods -o wide
oc -n openshift-machine-config-operator logs <machine-config-daemon-pod> -c machine-config-daemon
```

## Install Validation

Wait for core Longhorn workloads and check OpenShift console/oauth-proxy integration:

```bash
oc -n longhorn-system rollout status ds/longhorn-manager --timeout=10m
oc -n longhorn-system rollout status ds/longhorn-csi-plugin --timeout=10m
oc -n longhorn-system rollout status deploy/longhorn-driver-deployer --timeout=10m
oc -n longhorn-system rollout status deploy/longhorn-ui --timeout=10m
oc -n longhorn-system get pods -o wide
oc get sc
```

Before declaring success, verify exactly one default StorageClass if Longhorn was intended to be default.
