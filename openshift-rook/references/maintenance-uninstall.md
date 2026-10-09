# Maintenance And Uninstall

Use this runbook for node maintenance, OSD replacement, MachineConfig cleanup, operator uninstall, and cluster destruction.

## Node Maintenance

For SNO, treat node maintenance as an outage. Confirm backups and post-reboot checks; draining cannot preserve availability when there is only one node.

For multi-node:

```bash
oc adm cordon <node>
oc adm drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=<duration>
```

Perform maintenance. If the node has OSDs, Ceph will re-replicate data to remaining OSDs. Ensure the cluster has enough free capacity.

After maintenance, uncordon:

```bash
oc adm uncordon <node>
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
```

## OSD Replacement

See `references/cluster-expand-shrink.md` for detailed OSD replacement steps. Always verify cluster health before and after replacement.

## Operator Uninstall

### Ownership gate

Rook shares more with ODF than its name. ODF runs its own Rook and ceph-csi, so a cluster with ODF uses the same `ceph.rook.io`, `csi.ceph.io`, and `objectbucket.io` CRDs, has SCCs named `rook-ceph` and `rook-ceph-csi`, and has objects named `rook-ceph-*` (ClusterRoles `rook-ceph-metrics`, `rook-ceph-monitor`, `rook-ceph-monitor-mgr`, Role `rook-ceph-metrics`, PDB `rook-ceph-mon-pdb`, all labelled `olm.owner=ocs-operator...`). Deleting Rook's CRDs or SCCs by name on such a cluster takes ODF's `CephCluster` with them. **Classify before anything is deleted, and again immediately before every destructive step.**

`scripts/classify_ceph_ownership.sh` applies the rule from `SKILL.md`'s ownership gate, from the Rook side:

- **ODF present** — a `StorageCluster`; an ODF/OCS `Subscription` or CSV; a `CephCluster` in `openshift-storage`, owned by a `StorageCluster`, or named like ODF's; a `rook-ceph-operator` Deployment in `openshift-storage`; or a Ceph CSI driver, `drivers.csi.ceph.io` object, or PV of ODF (`openshift-storage.` prefix). Stop and hand off to the `openshift-odf` skill: this runbook must not delete the shared CRDs or SCCs.
- **Upstream Rook** — a `rook-ceph-operator` Deployment outside `openshift-storage` that OLM did not install (in any namespace: Rook watches all of them by default), and the non-ODF `CephCluster`s it runs.
- **Unknown** — an OLM-installed `rook-ceph-operator`; a non-ODF `CephCluster` with no such operator (renamed, OLM-installed, absent, or already deleted by an interrupted uninstall); a Ceph CSI driver, `drivers.csi.ceph.io` object, or PV whose driver carries neither this Rook's prefix nor ODF's. The script refuses to answer.

It is read-only, names the cluster it classified, prints the upstream Rook namespaces on stdout and its verdict on stderr, and exits 0 only for "upstream Rook only" or "no Rook or ODF". It exits nonzero when ODF is present, for an unknown owner, an unreachable cluster or unknown `--context`, any lookup error (only "the server doesn't have a resource type" for `CephCluster` reads as none; the ODF and Ceph CSI kinds are read only when the API serves them), or unusable output.

