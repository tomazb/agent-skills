# Install And Preflight

Use this runbook for discovery, installation planning, OpenShift/OKD prerequisites, and first Rook Ceph deployment.

## Live Discovery

Collect current state before choosing a path:

```bash
oc version
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc get ns rook-ceph || true
oc -n rook-ceph get pods,cephclusters.ceph.rook.io,cephblockpools.ceph.rook.io,cephfilesystems.ceph.rook.io,cephobjectstores.ceph.rook.io 2>/dev/null || true
```

## Leftover Install Detection (Rook or ODF)

Before any fresh install, detect uncleaned state from a previous Rook **or** ODF lifecycle. A prior ODF install ships the same Rook/Ceph components under different names, so check for **both** products — a stale mon store or an OSD disk that still carries a BlueStore label will make a fresh mon crash (SIGABRT) and make OSD prepare skip the disk (`Has BlueStore device label`). Namespace or CRD presence alone is not proof of ownership — classify with the Product Ownership Gate first.

Cluster-scoped and namespaced leftovers (survive a namespace delete and must be removed by name):

```bash
# Prior Rook AND prior ODF footprints
oc get ns rook-ceph openshift-storage 2>/dev/null || true
for g in ceph.rook.io ocs.openshift.io csi.ceph.io noobaa.io; do oc api-resources --api-group="$g" 2>/dev/null; done  # one --api-group per call; the flag is not repeatable
oc get crd | grep -E 'ceph\.rook\.io|ocs\.openshift\.io|csi\.ceph\.io|noobaa\.io' || echo "no rook/odf CRDs"
oc get storagecluster -A 2>/dev/null || true         # ODF ownership signal
oc get subscription,csv -A 2>/dev/null | grep -Ei 'rook|ocs|odf|mcg|cephcsi' || echo "no rook/odf OLM operators"
# Orphaned cluster-scoped objects that block a clean reinstall:
oc get sc | grep -E 'rook-ceph|ocs-storagecluster|ceph\.rook\.io|csi\.ceph\.com|noobaa' || echo "no leftover StorageClasses"
oc get csidriver | grep -E 'rook-ceph|ceph\.com' || echo "no leftover Ceph CSIDrivers"
oc get scc | grep -E 'rook-ceph|noobaa' || echo "no leftover Ceph SCCs"
oc get machineconfig | grep -iE 'rook|ocs|odf' || true
oc get pv,pvc -A -o wide 2>/dev/null | grep -E 'rook-ceph|ocs-storagecluster' || echo "no leftover PV/PVC"
```

Node-level leftovers on every candidate storage node (the most common cause of a failed reinstall):

```bash
NODE="<node>"
DISKS="/dev/disk/by-id/<osd-disk-id>"   # edit: space-separated candidate OSD disk(s) by stable path
oc debug "node/${NODE}" -- chroot /host bash -c '
  echo "== stale mon/OSD dataDirHostPath =="
  if [ ! -d /var/lib/rook ]; then echo "/var/lib/rook absent (clean)"
  else n=$(ls -A /var/lib/rook | wc -l); [ "$n" -eq 0 ] && echo "/var/lib/rook present but empty" || { echo "STALE ($n entries):"; ls -A /var/lib/rook; }; fi
  for p in /var/lib/rook/mon-* /var/lib/rook/openshift-storage; do [ -e "$p" ] && echo "stale dir: $p"; done
  echo "== OSD disk still carries a raw BlueStore label? =="
  # lsblk -f and wipefs -n show TYPE "ceph_bluestore" for a raw BlueStore label.
  [ -n '"$DISKS"' ] || { echo "no candidate disks configured" >&2; exit 1; }
  for d in '"$DISKS"'; do
    [ -b "$d" ] || { echo "invalid candidate disk: $d" >&2; exit 1; }
    lsblk_out=$(lsblk -f "$d") || exit 1
    printf "%s\n" "$lsblk_out"
    wipefs_out=$(wipefs -n "$d") || exit 1
    printf "%s\n" "$wipefs_out"
    if printf "%s\n%s\n" "$lsblk_out" "$wipefs_out" | grep -Fq ceph_bluestore; then
      echo "BlueStore signature remains on $d; do not reuse the disk" >&2
      exit 1
    fi
  done
  echo "== stale krbd device mappings (leaked by a prior teardown)? =="
  ls /dev/rbd[0-9]* 2>/dev/null && echo "STALE krbd present" || echo "no /dev/rbd[0-9]* devices"
  for r in /sys/bus/rbd/devices/*; do [ -e "$r" ] && echo "rbd $(basename $r): pool=$(cat $r/pool 2>/dev/null) image=$(cat $r/name 2>/dev/null)"; done
' || { echo "node leftover inspection failed; do not reuse the disk" >&2; exit 1; }

# RHCOS does not ship ceph-volume. Run the LVM residue audit from a node-local helper
# container that carries it and bind the host device/LVM paths into that container.
# `ceph-volume lvm list` exits 1 and prints "No valid Ceph lvm devices found" when the
# disk has no LVM OSD. That is an empty inventory. Exit 0 means ceph-volume found an
# LVM OSD on the disk, so reject it. Fail closed when the helper cannot
# run: image pull, mount, missing ceph-volume, or an unreadable device. Run the raw
# list in the same helper and require it to print {}. Do not use set -e here: the
# empty-inventory exit would skip it.
ROOK_CEPH_IMAGE="quay.io/ceph/ceph:v19.2.2"   # or the cephVersion.image you plan to deploy
oc debug "node/${NODE}" --image="${ROOK_CEPH_IMAGE}" -- bash -c '
  mkdir -p /run/lvm /etc/lvm
  mount --rbind /host/dev /dev || { echo "LVM residue audit failed; do not reuse the disk" >&2; exit 1; }
  mount --rbind /host/run/lvm /run/lvm || { echo "LVM residue audit failed; do not reuse the disk" >&2; exit 1; }
  mount --rbind /host/etc/lvm /etc/lvm || { echo "LVM residue audit failed; do not reuse the disk" >&2; exit 1; }
  [ -n '"$DISKS"' ] || { echo "no candidate disks configured" >&2; exit 1; }
  for d in '"$DISKS"'; do
    [ -b "$d" ] || { echo "invalid candidate disk: $d" >&2; exit 1; }
    lvm_rc=0
    lvm_out=$(ceph-volume lvm list "$d" 2>&1) || lvm_rc=$?
    printf "%s\n" "$lvm_out"
    if [ "$lvm_rc" -eq 0 ]; then
      echo "LVM OSD metadata found on $d; do not reuse the disk" >&2
      exit 1
    fi
    stripped=$(printf "%s\n" "$lvm_out" | sed "/^$/d")
    if [ "$stripped" != "No valid Ceph lvm devices found" ]; then
      echo "LVM residue audit failed; do not reuse the disk" >&2
      exit 1
    fi
    echo "== raw list =="
    raw_out=$(ceph-volume raw list "$d" --format json) || { echo "LVM residue audit failed; do not reuse the disk" >&2; exit 1; }
    printf "%s\n" "$raw_out"
    if [ "$(printf "%s" "$raw_out" | tr -d "[:space:]")" != "{}" ]; then
      echo "Raw Ceph inventory is not empty for $d; do not reuse the disk" >&2
      exit 1
    fi
  done
' || { echo "LVM residue audit failed; do not reuse the disk" >&2; exit 1; }
```

