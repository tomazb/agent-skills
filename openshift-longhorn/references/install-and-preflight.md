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

Also discover leftovers from a previous lifecycle before reinstalling:

```bash
oc api-resources --api-group=longhorn.io
oc get validatingwebhookconfiguration longhorn-webhook-validator 2>/dev/null || true
oc get mutatingwebhookconfiguration longhorn-webhook-mutator 2>/dev/null || true
oc get csidriver driver.longhorn.io 2>/dev/null || true
oc get storageclass -o wide
oc get machineconfig | grep -i longhorn || true
oc get pv,pvc -A -o wide
```

If `oc config current-context` points at a deleted namespace, use `-n default`
for `oc debug` and other namespace-scoped helper pods.

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

If `longhornctl` is missing, download the CLI release matching the target or
installed Longhorn version from `https://github.com/longhorn/cli/releases`,
download the matching `.sha256` file, verify the checksum, and run that pinned
binary. Do not mix a newer or older `longhornctl` with a different Longhorn
minor unless the official docs explicitly allow it.

Use the plain preflight command for V1 Data Engine and general host checks. Do
not add `--enable-spdk` for a V1-only validation because that flag checks
V2/SPDK prerequisites such as hugepages, SPDK modules, and raw block readiness.

For OpenShift, the preflight checker may need privileged host access. If the
checker pod is blocked by SCC, grant privileged SCC only for the preflight
service account, rerun the preflight, and remove the grant afterward:

```bash
oc adm policy add-scc-to-user privileged \
  -z longhorn-preflight-checker \
  -n longhorn-system

longhornctl --kubeconfig "${KUBECONFIG}" check preflight

oc adm policy remove-scc-from-user privileged \
  -z longhorn-preflight-checker \
  -n longhorn-system
```

For V2/SPDK preflight, use the same temporary SCC pattern and include
`--enable-spdk`:

```bash
oc adm policy add-scc-to-user privileged \
  -z longhorn-preflight-checker \
  -n longhorn-system

longhornctl --kubeconfig "${KUBECONFIG}" check preflight --enable-spdk

oc adm policy remove-scc-from-user privileged \
  -z longhorn-preflight-checker \
  -n longhorn-system
```

Interpret preflight findings before writing remediation commands:

- Report missing package, service, kernel module, hugepage, or disk conditions
  with the exact check name and node.
- On RHCOS/OpenShift, missing `/host/proc/config.gz` or
  `/host/boot/config-*` can cause kernel-config checks such as NFS or
  `dm_crypt` to report errors even when package checks pass. Verify whether the
  flagged feature is required before remediating.
- OpenShift DNS can trigger a `KubeDNS` deployment-label warning because
  OpenShift does not expose DNS exactly like upstream kube-dns. Verify cluster
  DNS health separately before treating that warning as a Longhorn blocker.

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

The packaged helper can patch the OKD manifest for either data engine while
keeping the Longhorn StorageClass non-default by default:

```bash
python3 scripts/patch_longhorn_okd_manifest.py \
  --input /tmp/longhorn-okd.yaml \
  --output /tmp/longhorn-okd-v2.yaml \
  --mode v2 \
  --oauth-proxy-image "${OAUTH_PROXY_IMAGE}" \
  --longhorn-default false \
  --replicas 1

oc apply --dry-run=server -f /tmp/longhorn-okd-v2.yaml
oc apply -f /tmp/longhorn-okd-v2.yaml
```

Use `--mode v1` for a V1-only smoke install. Use `--mode v2` only after the
host has the V2/SPDK prerequisites and raw block disk path prepared. For clean
V2 installs, the helper disables the V1 Data Engine by default. During a
migration where V1 volumes must stay online, add `--keep-v1-engine true`.

Server-side dry-run of the full multi-document OKD manifest can report
`namespaces "longhorn-system" not found` for later namespaced objects because
the dry-run namespace object is not persisted. Treat that as a dry-run artifact
only when the namespace is present earlier in the same manifest and a normal
apply is the next planned step.

Before applying a manifest on SNO, patch the generated StorageClass and default
settings deliberately:

- set `numberOfReplicas: "1"` for the Longhorn StorageClass;
- set `dataEngine: "v1"` or `dataEngine: "v2"` explicitly for the test path;
- keep Longhorn non-default unless the user explicitly wants defaulting;
- preserve exactly one default StorageClass by annotating the replacement class
  before or immediately after install;
- keep `longhorn-storageclass` ConfigMap aligned with the live StorageClass so
  Longhorn reconciliation does not drift it back.

After install, verify settings that are generated at runtime and patch them if
the manifest could not express the desired value:

```bash
oc -n longhorn-system patch settings.longhorn.io default-replica-count \
  --type=merge -p '{"value":"{\"v1\":\"1\",\"v2\":\"1\"}"}'
oc get sc
```

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

When switching between Longhorn data engines on SNO:

- remove obsolete Longhorn MachineConfigs before preparing the new mode;
- wait for the MCP to finish and the node to return `Ready`;
- validate host state with `systemctl`, `findmnt`, `lsblk -f`, `grep Huge /proc/meminfo`, and `lsmod` as appropriate;
- expect temporary API unavailability while the single node reboots.

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