Run these blocks in **bash**, from the `openshift-rook` skill directory. They are functions that use `return`, not `exit`, so a refusal cannot close your shell. Paste each function whole, from its `name() {` line to its closing `}`: a body pasted without its wrapper runs line by line, unguarded. Every function below that changes something calls `rook_classify` itself, through `rook_only` or `rook_gone`, immediately before acting and continues only when the classification succeeded with the verdict that step needs, so the verdict is always for the cluster and context you are logged in to now — never a leftover from an earlier `oc login`. Set the namespace, the driver prefix if the operator sets `CSI_DRIVER_NAME_PREFIX` (Rook's default prefix is the operator namespace), and the Helm release if you installed with Helm:

```bash
. scripts/rook_common.sh
: "${ODF_PACKAGES:?run this from the openshift-rook skill directory}"
ROOK_NAMESPACE=rook-ceph     # the namespace this Rook runs in
ROOK_CSI_PREFIX=             # CSI_DRIVER_NAME_PREFIX if customised; empty means the namespace
ROOK_HELM_RELEASE=rook-ceph  # Helm release of the operator chart; empty for a manifest install

# Every function checks the namespace it is about to act on: a DNS label, never ODF's.
rook_need_namespace() {
  if ! [[ ${ROOK_NAMESPACE:-} =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || [ "$ROOK_NAMESPACE" = openshift-storage ]; then
    echo "ROOK_NAMESPACE='${ROOK_NAMESPACE:-}' is not a Rook namespace (empty, not a DNS label, or ODF's openshift-storage)" >&2
    return 1
  fi
}

rook_classify() {
  ROOK_OWNERSHIP_CLASSIFIED=""
  ROOK_NAMESPACES=""
  local namespaces
  rook_need_namespace || return 1
  if ! namespaces=$(bash scripts/classify_ceph_ownership.sh --namespace "$ROOK_NAMESPACE" \
      --csi-prefix "${ROOK_CSI_PREFIX:-$ROOK_NAMESPACE}"); then
    echo "ODF present or ownership unknown - stop; this runbook deletes nothing (ODF: use openshift-odf)" >&2
    return 1
  fi
  ROOK_NAMESPACES="$namespaces"
  ROOK_OWNERSHIP_CLASSIFIED=yes
}

# A fresh "upstream Rook only" verdict naming exactly ROOK_NAMESPACE: the steps that
# act on a running Rook. A second Rook namespace shares cluster-scoped names with it.
rook_only() {
  if ! rook_classify || [ "${ROOK_OWNERSHIP_CLASSIFIED:-}" != yes ]; then
    return 1
  fi
  if [ "$ROOK_NAMESPACES" != "$ROOK_NAMESPACE" ]; then
    echo "expected upstream Rook in exactly $ROOK_NAMESPACE, found: ${ROOK_NAMESPACES:-none} - nothing changed" >&2
    return 1
  fi
}

# A fresh "no Rook or ODF" verdict: the steps that remove what nothing may still use.
rook_gone() {
  if ! rook_classify || [ "${ROOK_OWNERSHIP_CLASSIFIED:-}" != yes ]; then
    return 1
  fi
  if [ -n "$ROOK_NAMESPACES" ]; then
    echo "upstream Rook still runs in: $ROOK_NAMESPACES - nothing changed" >&2
    return 1
  fi
}
rook_classify
# stderr, for example:
#   classifying https://api.cluster.example.com:6443
#   upstream Rook in rook-ceph: CephCluster: rook-ceph
#   verdict: upstream Rook only, in: rook-ceph
# or "verdict: no Rook or ODF", or
#   verdict: ODF present (...) - hand off to openshift-odf; do not delete shared CRDs or SCCs
#   verdict: unknown - <reason> - do not delete anything shared with ODF
```

Continue with the uninstall only when `rook_classify` returned 0. In an interactive paste the `:?` guard only aborts its own line. The functions do not rely on it: each one starts with `rook_need_namespace` (directly or through `rook_classify`) and returns nonzero, before running any `oc` command, when `ROOK_NAMESPACE` is empty, not a DNS label, or `openshift-storage`.

Known limitation: an upstream Rook installed **inside** `openshift-storage` is classified as ODF. If that applies, stop and decide by hand.

### Helm Uninstall

`helm uninstall` deletes every object of the release, CRDs included, unless the object carries `helm.sh/resource-policy: keep`. This function needs a fresh "upstream Rook only, in: `$ROOK_NAMESPACE`" verdict, refuses while any `ceph.rook.io` object is left in `$ROOK_NAMESPACE` (removing the operator would orphan the `CephCluster`; run `rook_delete_ceph_crs` first), checks that the release exists there, and refuses when any `CustomResourceDefinition` in the release manifest is not kept: CRDs are removed only by `rook_delete_crds`. Without a YAML parser the keep test is strict: the CRD's `metadata:` block must hold an `annotations:` block with the exact line `helm.sh/resource-policy: keep`, indented the way Helm renders it (two spaces for `annotations:`, four for the entry); any other form counts as not kept.

```bash
rook_helm_uninstall() {
  local release="${ROOK_HELM_RELEASE:-}" manifest line kinds kind out left="" crd=0 keep=0 section="" blocked=0 json unkept name="" crd_names=""
  if [ -z "$release" ]; then
    echo "set ROOK_HELM_RELEASE to the operator chart release" >&2
    return 1
  fi
  rook_only || { echo "Helm release not uninstalled" >&2; return 1; }
  kinds=$(oc api-resources --api-group=ceph.rook.io --namespaced=true --verbs=list -o name) || return 1
  for kind in $kinds; do
    out=$(oc -n "$ROOK_NAMESPACE" get "$kind" -o name) || return 1
    [ -z "$out" ] || left="$left ${out//$'\n'/ }"
  done
  if [ -n "$left" ]; then
    echo "Ceph objects still in $ROOK_NAMESPACE:$left - run rook_delete_ceph_crs first; Helm release not uninstalled" >&2
    return 1
  fi
  manifest=$(helm get manifest "$release" -n "$ROOK_NAMESPACE") || {
    echo "no Helm release $release in $ROOK_NAMESPACE" >&2; return 1; }
  # One YAML document at a time; the trailing "---" closes the last one. A CRD is
  # kept only by the exact metadata.annotations line Helm renders.
  while IFS= read -r line; do
    if [ "$line" = "---" ]; then
      if [ "$crd" -eq 1 ] && [ "$keep" -eq 0 ]; then
        echo "release $release would delete a CRD without metadata.annotations helm.sh/resource-policy: keep" >&2
        blocked=1
      elif [ "$crd" -eq 1 ] && [ -z "$name" ]; then
        echo "release $release has a CRD whose metadata.name cannot be read" >&2
        blocked=1
      elif [ "$crd" -eq 1 ]; then
        crd_names="$crd_names $name"
      fi
      crd=0; keep=0; section=""; name=""
      continue
    fi
    # Any kind line naming a CRD counts, quoted or nested (a List of CRDs): over-
    # matching only refuses, under-matching would delete.
    if [[ $line == *kind:*CustomResourceDefinition* ]]; then
      crd=1
    fi
    case "$line" in
      "metadata:") section=metadata ;;
      "  annotations:") if [ "$section" = metadata ]; then section=annotations; fi ;;
      "    helm.sh/resource-policy: keep") if [ "$section" = annotations ]; then keep=1; fi ;;
      "    "*) ;;
      "  "*) if [ "$section" = annotations ]; then section=metadata; fi ;;
      *) section="" ;;
    esac
    if [ "$section" = metadata ] && [[ $line == "  name: "* ]]; then
      name=${line#  name: }
      name=${name//[\"\']/}
    fi
  done <<<"$manifest"$'\n---'
  # The line scan cannot tell a real annotation from the same text inside a
  # multi-line annotation value; the live CRDs can. Check every CRD the manifest
  # names, and every live CRD that carries this release's ownership annotations.
  json=$(oc get crd -o json) || return 1
  # shellcheck disable=SC2016 # jq variables
  unkept=$(jq -r --arg rel "$release" --arg ns "$ROOK_NAMESPACE" --arg names "$crd_names" '
    ($names | split(" ") | map(select(. != ""))) as $listed
    | .items[]
    | (.metadata.annotations // {}) as $a
    | select(.metadata.name as $n | any($listed[]; . == $n)
        or ($a["meta.helm.sh/release-name"] == $rel and $a["meta.helm.sh/release-namespace"] == $ns))
    | select($a["helm.sh/resource-policy"] != "keep") | .metadata.name' <<<"$json") || return 1
  if [ -n "$unkept" ]; then
    echo "live CRDs of release $release lack metadata.annotations helm.sh/resource-policy: keep: ${unkept//$'\n'/ }" >&2
    blocked=1
  fi
  if [ "$blocked" -ne 0 ]; then
    echo "Helm release not uninstalled: leave CRDs to rook_delete_crds" >&2
    return 1
  fi
  helm uninstall "$release" -n "$ROOK_NAMESPACE"
}
rook_helm_uninstall
```

### Manifest Uninstall

Record `dataDirHostPath`, this cluster's mon IDs, and the namespace and server they were read from **before** the `CephCluster` is deleted; the wipe further down refuses without them:

```bash
rook_record_data_dir() {
  local json dir mons ids="" server
  ROOK_DATA_DIR=""
  ROOK_DATA_DIR_SERVER=""
  ROOK_DATA_DIR_NAMESPACE=""
  ROOK_MON_IDS=""
  rook_need_namespace || return 1
  json=$(oc -n "$ROOK_NAMESPACE" get cephclusters.ceph.rook.io -o json) || return 1
  dir=$(jq -r '[.items[] | .spec.dataDirHostPath // "/var/lib/rook"] | unique
    | if length == 1 then .[0] else error("expected exactly one CephCluster in the namespace") end' <<<"$json") || return 1
  mons=$(oc -n "$ROOK_NAMESPACE" get configmaps rook-ceph-mon-endpoints --ignore-not-found -o json) || return 1
  if [ -n "$mons" ]; then
    ids=$(jq -r '(.data.data // "") | split(",")[] | select(length > 0) | split("=")[0]' <<<"$mons") || return 1
  fi
  server=$(oc whoami --show-server) || return 1
  ROOK_DATA_DIR="$dir"
  ROOK_MON_IDS="${ids//$'\n'/ }"
  ROOK_DATA_DIR_SERVER="$server"
  ROOK_DATA_DIR_NAMESPACE="$ROOK_NAMESPACE"
  echo "dataDirHostPath: $ROOK_DATA_DIR (mons: ${ROOK_MON_IDS:-none recorded}) for $ROOK_DATA_DIR_NAMESPACE on $ROOK_DATA_DIR_SERVER"
}
rook_record_data_dir
```

Delete the Rook Ceph resources in reverse order. The deletes use `--wait=false`: after an interrupted uninstall no controller removes the finalizers, and a waiting delete would block forever. The function then polls (at most `ROOK_DELETE_TIMEOUT` seconds, default 600) until each kind is gone, and stops at the first kind that stays:

```bash
# rook_wait_gone <namespace> <kind>...: poll until no instance of the kinds is left.
rook_wait_gone() {
  local ns="$1" kind out left deadline=$((SECONDS + ${ROOK_DELETE_TIMEOUT:-600}))
  shift
  while :; do
    left=""
    for kind in "$@"; do
      out=$(oc -n "$ns" get "$kind" -o name) || { echo "could not list $kind in $ns" >&2; return 1; }
      [ -z "$out" ] || left="$left ${out//$'\n'/ }"
    done
    [ -z "$left" ] && return 0
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "still present in $ns:$left - check the operator log; if the operator is gone, see Orphans After An Interrupted Uninstall" >&2
      return 1
    fi
    sleep 10
  done
}

rook_delete_ceph_crs() {
  rook_only || { echo "nothing deleted" >&2; return 1; }
  local ns="$ROOK_NAMESPACE" served kind
  served=$(oc api-resources --api-group=ceph.rook.io --verbs=list -o name) || return 1
  for kind in cephnfses.ceph.rook.io cephobjectstores.ceph.rook.io cephfilesystems.ceph.rook.io \
              cephblockpools.ceph.rook.io cephclusters.ceph.rook.io; do
    if [[ $'\n'$served$'\n' != *$'\n'$kind$'\n'* ]]; then
      echo "skipping $kind: its CRD is not installed" >&2
      continue
    fi
    oc -n "$ns" delete "$kind" --all --ignore-not-found --wait=false || return 1
    rook_wait_gone "$ns" "$kind" || return 1
  done
}
rook_delete_ceph_crs
```

Wait for the operator to clean up OSDs, mons, and mgrs (the poll above returns once the `CephCluster` is gone). Then remove the CSI custom resources **before** the CSI operator (otherwise their finalizers block the operator and namespace teardown), then the operators and the namespace.

**Never `oc delete -f` the install manifests.** The CRD manifest and `csi-operator.yaml` define CustomResourceDefinitions (without `csi-operator.yaml` a new `CephCluster` stalls on `no matches for kind "CephConnection"`), so deleting them by file removes the `csi.ceph.io` and `ceph.rook.io` CRDs cluster-wide, with every `Driver`, `CephConnection`, and `ClientProfile` of another Rook or a standalone ceph-csi-operator. `common.yaml` and `operator-openshift.yaml` carry cluster-scoped ClusterRoles, bindings, and the SCCs `rook-ceph`/`rook-ceph-csi`, whose names ODF and a second Rook share. This function deletes by kind, in `$ROOK_NAMESPACE` only, after a fresh "upstream Rook only, in: `$ROOK_NAMESPACE`" verdict, and refuses while a ValidatingWebhookConfiguration, MutatingWebhookConfiguration, or APIService is served from that namespace; cluster-scoped RBAC and SCCs are decided by **Cluster RBAC left by Rook** and `rook_remove_sccs`, and every CRD by `rook_delete_crds`:

```bash
rook_delete_operator() {
  rook_only || { echo "nothing deleted" >&2; return 1; }
  local ns="$ROOK_NAMESPACE" left kinds kind json served=""
  left=$(oc -n "$ns" get cephclusters.ceph.rook.io -o name) || return 1
  if [ -n "$left" ]; then
    echo "CephCluster still in $ns: $left - run rook_delete_ceph_crs first" >&2
    return 1
  fi
  # A webhook or APIService served from this namespace fails every request it
  # intercepts once the namespace is gone.
  for kind in validatingwebhookconfigurations mutatingwebhookconfigurations; do
    json=$(oc get "$kind" -o json) || return 1
    served="$served$(jq -r --arg ns "$ns" '.items[] | select(any(.webhooks[]?; .clientConfig.service.namespace == $ns))
      | " \(.kind)/\(.metadata.name)"' <<<"$json")" || return 1
  done
  json=$(oc get apiservices -o json) || return 1
  served="$served$(jq -r --arg ns "$ns" '.items[] | select(.spec.service.namespace == $ns)
    | " APIService/\(.metadata.name)"' <<<"$json")" || return 1
  if [ -n "$served" ]; then
    echo "served from $ns:${served//$'\n'/} - remove them first (after confirming they are this Rook's); nothing deleted" >&2
    return 1
  fi
  # ceph-csi CRs (drivers, operatorconfigs, cephconnections, clientprofiles.csi.ceph.io,
  # clientprofilemappings) first, so the csi-operator can finalize them.
  kinds=$(oc api-resources --api-group=csi.ceph.io --namespaced=true --verbs=list -o name) || return 1
  for kind in $kinds; do
    oc -n "$ns" delete "$kind" --all --ignore-not-found --wait=false || return 1
  done
  if [ -n "$kinds" ]; then
    # one argument per kind
    rook_wait_gone "$ns" $kinds || return 1
  fi
  # The operators and their namespaced RBAC, by kind, in this namespace only.
  for kind in deployments daemonsets serviceaccounts roles rolebindings; do
    oc -n "$ns" delete "$kind" --all --ignore-not-found --wait=false || return 1
  done
  oc delete namespace "$ns" --ignore-not-found --wait=false
}
rook_delete_operator
oc get namespace "$ROOK_NAMESPACE"   # repeat until NotFound; if it stays Terminating, see below
```

### Namespace Stuck Terminating And Orphaned Cluster-Scoped Objects

Namespace deletion can hang because a `csi.ceph.io` CR (for example `clientprofiles.csi.ceph.io/rook-ceph`) keeps finalizer `csi.ceph.com/cleanup` after the CSI operator Deployment is gone. That finalizer does not clear itself, so delete the `csi.ceph.io` objects while the CSI operator is still running (`rook_delete_operator` does). If it is already gone and the namespace is still stuck, clear finalizers on the **confirmed** blocking CRs, then leave the `clientprofiles.csi.ceph.io` CustomResourceDefinition to `rook_delete_crds` once it has no instances. This function does not use `rook_classify`, because an orphaned `CephCluster` or ceph-csi makes the classification "unknown" in exactly this state. It is bounded instead: it only touches objects in the Rook namespace that are already being deleted (`deletionTimestamp` set), refuses `openshift-storage` (ODF's), refuses while any Deployment, DaemonSet, or StatefulSet is left there, refuses while a `rook-ceph-operator` Deployment that is not being deleted exists in any namespace, and refuses while any `app=rook-ceph-operator` pod exists, terminating ones included (an operator that still runs, here or elsewhere, does the cleanup the finalizer guards; an external-mode `CephCluster` has no workloads in its own namespace). Pass `csi.ceph.io`, or `ceph.rook.io` if a `CephCluster` stays in `Deleting`; keep mounts and consumers removed before clearing any finalizer:

```bash
rook_clear_finalizers() {
  local group="${1:?usage: rook_clear_finalizers <csi.ceph.io|ceph.rook.io>}"
  local ns left kinds kind json items item
  case "$group" in
    csi.ceph.io|ceph.rook.io) ;;
    *) echo "unsupported group $group" >&2; return 1 ;;
  esac
  # refuses an empty namespace and ODF's openshift-storage
  rook_need_namespace || { echo "use the openshift-odf skill for openshift-storage" >&2; return 1; }
  ns="$ROOK_NAMESPACE"
  left=""
  for kind in deployments daemonsets statefulsets; do
    items=$(oc -n "$ns" get "$kind" -o name) || return 1
    [ -z "$items" ] || left="$left ${items//$'\n'/ }"
  done
  if [ -n "$left" ]; then
    echo "workloads still run in $ns:$left - remove the operators first; no finalizer cleared" >&2
    return 1
  fi
  json=$(oc get deployments -A --field-selector metadata.name=rook-ceph-operator -o json) || return 1
  left=$(jq -r '.items[] | select(.metadata.deletionTimestamp == null) | "\(.metadata.namespace)/\(.metadata.name)"' <<<"$json") || return 1
  if [ -n "$left" ]; then
    echo "a Rook operator still runs: ${left//$'\n'/ } - it owns these finalizers; no finalizer cleared" >&2
    return 1
  fi
  # A Deployment being deleted can still have running (or terminating) pods that
  # act on these objects; wait until no operator pod is left anywhere.
  left=$(oc get pods -A -l app=rook-ceph-operator -o name) || return 1
  if [ -n "$left" ]; then
    echo "rook-ceph-operator pods still exist: ${left//$'\n'/ } - wait until they are gone; no finalizer cleared" >&2
    return 1
  fi
  kinds=$(oc api-resources --api-group="$group" --namespaced=true --verbs=list -o name) || return 1
  for kind in $kinds; do
    json=$(oc -n "$ns" get "$kind" -o json) || return 1
    # Only objects already being deleted: stripping a live object's finalizer
    # would skip cleanup nobody asked to skip.
    items=$(jq -r --arg kind "$kind" '.items[] | select(.metadata.deletionTimestamp != null)
      | "\($kind)/\(.metadata.name)"' <<<"$json") || return 1
    for item in $items; do
      echo "clearing finalizers on $item in $ns"
      oc -n "$ns" patch "$item" --type=merge -p '{"metadata":{"finalizers":[]}}' || return 1
    done
  done
}
rook_clear_finalizers csi.ceph.io
```

Several objects are **cluster-scoped and survive the namespace deletion** — they must be removed by name or a later reinstall reuses stale definitions. Match them by provisioner or driver, never by name: a StorageClass named `rook-ceph-*` may use another provisioner, and a Rook class may carry any name. The driver prefix is `$ROOK_CSI_PREFIX` (default: the namespace), so a second Ceph cluster's `.csi.ceph.com` drivers and snapshot classes are never listed. This function is read-only:

```bash
rook_list_cluster_scoped() {
  rook_need_namespace || return 1
  local p="${ROOK_CSI_PREFIX:-$ROOK_NAMESPACE}" json kinds
  local rook_jq='def rook($p): . as $v
    | ([("rbd", "cephfs", "nfs", "nvmeof") | "\($p).\(.).csi.ceph.com"] + ["\($p).ceph.rook.io/bucket"])
    | any(.[]; . == $v);'
  json=$(oc get storageclasses -o json) || return 1
  jq -r --arg p "$p" "$rook_jq"' .items[] | select(.provisioner | rook($p))
    | "StorageClass \(.metadata.name) \(.provisioner)"' <<<"$json" || return 1
  json=$(oc get csidrivers -o json) || return 1
  jq -r --arg p "$p" "$rook_jq"' .items[] | select(.metadata.name | rook($p))
    | "CSIDriver \(.metadata.name)"' <<<"$json" || return 1
  kinds=$(oc api-resources --api-group=snapshot.storage.k8s.io --verbs=list -o name) || return 1
  if [[ $'\n'$kinds$'\n' == *$'\n'volumesnapshotclasses.snapshot.storage.k8s.io$'\n'* ]]; then
    json=$(oc get volumesnapshotclasses.snapshot.storage.k8s.io -o json) || return 1
    jq -r --arg p "$p" "$rook_jq"' .items[] | select(.driver | rook($p))
      | "VolumeSnapshotClass \(.metadata.name) \(.driver)"' <<<"$json" || return 1
  fi
}
rook_list_cluster_scoped
# Confirm no PV, PVC, or snapshot still depends on them, then delete each listed name:
oc delete sc <listed-storageclass> --ignore-not-found
oc delete csidriver <listed-csidriver> --ignore-not-found
oc delete volumesnapshotclass <listed-snapshotclass> --ignore-not-found
```

After the namespace is gone, clear this cluster's mon and cluster state under `dataDirHostPath` on every storage node so a reinstall starts clean (a leftover mon store crashes the new mon). The path, the mon IDs, and the server are the ones `rook_record_data_dir` read from **this** cluster's `CephCluster` (do not assume `/var/lib/rook`).

**The same path may belong to another Ceph.** ODF also keeps its state under `/var/lib/rook` by default (its cluster directory is `/var/lib/rook/openshift-storage`), and a second Rook cluster may use the same directory on the same node. So the wipe removes only `<dataDirHostPath>/<namespace>` and `<dataDirHostPath>/mon-<id>` for the recorded mon IDs, never every child. It refuses:

- a path that is not plain and absolute, has fewer than two components, contains `.` or `..` components, or is a system directory (`/bin /boot /dev /etc /home /lib /lib64 /opt /proc /root /run /sbin /srv /sys /tmp /usr /var /var/lib /var/log`);
- a path whose last component does not contain `rook`, unless you set `ROOK_DATA_DIR_ANY_NAME=yes` after checking the `CephCluster` spec;
- when the cluster you are logged in to, or `ROOK_NAMESPACE`, is not the one the path was recorded for (it warns when no mon IDs were recorded);
- unless a fresh classification says "no Rook or ODF": that verdict means no `CephCluster` of any owner and no `StorageCluster` exists, because a `CephCluster` without an operator is unknown, one with an operator is upstream Rook, and any ODF signal is "ODF present".

```bash
rook_wipe_data_dir() {
  local node="${1:-}" dir="${ROOK_DATA_DIR:-}" server id targets
  if [ -z "$node" ]; then
    echo "usage: rook_wipe_data_dir <node>" >&2
    return 1
  fi
  rook_need_namespace || return 1
  if ! [[ $dir =~ ^/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$ ]] || [[ /$dir/ == */./* || /$dir/ == */../* ]]; then
    echo "ROOK_DATA_DIR='$dir' is not a plain absolute path of two or more components - run rook_record_data_dir before deleting the CephCluster" >&2
    return 1
  fi
  case "$dir" in
    /bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var|/var/lib|/var/log)
      echo "ROOK_DATA_DIR=$dir is a system directory - nothing wiped" >&2
      return 1 ;;
  esac
  if [[ ${dir##*/} != *rook* ]] && [ "${ROOK_DATA_DIR_ANY_NAME:-}" != yes ]; then
    echo "ROOK_DATA_DIR=$dir does not name rook - set ROOK_DATA_DIR_ANY_NAME=yes only after checking the CephCluster spec" >&2
    return 1
  fi
  server=$(oc whoami --show-server) || return 1
  if [ -z "${ROOK_DATA_DIR_SERVER:-}" ] || [ "$server" != "$ROOK_DATA_DIR_SERVER" ]; then
    echo "ROOK_DATA_DIR was recorded on '${ROOK_DATA_DIR_SERVER:-}', you are logged in to $server - nothing wiped" >&2
    return 1
  fi
  if [ "${ROOK_DATA_DIR_NAMESPACE:-}" != "$ROOK_NAMESPACE" ]; then
    echo "ROOK_DATA_DIR was recorded for namespace '${ROOK_DATA_DIR_NAMESPACE:-}', not $ROOK_NAMESPACE - nothing wiped" >&2
    return 1
  fi
  rook_gone || { echo "another Ceph may use $dir - nothing wiped" >&2; return 1; }
  if [ -z "${ROOK_MON_IDS:-}" ]; then
    echo "warning: no mon IDs were recorded - only $dir/$ROOK_NAMESPACE is removed; check $dir/mon-* by hand" >&2
  fi
  targets="'$dir/$ROOK_NAMESPACE'"
  for id in ${ROOK_MON_IDS:-}; do
    if ! [[ $id =~ ^[a-z0-9]+$ ]]; then
      echo "invalid mon id '$id' - nothing wiped" >&2
      return 1
    fi
    targets="$targets '$dir/mon-$id'"
  done
  oc debug "node/$node" -- chroot /host bash -c "rm -rf -- $targets; ls -la '$dir'/"
}
rook_wipe_data_dir <node>
```

### Stale krbd Devices

Before removing the Ceph pools or a consumer namespace, make sure every RBD-backed PVC is unmounted and **unmapped**. If an RBD image is deleted (or its pool is destroyed) while a `/dev/rbdN` mapping is still open on a node, that mapping is orphaned against a cluster that no longer exists. A later Rook OSD prepare then hangs indefinitely at `ceph-volume raw list` (it probes the dead `/dev/rbdN`), and the device cannot be removed from userspace — `/sys/bus/rbd/remove*` blocks uninterruptibly and can wedge a node shutdown. Drain consumers first (delete app PVCs with `--wait=true` so CSI unmaps them), then check each node:

```bash
oc debug node/<node> -- chroot /host bash -c '
  ls /dev/rbd[0-9]* 2>/dev/null || echo "no /dev/rbd[0-9]* devices"
  for r in /sys/bus/rbd/devices/*; do [ -e "$r" ] && echo "rbd $(basename $r): pool=$(cat $r/pool 2>/dev/null) image=$(cat $r/name 2>/dev/null)"; done
'
```

Unmap a leftover from the affected node. `rbd device unmap --force` is a local kernel operation that does not need the pool, but it **waits for in-flight I/O**, so a fully wedged mapping can block — wrap it in `timeout`. If that times out, **do not wait on `/sys/bus/rbd/remove*`**: a write into those sysfs nodes can enter uninterruptible sleep (D-state), where `timeout` cannot kill the waiter and an `oc debug` session stays blocked. Skip the sysfs wait and escalate. Run the bounded unmap node-local, using the RBD id from `/sys/bus/rbd/devices/`:

```bash
oc debug node/<node> -- chroot /host bash -c '
  ID="<rbd-id>"   # from /sys/bus/rbd/devices/
  timeout 30 rbd device unmap --force "/dev/rbd${ID}" && exit 0
  echo "unmap timed out or failed; skip sysfs remove* (can block in D-state) — escalate to reboot" >&2
  exit 1
'
```

After a successful unmap (or before reboot escalation), re-check both `/dev/rbd[0-9]*` and `/sys/bus/rbd/devices/*` before pool deletion or reinstall:

```bash
oc debug node/<node> -- chroot /host bash -c '
  ls /dev/rbd[0-9]* 2>/dev/null || echo "no /dev/rbd[0-9]* devices"
  ls /sys/bus/rbd/devices/* 2>/dev/null || echo "no /sys/bus/rbd/devices entries"
'
```

If either path is still populated, a **node reboot (or hypervisor power-cycle for a wedged VM) is the reliable fix** — krbd mappings do not persist across reboot. After a reboot, confirm `/dev/rbd[0-9]*` and `/sys/bus/rbd/devices/*` are both empty before reinstalling.

### CRD deletion

If the cluster was installed with the direct manifest path (crds.yaml was applied), delete the CRDs last. CRD deletion is irreversible and cascade-deletes every remaining custom resource **in every namespace**, including those of another Ceph product. Do not run `oc delete -f` on the CRD manifest: it removes the `ceph.rook.io` and `objectbucket.io` CRDs (and, with the CSI manifests, `csi.ceph.io`) whatever else still uses them. The function below re-classifies, refuses unless the verdict is "no Rook or ODF", lists every instance of the three groups in **all** namespaces (and the cluster-scoped ones), and refuses while any remains. A group can also belong to a product that has no instance right now — a community `noobaa-operator` (`objectbucket.io`), a standalone ceph-csi-operator without a `Driver` (`csi.ceph.io`) — so it also refuses when any CRD of the three groups carries OLM labels (`olm.managed`, `operators.coreos.com/*`), a Helm release annotation (`meta.helm.sh/release-name`) of a release other than `$ROOK_HELM_RELEASE`, or is listed as owned or required by any ClusterServiceVersion. Only then does it delete the CRDs of exactly those groups (by `spec.group`, never by a name suffix):

```bash
rook_delete_crds() {
  rook_gone || { echo "no CRD deleted" >&2; return 1; }
  local group kinds kind left remaining="" json csvs owners crds
  local -a names
  for group in ceph.rook.io csi.ceph.io objectbucket.io; do
    # Fail closed: a suppressed discovery error would read as "no kinds, no instances".
    kinds=$(oc api-resources --api-group="$group" --verbs=list -o name) || {
      echo "kind discovery failed for $group - no CRD deleted" >&2; return 1; }
    for kind in $kinds; do
      left=$(oc get "$kind" -A -o name) || { echo "could not list $kind - no CRD deleted" >&2; return 1; }
      [ -z "$left" ] || remaining="$remaining ${left//$'\n'/ }"
    done
  done
  if [ -n "$remaining" ]; then
    echo "instances remain:$remaining - delete them, or clear them (see Orphans After An Interrupted Uninstall); no CRD deleted" >&2
    return 1
  fi
  json=$(oc get crd -o json) || return 1
  csvs=$(oc get clusterserviceversions.operators.coreos.com -A -o json) || return 1
  owners=$(printf '%s\n' "$json" "$csvs" | jq -r -s --arg rel "${ROOK_HELM_RELEASE:-}" --arg ns "$ROOK_NAMESPACE" '
    [.[1].items[] | .spec.customresourcedefinitions // {} | (.owned // [])[], (.required // [])[] | .name] as $listed
    | .[0].items[]
    | select(.spec.group == "ceph.rook.io" or .spec.group == "csi.ceph.io" or .spec.group == "objectbucket.io")
    | .metadata.name as $crd | (.metadata.labels // {}) as $l | (.metadata.annotations // {}) as $a
    | ((if ($l | has("olm.managed")) or any($l | keys[]; startswith("operators.coreos.com/")) then "OLM labels" else empty end),
       (($a["meta.helm.sh/release-name"] // null) as $r | ($a["meta.helm.sh/release-namespace"] // null) as $rn
        | if ($r != null or $rn != null) and ($r != $rel or $rn != $ns)
          then "Helm release \($rn // "")/\($r // "")" else empty end),
       (if any($listed[]; . == $crd) then "listed by a ClusterServiceVersion" else empty end))
    | "\($crd): \(.)"') || return 1
  if [ -n "$owners" ]; then
    echo "another product manages these CRDs - no CRD deleted:" >&2
    echo "$owners" >&2
    return 1
  fi
  for group in ceph.rook.io csi.ceph.io objectbucket.io; do
    crds=$(jq -r --arg g "$group" '.items[] | select(.spec.group == $g) | .metadata.name' <<<"$json") || return 1
    [ -n "$crds" ] || continue
    mapfile -t names <<<"$crds"
    oc delete crd "${names[@]}" --wait=false || return 1
  done
}
rook_delete_crds
```

CRDs with the `customresourcecleanup.apiextensions.k8s.io` finalizer block until all CR instances are gone; the function only deletes CRDs with no instance left, so none should stay `Terminating`.

## Post-Uninstall Audit

After uninstall, confirm:

- No upstream Rook operator or `CephCluster` runs, and nothing Ceph-related is of unknown owner (the rule of `scripts/classify_ceph_ownership.sh`). When ODF is present it is reported, and its objects are not Rook residue.
- The Rook namespace is absent; while it exists (kept, or stuck deleting) its pods and Rook/Ceph/CSI-named objects are listed. No namespace has been `Terminating` for more than 10 minutes.
- Without ODF: the `ceph.rook.io`, `csi.ceph.io`, and `objectbucket.io` API groups are gone, and every instance still holding them is listed. With ODF: those groups are retained (ODF uses them) and only their instances in the Rook namespace (or cluster-scoped and named with the Rook driver prefix) are residue.
- No StorageClass uses a Rook provisioner (`<prefix>.rbd.csi.ceph.com`, `<prefix>.cephfs.csi.ceph.com`, `<prefix>.nfs.csi.ceph.com`, `<prefix>.nvmeof.csi.ceph.com`, `<prefix>.ceph.rook.io/bucket`; prefix `rook-ceph` unless `CSI_DRIVER_NAME_PREFIX` was set). No PV uses a Rook CSI driver (whatever its StorageClass is called), no PVC uses a Rook StorageClass or is bound to a Rook PV, and no PVC or PV has had a `deletionTimestamp` for more than 10 minutes.
- No VolumeSnapshotClass, CSIDriver, `VolumeAttachment` (by attacher), or node `CSINode` entry names a Rook driver, and no Pod anywhere has been deleting for more than 10 minutes.
- No ObjectBucketClaim or ObjectBucket whose StorageClass uses the Rook bucket provisioner (or is missing while no ODF runs; with ODF present a missing class is reported for review), and no ConfigMap or Secret held by `objectbucket.io/finalizer` without a live claim in the Rook namespace or a Terminating namespace.
- The `rook-ceph` and `rook-ceph-csi` SCCs are gone unless their users are ODF's service accounts; the PriorityClass `rook-ceph-default` is gone; no dead Rook ClusterRole or ClusterRoleBinding remains (see **Cluster RBAC left by Rook**). MachineConfigs named for Rook are listed for review.
- The default StorageClass matches what was recorded before uninstall. No default is a clean end state when the cluster had none.
- `rook-ceph-metrics` bound only to `openshift-monitoring/prometheus-k8s` is residue once both `rook-ceph` and `openshift-storage` are gone. Keep it while either namespace still runs Ceph. `prometheus-k8s` exists on every OpenShift cluster, so the ServiceAccount alone is not a reason to keep the role.

Run the post-uninstall audit script. Export `PRIOR_DEFAULT_STORAGE_CLASS` before uninstall and leave it set. Empty output means there was no default:

```bash
PRIOR_DEFAULT_STORAGE_CLASS="$(oc get sc -o jsonpath='{range .items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")]}{.metadata.name}{"\n"}{end}')"
export PRIOR_DEFAULT_STORAGE_CLASS
bash scripts/post_uninstall_audit.sh
# with a non-default namespace or driver prefix:
bash scripts/post_uninstall_audit.sh --namespace <rook-namespace> --csi-prefix <csi-driver-name-prefix>
```

It is read-only and needs only `oc`, `jq`, and bash; it names the cluster it audited and accepts `--context` and `--kubeconfig`. Any `WARN` or `FAIL` line exits nonzero, so it can gate a pipeline. `OK: ... retained: <reason>` lines name objects that look like Rook's but are not (ODF's SCCs, OLM-labelled `rook-ceph-*` RBAC, roles in use); they do not fail the audit. Objects are matched by driver, provisioner, StorageClass, and ownership, never by a `rook-ceph` name alone. "Terminating" for a PVC or PV is only how `oc get` prints it — the phase stays `Bound` or `Released` and the deletion shows as `metadata.deletionTimestamp`, which is what the audit tests. ConfigMaps and Secrets are read as names and finalizers only, never their data; a user who may not list Secrets gets a `FAIL: could not check ...` line naming the missing permission.

Equivalent manual checks:

```bash
PFX="rook-ceph"   # = CSI_DRIVER_NAME_PREFIX if customized
DRV="^${PFX}[.](rbd|cephfs|nfs|nvmeof)[.]csi[.]ceph[.]com$"
bash scripts/classify_ceph_ownership.sh --csi-prefix "$PFX"
oc get namespace rook-ceph 2>/dev/null || echo "namespace gone"
oc get ns -o json | jq -r '.items[] | select(.status.phase == "Terminating") | .metadata.name'
for group in ceph.rook.io csi.ceph.io objectbucket.io; do oc api-resources --api-group="$group" -o name; done
oc get sc -o json | jq -r --arg p "$PFX" '.items[] | select(.provisioner | startswith($p + ".")) | .metadata.name'
oc get pv -o json | jq -r --arg d "$DRV" '.items[] | select((.spec.csi.driver // "") | test($d)) | .metadata.name'
oc get pvc -A -o jsonpath='{range .items[?(@.metadata.deletionTimestamp)]}{.metadata.namespace}/{.metadata.name} {.status.phase}{"\n"}{end}'
oc get volumeattachment -o json | jq -r --arg d "$DRV" '.items[] | select(.spec.attacher | test($d)) | .metadata.name'
oc get csidriver -o name; oc get csinode -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.drivers[*].name}{"\n"}{end}'
oc get scc rook-ceph rook-ceph-csi -o jsonpath='{range .items[*]}{.metadata.name}: {.users}{"\n"}{end}' 2>/dev/null
oc get priorityclass rook-ceph-default 2>/dev/null || true
```

## Orphans After An Interrupted Uninstall

When the Rook operator and CSI driver are removed **before** the workloads and volumes that need them — an uninstall stopped halfway, the operator deleted first, or a namespace deleted with everything in it — the steps above leave objects that can never go away by themselves: every one of them waits for a controller or driver that no longer exists. The mechanisms are the ones seen with ODF 4.20.17 leftovers on an OCP 4.20.34 SNO cluster (LVMS sharing `openshift-storage`, an upstream non-OLM Rook v1.20.5 in `rook-ceph`), with Rook's driver names in place of ODF's. A reboot clears none of it. In this state `rook_classify` reports the orphaned `CephCluster` or Ceph CSI as **unknown** and every classified function refuses; that is by design — work through this section first, then run `rook_classify` again.

### Prove nothing stands behind a finalizer

Stripping a finalizer skips whatever cleanup it guards. Do it only after collecting all of this evidence, and stop if any of it fails:

```bash
PFX="rook-ceph"   # = CSI_DRIVER_NAME_PREFIX if customized
oc get csidriver -o name | grep -E "/${PFX}\.(rbd|cephfs|nfs|nvmeof)\.csi\.ceph\.com$"    # expect nothing
oc get csinode <node> -o jsonpath='{.spec.drivers[*].name}{"\n"}'  # no ${PFX}.* driver
oc get pv <pv> -o jsonpath='{.spec.csi.driver} {.spec.csi.volumeAttributes.clusterID}{"\n"}'
                                                                   # the removed driver, clusterID = the Rook namespace
oc get sc "$(oc get pv <pv> -o jsonpath='{.spec.storageClassName}')"
                                                                   # expect NotFound: the PV's own class is gone
oc -n rook-ceph get cephcluster 2>&1                               # no CephCluster (or no such type)
oc get deployments -A --field-selector metadata.name=rook-ceph-operator  # no Rook operator anywhere
bash scripts/classify_ceph_ownership.sh --csi-prefix "$PFX"        # no "ODF:" line: no other Ceph product owns them
```

A driver of another product is never this Rook's: ODF's is `openshift-storage.rbd.csi.ceph.com`, a second Rook's carries its own prefix. If a PV names a driver that is still registered, it is not an orphan.

### Order of removal

Work in this order — each step releases the next, and the reverse creates new stuck objects:

1. The Pod the kubelet cannot release.
2. Its PVC, which releases itself once the Pod is gone (held only by `kubernetes.io/pvc-protection`).
3. `VolumeAttachment`s of the removed driver.
4. PVs of the removed driver.
5. Finalizers in consumer namespaces stuck `Terminating` (bucket claims and their ConfigMaps/Secrets).
6. Cluster-scoped `ObjectBucket`s.
7. Cluster RBAC (**Cluster RBAC left by Rook** below), then the CRDs (`rook_delete_crds`).

### Pod the kubelet holds after its CSI driver is gone

Recognise it: a Pod with `deletionTimestamp` set, often phase `Failed` with its container terminated, **no finalizers**, and an owner that is gone. Its PVC is `Bound` with an old `deletionTimestamp`, held only by `kubernetes.io/pvc-protection`. The kubelet journal repeats an `UnmountVolume` start followed by a failure naming `<prefix>.rbd.csi.ceph.com` as not registered, every couple of minutes. Without the driver the kubelet can never unmount, so it never lets the Pod object go.

```bash
oc get pods -A -o json | jq -r '.items[] | select(.metadata.deletionTimestamp)
  | "\(.metadata.namespace)/\(.metadata.name) \(.status.phase) \(.spec.nodeName) since \(.metadata.deletionTimestamp)"'
oc -n <ns> get pod <pod> -o jsonpath='{.metadata.uid}{"\n"}{.metadata.finalizers}{"\n"}{.metadata.ownerReferences}{"\n"}'
oc adm node-logs <node> -u kubelet --tail=500 | grep -E "UnmountVolume|${PFX}\.(rbd|cephfs|nfs|nvmeof)\.csi\.ceph\.com"
```

Fix: force-delete the Pod object, then **restart the kubelet on that node**:

```bash
oc -n <ns> delete pod <pod> --grace-period=0 --force
# The debug session runs through the kubelet and may drop when it restarts; that is expected.
# SSH to the node and `sudo systemctl restart kubelet` works too.
oc debug node/<node> -- chroot /host systemctl restart kubelet
```

What the restart does: running containers keep running, including the static API server pod, so the API stays up; the node reports `NotReady` for a short while until the kubelet posts status again, and the `oc debug` session drops because it runs through the kubelet. On SNO, expect that brief `NotReady` and nothing more. Afterwards the kubelet journal must show no further lines for that volume, the kubelet removes `/var/lib/kubelet/pods/<uid>` itself, and the held PVC is gone:

```bash
oc adm node-logs <node> -u kubelet --tail=500 | grep -E "UnmountVolume|${PFX}\.(rbd|cephfs|nfs|nvmeof)\.csi\.ceph\.com" || echo "quiet"
oc debug node/<node> -- chroot /host ls /var/lib/kubelet/pods/<uid> 2>&1   # expect: No such file or directory
oc -n <ns> get pvc
```

> **Warning — never delete the volume directory under a running kubelet.** Removing `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~csi/<pv>` by hand looks safe when it holds only `vol_data.json`, nothing is mounted, and no rbd device is mapped. It is not: the kubelet still holds the volume in memory, can no longer even build an unmounter (`UnmountVolume.NewUnmounter failed`), and retries without backoff — about 590 log lines a minute instead of one retry every two minutes — until the kubelet is restarted. Restart the kubelet instead; it cleans the directory itself.

### VolumeAttachments of the removed driver

Recognise it: `spec.attacher` is `<prefix>.rbd.csi.ceph.com` (or `.cephfs.`), often still `status.attached=true`, held by `external-attacher/<prefix>-rbd-csi-ceph-com` (the prefix with its dots as dashes). No attacher remains to honour that finalizer.

```bash
oc get volumeattachment -o custom-columns=NAME:.metadata.name,ATTACHER:.spec.attacher,PV:.spec.source.persistentVolumeName,ATTACHED:.status.attached,FINALIZERS:.metadata.finalizers
oc delete volumeattachment <name> --wait=false
oc patch volumeattachment <name> --type merge -p '{"metadata":{"finalizers":null}}'
```

### PVs of the removed driver

Recognise it: `spec.csi.driver` is the removed driver, `volumeAttributes.clusterID` is the Rook namespace, the StorageClass no longer exists, phase `Bound` or `Released`, reclaim `Delete`, and finalizers `external-provisioner.volume.kubernetes.io/finalizer`, `kubernetes.io/pv-protection`, and `external-attacher/<prefix>-rbd-csi-ceph-com`. No provisioner or attacher remains, and the Ceph cluster behind the volume is gone, so there is nothing for reclaim to delete. A `Bound` PV must have lost its claim first (the Pod fix above), or the claim must be one you are removing on purpose. Select by driver, never by StorageClass name: a custom class name hides a Rook PV from a name match.

```bash
oc get pv -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,DRIVER:.spec.csi.driver,CLUSTERID:.spec.csi.volumeAttributes.clusterID,SC:.spec.storageClassName,CLAIM:.spec.claimRef.name,FINALIZERS:.metadata.finalizers
oc delete pv <pv> --wait=false
oc patch pv <pv> --type merge -p '{"metadata":{"finalizers":null}}'
```

### Consumer namespace stuck Terminating on bucket claims

Recognise it: an application namespace `Terminating` for a long time that still holds `ObjectBucketClaim`s **and**, for each claim, a ConfigMap and a Secret of the same name — every one with a `deletionTimestamp` and the single finalizer `objectbucket.io/finalizer` (six objects for two claims). Their StorageClass is gone or uses `<prefix>.ceph.rook.io/bucket`, and no bucket provisioner runs. Claims whose class uses an ODF provisioner (`openshift-storage.noobaa.io/obc`, `openshift-storage.ceph.rook.io/bucket`) are ODF's: leave them to the `openshift-odf` skill.

```bash
oc get ns | grep Terminating
oc -n <ns> get obc -o custom-columns=NAME:.metadata.name,SC:.spec.storageClassName,DELETING:.metadata.deletionTimestamp,FINALIZERS:.metadata.finalizers
oc -n <ns> get configmap,secret -o custom-columns=KIND:.kind,NAME:.metadata.name,FINALIZERS:.metadata.finalizers | grep objectbucket.io/finalizer
oc get sc <class>                                                       # expect NotFound or a ${PFX}.ceph.rook.io/bucket provisioner

for kind in obc configmap secret; do
  oc -n <ns> patch "$kind" <claim-name> --type merge -p '{"metadata":{"finalizers":null}}'
done
oc get ns <ns>   # finishes within seconds once the last finalizer is gone
```

### ObjectBuckets

The cluster-scoped `ObjectBucket`s behind those claims (`Released` or still `Bound`) stay after the namespace is gone. Apply the same StorageClass test, then:

```bash
oc get objectbucket -o custom-columns=NAME:.metadata.name,SC:.spec.storageClassName,PHASE:.status.phase,CLAIM:.spec.claimRef.name
oc delete objectbucket <name> --wait=false
oc patch objectbucket <name> --type merge -p '{"metadata":{"finalizers":null}}'
```

### csi.ceph.io and ceph.rook.io CRs with operator finalizers

`drivers`, `operatorconfigs`, `cephconnections`, `clientprofiles`, and `clientprofilemappings` in `csi.ceph.io`, and a `CephCluster` or pool in `ceph.rook.io`, keep their operator finalizers once the operators are gone and hold the Rook namespace in `Terminating`. Clear them with `rook_clear_finalizers` (above), after the proofs in this section.

### Cluster RBAC left by Rook

Rook's manifests create ClusterRoles and ClusterRoleBindings (`rook-ceph-*`, `rbd-csi-*`, `rbd-external-provisioner-*`, `cephfs-csi-*`, `cephfs-external-provisioner-*`, `ceph-csi-*`, `objectstorage-provisioner-*`) that `oc delete -f` normally removes, but that outlive an interrupted uninstall.

**A name is not ownership, and a label is provenance, not proof of use.** ODF creates objects named `rook-ceph-*` too (ClusterRoles `rook-ceph-metrics`, `rook-ceph-monitor`, `rook-ceph-monitor-mgr`, Role `rook-ceph-metrics`, PDB `rook-ceph-mon-pdb`, labelled `olm.owner=ocs-operator...`). Upstream Rook is not installed by OLM, so an object carrying `olm.owner` or `operators.coreos.com/*` labels is not Rook residue: while that operator is installed it is in use; when it is gone it is that operator's leftover (for ODF, the `openshift-odf` skill's). Objects named `rook-ceph-*` that are bound to live subjects are not residue either.