**Stale krbd devices are a silent killer.** If a prior Rook/ODF teardown deleted an RBD-backed PVC (or its whole namespace) *before* the volume was unmapped, or deleted the Ceph pool out from under a mapped image, the node keeps a wedged `/dev/rbdN` device pointing at a pool that no longer exists. A fresh Rook OSD prepare then hangs **forever** at `ceph-volume raw list` (it probes every block device, including the dead `/dev/rbdN`). The device cannot be force-removed from userspace — `/sys/bus/rbd/remove*` blocks uninterruptibly, and it can even wedge a node shutdown. Clear it before installing (see `maintenance-uninstall.md`, "Stale krbd Devices"); a wedged device may require a node reboot or hypervisor power-cycle.

If any of these exist and the target node is not running an intended storage system, remove them before installing — follow `maintenance-uninstall.md` (orphaned StorageClasses/CSIDrivers, stuck `clientprofiles.csi.ceph.io` finalizers, `/var/lib/rook` clearing, stale krbd unmap) and `references/osd-disk-prep.md` for a leftover BlueStore OSD. `wipefs -af` and `sgdisk --zap-all` are not sufficient: the label is also stored at 1 GiB, 10 GiB, 100 GiB, and 1000 GiB, whichever fit. Reuse the disk only when `ceph-volume raw list` prints `{}` and `wipefs -n` and `lsblk -f` no longer report `ceph_bluestore`. An empty raw list can still leave a signature that OSD prepare skips with `Has BlueStore device label`. A clean `lsblk` can still leave a foreign OSD that raw list names. Either result alone is incomplete. Full-disk zeroing is only for when the whole device must be erased. A Rook cleanup handoff is required when the leftover is upstream Rook; an ODF cleanup handoff (`openshift-odf`) is required when the leftover is ODF-owned. Only after the leftover audit is clean should you proceed.

## Ceph Version And ceph-csi Compatibility

Use AES256K when every schedulable node mounts a volume created with an AES256K CSI key and a write succeeds. Keep AES256K after that probe. Classic AES is the cipher when a probe node reports that it cannot map the key.

AES256K keys use key byte `0x02` and the base64 prefix `Ag`. Classic AES keys use key byte `0x01` and the prefix `AQ`. A fresh Ceph Tentacle `v20.2.4` (and later) or Squid `v19.2.6` (and later) issues AES256K. Pin `cephVersion.image` to `quay.io/ceph/ceph:v20.2.4` for that probe. Read the ceph-csi image Rook will deploy before creating the CephCluster. Leave the newest `quay.io/ceph/ceph` tag in upstream `cluster.yaml` unused until the probe passes.

The secure default is `spec.security.cephx.allowedCiphers: [aes256k]` plus `spec.security.cephx.csi.keyType: aes256k`. Leave `spec.security.cephx.daemon.keyType` unset. Setting it adds `--mon-auth-emergency-allowed-ciphers` to the monitors and raises `AUTH_EMERGENCY_CIPHERS_SET`. Rook selects the daemon key type itself. An empty `allowedCiphers` list allows every cipher, which raises `AUTH_INSECURE_KEYS_ALLOWED` and `AUTH_INSECURE_KEYS_CREATABLE`. Allow `aes` only when the user asks for classic AES, or when the volume probe cannot mount an AES256K key.