Decide each remaining one by liveness:

- **A ClusterRoleBinding is dead** only if its ClusterRole is missing, or none of its ServiceAccount subjects exists. A missing role makes the binding dead even with `User` or `Group` subjects; otherwise a `User` or `Group` subject cannot be proven absent — keep that binding.
- **A ClusterRole is dead** only if no live ClusterRoleBinding or RoleBinding anywhere references it and it does not aggregate into another role. A binding you have just judged dead does not keep its role alive. Evaluate each `clusterRoleSelectors` entry in full: every `matchLabels` pair and every `matchExpressions` term (`In`, `NotIn` — also true when the key is absent —, `Exists`, `DoesNotExist`) must hold; an empty selector (`{}`) selects **every** ClusterRole, because Kubernetes reads a non-nil empty label selector as "everything"; if you cannot evaluate a selector (an unknown operator, a malformed term), keep the role.

```bash
# Labels first: anything OLM-labelled is not upstream Rook's.
oc get clusterrole,clusterrolebinding -o json | jq -r '.items[]
  | select(.metadata.name | test("^(rook-ceph|rbd-csi|rbd-external|cephfs-csi|cephfs-external|ceph-csi|objectstorage-provisioner)"))
  | "\(.kind)/\(.metadata.name) \(.metadata.labels // {} | with_entries(select(.key == "olm.owner" or (.key | startswith("operators.coreos.com/")))))"'

# Binding: its role and subjects, then check each ServiceAccount exists.
oc get clusterrolebinding <name> -o jsonpath='{.roleRef.name}{"\n"}{range .subjects[*]}{.kind} {.namespace}/{.name}{"\n"}{end}'
oc get clusterrole <role>
oc -n <subject-namespace> get serviceaccount <subject-name>

# Role: every binding that references it (judge each with the binding test above) ...
oc get clusterrolebinding,rolebinding -A -o json | jq -r --arg r <role> '.items[]
  | select(.roleRef.kind == "ClusterRole" and .roleRef.name == $r)
  | "\(.kind) \(.metadata.namespace // "-")/\(.metadata.name)"'
# ... and whether an aggregating role selects its labels.
oc get clusterrole <role> -o jsonpath='{.metadata.labels}{"\n"}'
oc get clusterrole -o json | jq -r '.items[] | select(.aggregationRule) | "\(.metadata.name) \(.aggregationRule.clusterRoleSelectors | tostring)"'

oc delete clusterrolebinding <dead-binding>
oc delete clusterrole <dead-role>
```

`post_uninstall_audit.sh` applies the same tests to Rook-named ClusterRoles and ClusterRoleBindings and to bindings with a ServiceAccount subject in the Rook namespace: dead ones `WARN`, in-use or OLM-labelled ones print `OK: ...`.

## Cluster Destruction (Data Loss)

Destroying the Ceph cluster destroys all data. Require explicit destructive confirmation before proceeding, and pass the **Ownership gate** first: with ODF on the same nodes, Rook's cleanup and a manual wipe of the shared `dataDirHostPath` would reach ODF's mon stores.

### Option A: Rook-native cleanup (recommended)

Set `cleanupPolicy` on the CephCluster **before** deleting it. With the required
confirmation string, Rook runs a job that zaps each OSD disk and removes
`dataDirHostPath` automatically, so you do not have to wipe disks by hand. This
is irreversible — only apply it when you intend to erase all data. The function
needs `ROOK_CONFIRM_DESTROY_DATA=yes-really-destroy-data` and a fresh "upstream Rook
only, in: `$ROOK_NAMESPACE`" verdict, and patches only the `CephCluster`s there:

```bash
rook_set_cleanup_policy() {
  local names name
  if [ "${ROOK_CONFIRM_DESTROY_DATA:-}" != yes-really-destroy-data ]; then
    echo "set ROOK_CONFIRM_DESTROY_DATA=yes-really-destroy-data to erase every OSD disk and dataDirHostPath of the CephCluster in ${ROOK_NAMESPACE:-?}" >&2
    return 1
  fi
  rook_only || { echo "cleanupPolicy not set" >&2; return 1; }
  names=$(oc -n "$ROOK_NAMESPACE" get cephclusters.ceph.rook.io -o name) || return 1
  if [ -z "$names" ]; then
    echo "no CephCluster in $ROOK_NAMESPACE" >&2
    return 1
  fi
  for name in $names; do
    oc -n "$ROOK_NAMESPACE" patch "$name" --type=merge \
      -p '{"spec":{"cleanupPolicy":{"confirmation":"yes-really-destroy-data"}}}' || return 1
  done
}
rook_set_cleanup_policy
```