**Reported field evidence (not independently reproduced):** An OpenShift 4.20 RHCOS node running kernel `5.14.0-570.134.1.el9_6` mapped an AES256K RBD volume at `/dev/rbd0`. A compact three-node OpenShift 4.21.34 cluster running RHCOS kernel `5.14.0-570.141.1.el9_6`, Rook `v1.21.0`, and ceph-csi `v3.18.1` reportedly wrote through an AES256K RBD mapping at `/dev/rbd0` on every schedulable node. An OpenShift 4.18.56 SNO node running RHCOS kernel `5.14.0-427.151.1.el9_4` with FIPS off, Rook `v1.21.1`, Ceph `v20.2.4`, and ceph-csi `v3.18.1` wrote through an AES256K RBD mapping at `/dev/rbd0`. A full `ceph auth dump-keys` audit on that cluster reported 25 `aes256k` keys, and `lvms-vg1` stayed the only default StorageClass. These observations are not a compatibility guarantee for all 5.14 kernels or FIPS configurations. Capture the kernel, FIPS state, Ceph/Rook/CSI versions, effective MonMap policy, audited key types, and per-node `/dev/rbd*` write/read results. The live volume probe, not the kernel release string, decides.

**Discover the ceph-csi image before the CephCluster.** The CSI Deployment may not exist yet. Read the operator image-set, or the manifest about to be applied:

```bash
oc -n rook-ceph get cm rook-csi-operator-image-set-configmap -o jsonpath='{.data.plugin}{"\n"}' 2>/dev/null \
  || grep -E 'cephcsi/cephcsi:|ROOK_CSI_CEPH_IMAGE' /tmp/rook-ceph-operator.yaml
```

An empty `plugin` value is not `v3.17.0`. Rook v1.21 leaves that field empty so the ceph-csi-operator uses its built-in default. ceph-csi-operator v1.1.0's built-in plugin is `quay.io/cephcsi/cephcsi:v3.18.1`. `operator-openshift.yaml` applies the RBD and CephFS `Driver` CRs with the operator, so the plugin Deployments exist before the CephCluster. Read the running `csi-rbdplugin` image and `ceph --version` before creating the cluster. Continue with AES256K when that client is Ceph `v20.2.4` or newer. Patch the image-set when the running plugin is older than `v3.17.1`.

ceph-csi **v3.17.0** bundles a librados that cannot decode AES256K. Claims stay `Pending` with `failed to decode key` and `rados: ret=-22, Invalid argument`. ceph-csi **v3.17.1** bundles Ceph `v20.2.4` and decodes those keys. RGW and ObjectBucketClaim provisioning skip this librados path, so an object-store check can succeed while every RBD, CephFS, and NFS claim fails.

When the image-set pins `quay.io/cephcsi/cephcsi:v3.17.0`, move it to `quay.io/cephcsi/cephcsi:v3.17.1` and let the CSI operator roll the plugins before the CephCluster is created:

```bash
oc -n rook-ceph patch cm rook-csi-operator-image-set-configmap --type=merge \
  -p '{"data":{"plugin":"quay.io/cephcsi/cephcsi:v3.17.1"}}'
oc -n rook-ceph rollout restart deploy/ceph-csi-controller-manager
oc -n rook-ceph rollout status deploy/ceph-csi-controller-manager --timeout=3m
```

After the RBD, CephFS, and NFS plugin Deployments exist, each plugin image is `quay.io/cephcsi/cephcsi:v3.17.1` and the RBD plugin reports Ceph `v20.2.4` or newer:

```bash
oc -n rook-ceph exec deploy/rook-ceph.rbd.csi.ceph.com-ctrlplugin -c csi-rbdplugin -- ceph --version
```

When the image-set cannot move to a ceph-csi build that decodes AES256K, install Squid `v19.2.2` and omit `security.cephx`. A `v20` mon and OSD store cannot be downgraded onto `v19` (`unsupported features: ...aes256k`). Wipe and redeploy to change major versions.

**Create the cluster with AES256K keys** once the CSI image can decode them:

```yaml
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v20.2.4
  security:
    cephx:
      allowedCiphers:
      - aes256k
      csi:
        keyType: aes256k
```

When the user requests classic AES, set `allowedCiphers` to `aes` and `aes256k` and set `csi.keyType` to `aes` instead of the block above.

After the cluster is `Ready`, `status.cephx.csi.keyType` is `aes256k`, the admin key prefix is `Ag`, and `ceph health detail` does not contain `AUTH_INSECURE_KEYS_ALLOWED`, `AUTH_INSECURE_KEYS_CREATABLE`, or `AUTH_EMERGENCY_CIPHERS_SET`:

```bash
oc -n rook-ceph get cephcluster rook-ceph -o jsonpath='{.status.cephx.csi.keyType}{"\n"}{.spec.security.cephx.allowedCiphers}{"\n"}'
# For an existing cluster, run the full CephX audit in references/validation-hardening.md before restricting ciphers.
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
oc -n rook-ceph get pod -l app=rook-ceph-mon -o jsonpath='{range .items[*]}{.spec.containers[0].args}{"\n"}{end}'
```

The mon arguments do not include `--mon-auth-emergency-allowed-ciphers`. On an existing cluster, run the complete `ceph auth dump-keys` audit in `references/validation-hardening.md` using `scripts/check_cephx_key_types.py` before restricting `allowedCiphers`. Checking only `client.admin`, CSI Secrets, or key prefixes is insufficient: pending, expiring, and rotating service keys also matter. Do not run `ceph auth ls` for this gate: it reveals authentication keys and cannot substitute for the full audit. Every audited key must report `aes256k`. If any key still uses `aes`, keep it allowed until that key and its consumers have migrated. Restricting the list while a daemon key is still classic AES returns `RADOS permission denied` and can make the cluster unavailable.