Then delete the CephCluster (the operator runs the cleanup job) and continue with
the operator uninstall steps above. Watch the cleanup jobs complete before
deleting the namespace:

```bash
rook_delete_ceph_crs
oc -n "$ROOK_NAMESPACE" get pods -l app=rook-ceph-cleanup
```

### Option B: Manual disk cleanup

If `cleanupPolicy` was not used (or you need to reclaim disks after the fact):

1. Follow the operator uninstall steps above.
2. After the namespace is removed, collect the `readlink -f`, `lsblk -f`, `wipefs -n`, and `ceph-volume lvm list` evidence for the disk (`references/osd-disk-prep.md`), then clean it. Nothing else on the node may be using or claiming the disk while you do: no one formatting it, mounting it, or adding it to LVM. The function takes only a stable `/dev/disk/by-id/` path of a whole disk (never a `-part<N>` link), needs `ROOK_CONFIRM_WIPE_DISK` set to exactly that path, and refuses unless a fresh classification says "no Rook or ODF". It then runs **one** script on the node that checks the disk and wipes it right after the last check, only if every check passed; that narrows the window between check and wipe but does not lock the disk. A check that cannot run (a failed `readlink`, `lsblk`, holders listing, `wipefs` probe, `findmnt`, `swapon`, `pvs`, or `sfdisk`, `blkid -p` with any status but 0 or 2, or no `pvs` at all) blocks the wipe: unknown is never read as unused. The disk must resolve to a device of type `disk` with no partitions or child devices, no holders, no mount in the host's mount table, no active swap, and no `pvs` entry. The only signatures `wipefs` and `blkid -p` may find on it are `ceph_bluestore` and a partition table (`gpt`, `PMBR`, `dos`) whose on-disk entries (`sfdisk -d`) list no partition, whatever the kernel shows; `xfs`, `ext4`, `LVM2_member`, `crypto_LUKS`, `swap`, or any other signature blocks it. On a node shared with LVMS, that is what keeps the boot disk and LVMS volume-group disks safe. The wipe runs on the resolved device, not on the link. If it fails after it started, the function says the disk may be partly wiped instead of "disk not wiped":

```bash
rook_wipe_osd_disk() {
  local node="${1:-}" disk="${2:-}" out
  if [ -z "$node" ] || [ -z "$disk" ]; then
    echo "usage: rook_wipe_osd_disk <node> /dev/disk/by-id/<stable-disk-id>" >&2
    return 1
  fi
  if ! [[ $disk =~ ^/dev/disk/by-id/[A-Za-z0-9._:+-]+$ ]]; then
    echo "$disk is not a /dev/disk/by-id/ path - never use /dev/sdX or /dev/nvmeXnY" >&2
    return 1
  fi
  if [ "${ROOK_CONFIRM_WIPE_DISK:-}" != "$disk" ]; then
    echo "set ROOK_CONFIRM_WIPE_DISK=$disk to confirm erasing exactly that disk on $node" >&2
    return 1
  fi
  if [[ $disk =~ -part[0-9]+$ ]]; then
    echo "$disk is a partition link - give the whole disk" >&2
    return 1
  fi
  rook_gone || { echo "disk not wiped" >&2; return 1; }
  # Check and wipe in one node-side run, so the wipe follows the last check
  # directly. set -e stops at the first check that cannot run: a failed probe
  # never reads as "not in use". "wiping" marks the start of the writes.
  # shellcheck disable=SC2016 # expands on the node
  out=$(oc debug "node/$node" -- chroot /host bash -c '
set -euo pipefail
set -f
trap "echo \"blocked: a check could not run: \$BASH_COMMAND\"" ERR
nl=$(printf "\nx")
nl=${nl%x}
link=$1
d=$(readlink -f "$link")
[[ $d == /dev/?* ]] || { echo "blocked: $link does not resolve to a device"; exit 3; }
type=$(lsblk -dno TYPE "$d")
majmin=$(lsblk -dno MAJ:MIN "$d")
majmin=${majmin// /}
names=$(lsblk -nro NAME "$d")
holders=$(ls -A "/sys/class/block/${d##*/}/holders")
sigs=$(wipefs --noheadings -O TYPE "$d")
# A second, independent probe: blkid -p exits 2 when it finds nothing, and any
# status but 0 or 2 is a failed probe, never an empty disk.
if probe=$(blkid -p -o export "$d"); then rc=0; else rc=$?; fi
case "$rc" in
  0|2) ;;
  *) echo "blocked: blkid -p failed with status $rc"; exit 3 ;;
esac
for kv in $probe; do
  case "$kv" in
    TYPE=*|PTTYPE=*) sigs="$sigs$nl${kv#*=}" ;;
  esac
done
mounts=$(findmnt -N 1 -rno MAJ:MIN)
swaps=$(swapon --show=NAME --noheadings --raw)
command -v pvs >/dev/null || { echo "blocked: pvs is not available, so LVM use cannot be ruled out"; exit 3; }
pvlist=$(pvs --noheadings -o pv_name)
echo "device $d: type ${type:-unknown}, signatures: ${sigs//$nl/ }"
blocked=""
table=""
[ "$type" = disk ] || blocked="$blocked; type ${type:-unknown}, not a whole disk"
if [[ $names == *$nl* ]]; then
  children=${names#*$nl}
  blocked="$blocked; partitions or child devices: ${children//$nl/ }"
fi
[ -z "$holders" ] || blocked="$blocked; holders: ${holders//$nl/ }"
for m in $mounts; do
  [ "$m" != "$majmin" ] || blocked="$blocked; mounted on the host"
done
for s in $swaps; do
  [ "$s" != "$d" ] || blocked="$blocked; active swap"
done
for p in $pvlist; do
  if [ "$p" = "$d" ] || [ "$p" = "$link" ]; then blocked="$blocked; LVM physical volume $p"; fi
done
for s in $sigs; do
  case "$s" in
    ceph_bluestore) ;;
    gpt|PMBR|dos) table=yes ;;
    *) blocked="$blocked; signature $s" ;;
  esac
done
# A partition table counts as empty only if the on-disk table lists no
# partition, whatever the kernel currently shows as child devices.
if [ -n "$table" ]; then
  dump=$(sfdisk -d "$d")
  parts=""
  IFS=$nl
  for line in $dump; do
    case "$line" in
      /dev/*) parts="$parts ${line%% *}" ;;
    esac
  done
  unset IFS
  [ -z "$parts" ] || blocked="$blocked; on-disk partitions:$parts"
fi
if [ -n "$blocked" ]; then
  echo "blocked: ${blocked#; }"
  exit 3
fi
trap "echo \"wipe step failed: \$BASH_COMMAND\"" ERR
echo "wiping $d"
wipefs -af "$d"
sgdisk --zap-all "$d"
lsblk -f "$d"
' _ "$disk") || {
    printf '%s\n' "$out" >&2
    if [[ $out == *"wiping /dev/"* ]]; then
      echo "the wipe of $disk on $node started and then failed - the disk may be partly wiped; check it with lsblk -f and wipefs -n" >&2
    else
      echo "$disk on $node is in use or could not be checked - disk not wiped" >&2
    fi
    return 1
  }
  printf '%s\n' "$out"
}
rook_wipe_osd_disk <node> /dev/disk/by-id/<stable-disk-id>
```