**Probe one RBD volume on every schedulable node** after the block pool and StorageClass from `references/rbd-block-pools.md` exist. Substitute the class this install uses. A passing probe is the RBD smoke for `references/validation-hardening.md`. One scheduler-placed pod proves the cipher only on the node where it lands. The smoke helper uses required node affinity matching the Node's `metadata.name`, not `spec.nodeName`, so the scheduler still participates when the selected StorageClass uses `WaitForFirstConsumer`. The smoke image is `ubi9/ubi-minimal`, which has a shell and does not have `awk`, so the mount check stays inside `sh -c`.

A schedulable node is `Ready`, is not cordoned, and has no `NoSchedule` or `NoExecute` taint. The probe pod has no tolerations. An empty list means no node can run the probe; stop and fix scheduling before choosing a cipher.

```bash
oc get nodes -o json | python3 -c '
import json, sys
for node in json.load(sys.stdin)["items"]:
    spec = node["spec"]
    if spec.get("unschedulable"):
        continue
    taints = spec.get("taints") or []
    if any(taint.get("effect") in ("NoSchedule", "NoExecute") for taint in taints):
        continue
    ready = any(
        cond.get("type") == "Ready" and cond.get("status") == "True"
        for cond in (node.get("status") or {}).get("conditions") or []
    )
    if ready:
        print(node["metadata"]["name"])
'
```

Run the probe on each printed node. Stop at the first command that fails. The RWO claim must not stay pinned to the previous node, so each node ends in one of three outcomes:

- Success: the write prints `ok` and the mount device starts with `/dev/rbd`. Record both, then delete the namespace and start the next node.
- Scheduling or startup failure (`Pending`, `ImagePullBackOff`, `CrashLoopBackOff`): record the pod events, then delete the namespace, fix it, and run the probe again.
- Key or mapping failure: keep the namespace until the key rotation below has finished, then delete it.

Keep AES256K only when every node prints `ok` and a mount device that starts with `/dev/rbd`.

```bash
python3 scripts/render_smoke_manifest.py \
  --mode rbd \
  --namespace rook-rbd-aes256k-probe \
  --storage-class rook-ceph-block \
  --node-name "<node>" \
  --output /tmp/rook-rbd-aes256k-probe.yaml
oc apply -f /tmp/rook-rbd-aes256k-probe.yaml
oc -n rook-rbd-aes256k-probe wait pod/rbd-smoke-writer --for=condition=Ready --timeout=5m
oc -n rook-rbd-aes256k-probe get pod rbd-smoke-writer -o jsonpath='{.spec.nodeName}{"\n"}'  # confirm requested node
oc -n rook-rbd-aes256k-probe exec rbd-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
oc -n rook-rbd-aes256k-probe exec rbd-smoke-writer -- sh -c 'while read -r dev mp _; do [ "$mp" = /data ] && echo "$dev"; done < /proc/mounts'
```

Only after the `ok` write and the `/dev/rbd` mount device are recorded for this node, delete the probe namespace:

```bash
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-aes256k-probe
```

When the PVC stays `Pending` with `rados: ret=-22` and the plugin image is still older than `v3.17.1`, apply the image-set patch above, wait for the plugin rollout, and run the probe once more.

When the pod does not become `Ready`, read the pod events and the RBD node plugin log from the probe node before changing ciphers. The node plugin is a DaemonSet, so a DaemonSet-wide log can come from a different node.

```bash
oc -n rook-rbd-aes256k-probe describe pod rbd-smoke-writer
oc -n rook-ceph logs -c csi-rbdplugin --tail=80 \
  "$(oc -n rook-ceph get pod --field-selector spec.nodeName=<node> -o name | grep 'rbd.csi.ceph.com-nodeplugin')"
```

A `Pending` pod, `ImagePullBackOff`, or `CrashLoopBackOff` is not a cipher result. Leave the namespace only while those events and the plugin log are still being read, then delete it, fix scheduling or startup, and run the probe again. Skip this delete when the events are a key or mapping failure; that namespace stays until the rotation below has finished:

```bash
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-aes256k-probe
```

Rotate the CSI key only when a `FailedMount` event or that node plugin log reports a key or mapping failure (`failed to decode key`, `rados: ret=-22`, or the kernel rejecting the key). One confirmed mapping failure means a later volume can land on that node, so the cluster cannot stay on `aes256k` alone. Keep the Ceph image. Do not delete the probe namespace before this rotation. Read `status.cephx.csi.keyGeneration` first. A fresh cluster reports `1` or an empty generation; the first rotation uses `2`. A later rotation uses one more than the current generation. `keepPriorKeyCountMax: 1` leaves the previous CSI key in place so the bound probe volume can still unmap.

```bash
CURRENT=$(oc -n rook-ceph get cephcluster rook-ceph -o jsonpath='{.status.cephx.csi.keyGeneration}')
if [ -z "$CURRENT" ]; then NEXT=2; else NEXT=$((CURRENT + 1)); fi
oc -n rook-ceph patch cephcluster rook-ceph --type=merge -p \
  "{\"spec\":{\"security\":{\"cephx\":{\"allowedCiphers\":[\"aes\",\"aes256k\"],\"csi\":{\"keyRotationPolicy\":\"KeyGeneration\",\"keyGeneration\":${NEXT},\"keepPriorKeyCountMax\":1,\"keyType\":\"aes\"}}}}}"
```