3. Remove MachineConfigs created for Rook Ceph if any.
4. Remove node labels.

## MachineConfig Cleanup

MachineConfig cleanup can reboot nodes. On SNO, warn about temporary API loss. Find Rook Ceph-specific MachineConfigs before deciding what to remove (`post_uninstall_audit.sh` lists the ones named for Rook, but never judges them):

```bash
oc get machineconfig | grep -i rook || true
oc get machineconfig <name> -o yaml
```

After changes:

```bash
oc wait mcp/<pool> --for=condition=Updated=True --timeout=45m
oc get mcp <pool> -o wide
oc get nodes
```

If MCP is degraded, stop and inspect before proceeding.

## SCC Cleanup

Remove SCC grants when uninstalling Rook Ceph or after emergency repair work that granted additional privileges beyond the standard operator requirements:

```bash
oc adm policy remove-scc-from-user privileged -z rook-ceph-osd -n rook-ceph
oc adm policy remove-scc-from-user privileged -z rook-ceph-system -n rook-ceph
oc adm policy remove-scc-from-user privileged -z rook-ceph-mgr -n rook-ceph
```

List service accounts and SCC use if cleanup is uncertain:

```bash
oc get rolebindings,clusterrolebindings -A | grep -i rook || true
oc adm policy who-can use scc privileged
```

**Judge the `rook-ceph` and `rook-ceph-csi` SCCs by their `users`, not their names.** ODF 4.20 has SCCs with exactly those names for its own service accounts in `openshift-storage`. An SCC whose every user is a service account of the Rook namespace (and whose groups, if any, are that namespace's service-account group) is Rook's; one whose users are in `openshift-storage` is ODF's and must stay; anything mixed needs a decision by hand. If the operator manifest deletion left them behind, this function re-classifies and removes only the ones that are provably Rook's:

```bash
rook_remove_sccs() {
  rook_gone || { echo "keeping SCCs rook-ceph and rook-ceph-csi" >&2; return 1; }
  local ns="$ROOK_NAMESPACE" json plan name verdict kept=0
  json=$(oc get scc -o json) || return 1
  plan=$(jq -r --arg ns "$ns" '.items[] | select(.metadata.name == "rook-ceph" or .metadata.name == "rook-ceph-csi")
      | ((.users // []) + (.groups // [])) as $all
      | [.metadata.name, (if ($all | length) > 0 and all($all[];
            startswith("system:serviceaccount:" + $ns + ":") or . == "system:serviceaccounts:" + $ns)
          then "rook" else "keep" end)] | @tsv' <<<"$json") || return 1
  while IFS=$'\t' read -r name verdict; do
    [ -n "$name" ] || continue
    if [ "$verdict" = rook ]; then
      oc delete scc "$name" --ignore-not-found --wait=false || return 1
    else
      echo "keeping SCC $name: its users are not all service accounts in $ns" >&2
      kept=1
    fi
  done <<<"$plan"
  return "$kept"
}
rook_remove_sccs
```