Wait until `status.cephx.csi.keyGeneration` equals `NEXT`, `status.cephx.csi.priorKeyCount` is at least `1`, `status.cephx.csi.keyType` is `aes`, and `userKey` in `rook-csi-rbd-provisioner` starts with `AQ`. Then delete the probe namespace and repeat the probe in a new namespace:

```bash
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rbd-aes256k-probe
```

New PVCs use the classic AES key. The prior key remains for volumes that mounted with it. Daemon keys stay AES256K. `AUTH_INSECURE_KEYS_ALLOWED` returns for this exception. Do not set `daemon.keyType`.

When `quay.io/cephcsi/cephcsi:v3.17.1` is running and the probe still fails with `rados: ret=-22`, wipe the cluster with `references/maintenance-uninstall.md` and install Squid `v19.2.2` without `security.cephx`. Do not downgrade the existing `v20` store in place.

## Node and Disk Discovery

For each candidate OSD disk, use a stable path and capture non-destructive evidence:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${DISK}'
  lsblk -f '${DISK}'
  wipefs -n '${DISK}' || true
  ceph-volume lvm list '${DISK}' || true
  lsblk -f
"
```

Never proceed from `/dev/nvmeXnY`, `/dev/sdX`, or a guessed path alone. Resolve and record the `/dev/disk/by-id/*` or `/dev/disk/by-path/*` identity first.

## OpenShift Prerequisites

Rook Ceph needs elevated privileges (host paths for OSDs, privileged CSI). On
OpenShift, prefer the upstream OpenShift manifests, which create dedicated,
scoped SecurityContextConstraints instead of granting the broad built-in
`privileged` SCC to service accounts:

- Use `operator-openshift.yaml` instead of `operator.yaml` (see Direct Manifest
  Install below). It defines a dedicated `rook-ceph` SCC (and a `rook-ceph-csi`
  SCC) bound to the Rook service accounts, and sets
  `ROOK_HOSTPATH_REQUIRES_PRIVILEGED=true` so OSD pods using host paths run
  correctly.
- The upstream `rook-ceph` SCC ships with `allowHostNetwork: false` and
  `allowHostPorts: false`. When `CephCluster.spec.network.provider: host` is
  explicitly selected, the mon canary pods can fail SCC admission with
  `host network is not allowed` or rejected host ports `3300` and `6789`.
  Use the **Host-Network SCC Gate** after the operator install and before
  creating the CephCluster. Leave these permissions disabled for pod-network
  clusters; enabling them expands permissions for all users of this SCC.
- The dedicated `rook-ceph` SCC binds these service accounts: `rook-ceph-system`,
  `rook-ceph-default`, `rook-ceph-mgr`, `rook-ceph-osd`, and `rook-ceph-rgw`.
  Confirm they are covered before deploying OSDs or an object store.

If you must grant SCCs manually (a customized install), grant **all** the service
accounts the workloads use — omitting `rook-ceph-rgw` or `rook-ceph-default`
causes RGW or OSD-prepare pods to fail admission:

```bash
oc adm policy add-scc-to-user privileged -z rook-ceph-system -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-default -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-osd -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-mgr -n rook-ceph
oc adm policy add-scc-to-user privileged -z rook-ceph-rgw -n rook-ceph
```

`oc apply` of `operator-openshift.yaml` can warn that the operator container would violate PodSecurity `restricted:latest` (`allowPrivilegeEscalation`, capabilities, and `seccompProfile`). OpenShift admits that pod through the `rook-ceph` SCC. Continue when the Deployment is created and the SCC lists the Rook service accounts. Stop when the pod stays pending with an SCC admission error.

## Install Path

### Helm Install (Recommended)

The `rook-ceph` chart installs the **operator only** — the CephCluster CR and
pools below are applied separately (or via the companion `rook-ceph-cluster`
chart). The operator chart ships the OpenShift SecurityContextConstraints; after
install, verify they exist with `oc get scc rook-ceph rook-ceph-csi`.

```bash
helm repo add rook-release https://charts.rook.io/release
helm repo update rook-release
helm install rook-ceph rook-release/rook-ceph \
  --namespace rook-ceph --create-namespace
```

### Direct Manifest Install (OLM or YAML)

For OLM-based installs, use the OperatorHub or an OLM Subscription. For direct manifest installs, pin the version, create the namespace explicitly on a fresh cluster, apply the Ceph CSI operator manifest (`csi-operator.yaml`), then use the OpenShift operator manifest (`operator-openshift.yaml`), which ships the dedicated SCCs described above:

```bash
ROOK_VERSION="v<version>"
curl -fsSLo /tmp/rook-ceph-crds.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/crds.yaml"
curl -fsSLo /tmp/rook-ceph-common.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/common.yaml"
curl -fsSLo /tmp/rook-ceph-csi-operator.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/csi-operator.yaml"
curl -fsSLo /tmp/rook-ceph-operator.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/operator-openshift.yaml"
```

On SNO, edit `/tmp/rook-ceph-operator.yaml` now, before its first apply: add `replicas: 1` under `spec.driverSpecDefaults.controllerPlugin` of the `ceph-csi-operator-config` `OperatorConfig`, and keep its `imageSet` and other fields. See the SNO section below for why and how to verify it.

Create the namespace before `common.yaml` on a fresh cluster. Apply CRDs first (required before common, CSI, and operator manifests), then common, then `csi-operator.yaml`, then the OpenShift operator. Apply the CRDs server-side — the Rook CRDs are large and client-side `oc apply` can fail with a `metadata.annotations: Too long` error:

```bash
oc get ns rook-ceph >/dev/null 2>&1 || oc create ns rook-ceph
oc apply --server-side --force-conflicts -f /tmp/rook-ceph-crds.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-common.yaml
oc apply -f /tmp/rook-ceph-common.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-csi-operator.yaml
oc apply -f /tmp/rook-ceph-csi-operator.yaml
oc apply --dry-run=server -f /tmp/rook-ceph-operator.yaml
oc apply -f /tmp/rook-ceph-operator.yaml
```

Newer Rook releases use `csi.ceph.io/v1` resources such as `CephConnection`,
`Driver`, and `OperatorConfig`. If `csi-operator.yaml` is omitted, a new
`CephCluster` can stall with `no matches for kind "CephConnection"` even though
the main operator deployment is running.

### Host-Network SCC Gate (Only When Selected)

Run the Product Ownership Gate first; stop for ODF-owned, mixed, or unknown
ownership. After the upstream Rook operator has created the `rook-ceph` SCC
and **before** applying a CephCluster using `spec.network.provider: host`,
inspect its permissions and every authorization path. Do not patch
`rook-ceph-csi` or grant the built-in `privileged` SCC as a workaround.
For pod networking, leave the `rook-ceph` SCC defaults unchanged.

**Read-only authorization audit (stop if any command fails):**

```bash
# READ-ONLY SCC authorization audit; complete it before any permission change.
(
  set -euo pipefail
  oc get scc rook-ceph -o jsonpath='{.allowHostNetwork}{" "}{.allowHostPorts}{"\n"}'
  oc get scc rook-ceph -o jsonpath='{range .users[*]}{.}{"\n"}{end}'
  oc get scc rook-ceph -o jsonpath='{range .groups[*]}{.}{"\n"}{end}'
  # who-can evaluates namespaced RBAC. Enumerate *all* namespaces before
  # widening this cluster-scoped SCC; a RoleBinding outside rook-ceph matters.
  namespaces=$(oc get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}') || {
    echo 'STOP: cannot enumerate namespaces for SCC RBAC audit' >&2
    exit 1
  }
  [ -n "$namespaces" ] || {
    echo 'STOP: namespace inventory is empty; SCC RBAC audit is incomplete' >&2
    exit 1
  }
  while IFS= read -r namespace; do
    [ -n "$namespace" ] || {
      echo 'STOP: invalid empty namespace in SCC RBAC audit' >&2
      exit 1
    }
    printf '\n== SCC RBAC use grants in namespace %s ==\n' "$namespace"
    # 'oc who-can' can report partial authorization results even with exit 0.
    who_can_output=$(oc -n "$namespace" adm policy who-can use scc rook-ceph 2>&1) || {
      echo "STOP: SCC RBAC audit failed in namespace ${namespace}" >&2
      exit 1
    }
    if grep -Eiq 'error during evaluation|evaluationerror|evalutionerror' <<< "$who_can_output"; then
      echo "STOP: incomplete SCC RBAC authorization evaluation in namespace ${namespace}" >&2
      exit 1
    fi
    if ! grep -Eq '^Users:[[:space:]]' <<< "$who_can_output" ||
       ! grep -Eq '^Groups:[[:space:]]' <<< "$who_can_output"; then
      echo "STOP: missing SCC RBAC authorization results in namespace ${namespace}" >&2
      exit 1
    fi
    printf '%s\n' "$who_can_output"
  done <<< "$namespaces"
)
```

The SCC `users` and `groups` fields show **direct** grants; `oc adm policy
who-can use scc rook-ceph` shows **RBAC** grants in the selected namespace,
not direct SCC assignments. The audit explicitly queries **every namespace**
because a RoleBinding outside `rook-ceph` can authorize use of this shared,
cluster-scoped SCC. Review all listed users, group membership, and
RoleBinding/ClusterRoleBinding subjects and scope (including broad groups or
wildcard RBAC rules) against the intended Rook workloads. Run this check
immediately before applying the patch, and account for namespace/RBAC changes
between the audit and the mutation. OpenShift `who-can` can print
`Error during evaluation, results may not be complete` despite exiting with
status 0. The audit rejects that diagnostic, `evaluationError` / `evalutionError`
field variants, and missing user/group summaries, so an incomplete query
cannot authorize the SCC change. **STOP without patching** if the audit fails or
any principal or group membership is unexpected or cannot be classified. If
sharing this SCC is inappropriate, design a separately scoped SCC/grant instead;
do not silently widen permissions for other workloads.

**Only after** confirming upstream Rook ownership, explicit host networking,
and approval of the affected principals, apply the change:

```bash
oc patch scc rook-ceph --type=merge \
  -p '{"allowHostNetwork":true,"allowHostPorts":true}'
oc get scc rook-ceph -o jsonpath='{.allowHostNetwork}{" "}{.allowHostPorts}{"\n"}'
```

Verify both fields read back as `true`, then create the CephCluster and check
mon canary events and reconciliation. Changing an SCC does not normally require
restarting the operator. If reconciliation remains stalled after admission
succeeds, inspect `oc -n rook-ceph logs deploy/rook-ceph-operator` and pod
events before considering a deliberate operator restart.

Reapplying the unmodified upstream OpenShift manifest can reset these SCC
fields to `false`. Persist the host-network settings in the version-pinned
manifest, Helm post-renderer, or GitOps overlay used by the installation;
verify them again after an upgrade or reapply.

## CephCluster CR for SNO

On SNO, use a CephCluster with minimal mon/mgr counts and explicit device
pinning when the user names a dedicated OSD disk:

```yaml
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata:
  name: rook-ceph
  namespace: rook-ceph
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v<ceph-version>
    allowUnsupported: false
  # Default. Add aes to allowedCiphers only when the user requests classic AES or a probe node reports a key-mapping failure.
  security:
    cephx:
      allowedCiphers:
      - aes256k
      csi:
        keyType: aes256k
  dataDirHostPath: /var/lib/rook
  mon:
    count: 1
    allowMultiplePerNode: true
  mgr:
    count: 1
    allowMultiplePerNode: true
  dashboard:
    enabled: true
  cephConfig:
    global:
      osd_pool_default_size: "1"
      mon_warn_on_pool_no_redundancy: "false"
      mon_max_pg_per_osd: "500"
  storage:
    useAllNodes: false
    useAllDevices: false
    config:
      osdsPerDevice: "1"
    nodes:
    - name: "<sno-node>"
      devices:
      - name: "/dev/disk/by-id/<stable-disk-id>"
```

Prefer explicit `/dev/disk/by-id/...` device pinning when the user has already
identified one OSD disk. Reserve `useAllDevices: true` for nodes that are
intentionally dedicated to Ceph. If the SNO node is tainted for storage
workloads, add the required toleration block explicitly instead of assuming it.

Do not copy `mon.count: 1`, `allowMultiplePerNode: true`, or
`mon_max_pg_per_osd: "500"` into multi-node production plans without explicit
direction.

The ceph-csi-operator built-in controller replica count is 2, and the controller Deployment uses required pod anti-affinity on `kubernetes.io/hostname`. On SNO the second replica stays Pending. Set one replica on the shared driver defaults before the CephCluster, and do not copy `replicas: 1` into a multi-node plan without explicit direction.

`operator-openshift.yaml` already creates `ceph-csi-operator-config` with `driverSpecDefaults.imageSet` and the other driver defaults. Add the replica count to that object. Do not `oc apply` a standalone `OperatorConfig` that carries only `replicas`: client-side apply prunes the fields it omits, including the image-set link. On a direct-manifest install, make that edit in `/tmp/rook-ceph-operator.yaml` before its first apply, as the Direct Manifest Install step says. When the object already exists, merge-patch it and keep the same field in any manifest you reapply:

```bash
oc -n rook-ceph patch operatorconfig.csi.ceph.io ceph-csi-operator-config --type=merge \
  -p '{"spec":{"driverSpecDefaults":{"controllerPlugin":{"replicas":1}}}}'
oc -n rook-ceph get operatorconfig.csi.ceph.io ceph-csi-operator-config \
  -o jsonpath='{.spec.driverSpecDefaults.controllerPlugin.replicas} {.spec.driverSpecDefaults.imageSet.name}{"\n"}'
```

Continue when the second command prints `1 rook-csi-operator-image-set-configmap`. Stop when the image-set name is empty.

When preparing version-pinned example manifests, prefer the packaged helper and
pass explicit Rook/Ceph versions from live discovery (do not treat helper defaults
as the install target). The helper only substitutes exact placeholder tokens such
as `CEPH_VERSION_PLACEHOLDER` and `ROOK_VERSION_PLACEHOLDER`; prose tokens like
`v<ceph-version>` are left unchanged. Put those placeholder tokens in the input
manifest first, for example:

```yaml
spec:
  cephVersion:
    image: quay.io/ceph/ceph:CEPH_VERSION_PLACEHOLDER
```

```bash
python3 scripts/patch_rook_ceph_manifest.py \
  --input /tmp/rook-ceph-cluster.yaml \
  --output /tmp/rook-ceph-cluster-patched.yaml \
  --rook-version "${ROOK_VERSION}" \
  --ceph-version "${CEPH_VERSION}" \
  --replicas 1 \
  --mon-count 1 \
  --mgr-count 1 \
  --allow-multiple-per-node

oc apply --dry-run=server -f /tmp/rook-ceph-cluster-patched.yaml
```

Only after reviewing the patched image pins and topology, apply:

```bash
oc apply -f /tmp/rook-ceph-cluster-patched.yaml
```

## CephCluster CR for Multi-Node Production

```yaml
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata:
  name: rook-ceph
  namespace: rook-ceph
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v<ceph-version>
  # Default. Add aes to allowedCiphers only when the user requests classic AES or a probe node reports a key-mapping failure.
  security:
    cephx:
      allowedCiphers:
      - aes256k
      csi:
        keyType: aes256k
  dataDirHostPath: /var/lib/rook
  mon:
    count: 3
    allowMultiplePerNode: false
  mgr:
    count: 2
    allowMultiplePerNode: false
  dashboard:
    enabled: true
  storage:
    useAllNodes: false
    nodes:
    - name: "node-1"
      devices:
      - name: "/dev/disk/by-id/<disk-1>"
    - name: "node-2"
      devices:
      - name: "/dev/disk/by-id/<disk-2>"
    - name: "node-3"
      devices:
      - name: "/dev/disk/by-id/<disk-3>"
  network:
    provider: host
    connections:
      requireMsgr2: false
  placement:
    all:
      nodeAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          nodeSelectorTerms:
          - matchExpressions:
            - key: node.ocs.openshift.io/storage
              operator: In
              values:
              - "true"
```

Label storage nodes explicitly:

```bash
oc label node <node-1> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-2> node.ocs.openshift.io/storage=true --overwrite
oc label node <node-3> node.ocs.openshift.io/storage=true --overwrite
```

## Deploy the Toolbox

The Rook Ceph toolbox provides the `ceph` CLI inside the cluster. It is not deployed automatically — apply it explicitly before running any `ceph` commands:

```bash
curl -fsSLo /tmp/rook-ceph-toolbox.yaml \
  "https://raw.githubusercontent.com/rook/rook/${ROOK_VERSION}/deploy/examples/toolbox.yaml"
oc apply -f /tmp/rook-ceph-toolbox.yaml
oc -n rook-ceph rollout status deploy/rook-ceph-tools --timeout=5m
```

The example toolbox image is the floating tag `quay.io/ceph/ceph:v20`. Before apply, set that container image to the CephCluster `cephVersion.image`, for example `quay.io/ceph/ceph:v20.2.4`.

## Install Validation

Wait for the operator and cluster to reach a healthy state:

```bash
oc -n rook-ceph rollout status deploy/rook-ceph-operator --timeout=10m
oc -n rook-ceph wait cephcluster/rook-ceph --for=condition=Ready --timeout=15m
oc -n rook-ceph get pods -o wide
oc -n rook-ceph get cephcluster -o wide
```

Check Ceph cluster health via the toolbox:

```bash
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail
```

`status.phase: Ready` can arrive while `status.ceph.health` is still `HEALTH_WARN` because the crash collector and exporter restart during bootstrap. Read `ceph health detail` before changing ciphers, pools, or OSDs. Declare success only after `scripts/check_rook_health.py` records sustained `HEALTH_OK`.

Before declaring success, verify:

- All mons are in quorum.
- All OSDs are `up` and `in`.
- Ceph cluster health is `HEALTH_OK` or `HEALTH_WARN` with known, documented warnings. `AUTH_INSECURE_KEYS_ALLOWED` and `AUTH_INSECURE_KEYS_CREATABLE` are absent unless the user requested classic AES or the volume probe had to allow it.
- The AES256K probe in **Ceph Version And ceph-csi Compatibility** has finished: either `allowedCiphers` is `aes256k` alone because every schedulable node wrote through `/dev/rbd`, or CSI keys are classic AES after a confirmed key-mapping `FailedMount`.
- No PGs are stuck in `creating`, `degraded`, or `peering`.
- Exactly one default StorageClass exists when defaulting is expected.

## Snapshot readiness

After creating RBD/CephFS StorageClasses, complete [snapshot setup and verification](backup-restore-dr.md#snapshot-readiness) before declaring the install complete. Configure supported snapshotting even if the cluster has no PVCs yet. Record any explicit opt-out, unsupported service, or blocked prerequisite; healthy Ceph and CSI pods do not replace this check.

## Enable The Rook Orchestrator Backend

This manager integration is optional. The Rook Kubernetes operator does not need
it. Enable it only when dashboard orchestrator features or `ceph orch` are needed,
after checking the exact running Ceph release with the read-only compatibility
gate below. Ceph 20.2.3 and 20.2.4 raise `node_proxy_fullreport` NotImplementedError
on Prometheus scrapes. Later Tentacle patches remain unverified until an upstream
fix is confirmed. See [Rook issue 18124](https://github.com/rook/rook/issues/18124).
A failed gate must prevent both enablement and backend changes:

```bash
(
set -euo pipefail
TARGET_CONTEXT="<target-context>"
ROOK_CEPH_VERSION=$(oc --context "$TARGET_CONTEXT" -n rook-ceph exec deploy/rook-ceph-tools -- ceph version)
ROOK_CEPH_VERSION=${ROOK_CEPH_VERSION#ceph version }
ROOK_CEPH_VERSION=${ROOK_CEPH_VERSION%% *}
python3 scripts/check_rook_mgr_compatibility.py --version "$ROOK_CEPH_VERSION"
oc --context "$TARGET_CONTEXT" -n rook-ceph exec deploy/rook-ceph-tools -- ceph mgr module enable rook
oc --context "$TARGET_CONTEXT" -n rook-ceph exec deploy/rook-ceph-tools -- ceph orch set backend rook
oc --context "$TARGET_CONTEXT" -n rook-ceph exec deploy/rook-ceph-tools -- ceph orch status
)
```

On an affected release, keep the `rook` entry in `spec.mgr.modules` disabled.
Preserve all other entries and leave Prometheus enabled. If this module is already
causing crashes, follow the authorized-remediation instructions in
[validation-hardening.md](validation-hardening.md#optional-rook-manager-regression).
Do not hide the symptom by muting crash health checks, archiving arbitrary crashes,
or downgrading Ceph. Some dashboard features and `ceph orch` remain unavailable
while the optional module is disabled.

## MachineConfig Discipline

MachineConfig changes can reboot nodes. On SNO, warn that API access can disappear until the single node returns. Apply one purpose per MachineConfig, wait for MCP recovery, then verify host state:

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
