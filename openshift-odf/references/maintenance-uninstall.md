# Maintenance And Uninstall

Use this runbook for node maintenance, OSD replacement, MachineConfig cleanup, ODF operator uninstall, and cluster removal. Uninstall ODF through OLM and the `StorageCluster`, not by deleting Rook CRs by hand.

## Node Maintenance

For SNO, treat node maintenance as an outage. Confirm backups and post-reboot checks; draining cannot preserve availability when there is only one node.

For multi-node:

```bash
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd set noout
oc adm cordon <node>
oc adm drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=<duration>
```

Set `noout` before draining so Ceph does not immediately rebalance data off a node that will return. Perform maintenance, uncordon the node, and confirm the OSDs have recovered before clearing the flag:

```bash
oc adm uncordon <node>
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd tree
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph osd unset noout
```

## OSD Replacement

See `references/cluster-expand-shrink.md` for the supported `ocs-osd-removal` job and disk-replacement steps. Always verify cluster health before and after replacement.

## Uninstall ODF

ODF uninstall is a documented, ordered process. It has two independent annotations:

- `uninstall.ocs.openshift.io/mode="graceful"` (the default) pauses until all ODF PVCs and OBCs are removed. `mode="forced"` proceeds despite those consumers and leaves orphaned PVCs and OBCs; it does not delete them safely.
- `uninstall.ocs.openshift.io/cleanup-policy="delete"` removes ODF `DataDirHostPath` data and OSD disks. `cleanup-policy="retain"` preserves them for a later recovery decision.

Confirm both the consumer-handling and disk-data intent with the user before choosing annotations.

### 0. Inventory the namespace before planning removal

LVMS installs into `openshift-storage` by default, and LSO can be installed there too. Inventory every operator in the namespace before touching it — the namespace, its subscriptions, and its CSVs can only be removed wholesale when ODF is the sole tenant:

```bash
oc -n openshift-storage get subscription,csv
oc -n openshift-storage get lvmcluster 2>/dev/null
```

If `lvms-operator`, `local-storage-operator`, or any other non-ODF subscription is present, keep the namespace and delete only the ODF subscriptions and CSVs by name (step 4).

### 1. Remove consumers

For the default graceful mode, delete application PVCs and OBCs that use ODF StorageClasses, and any custom StorageClasses you created on top of ODF. The cluster must have no bound ODF volumes before removing the `StorageCluster`. Use forced mode only when the user explicitly accepts orphaned claims and their recovery implications.

### 2. Set the uninstall annotations

```bash
# Choose delete only when the OSD disks and /var/lib/rook data may be erased.
oc annotate storagecluster ocs-storagecluster -n openshift-storage \
  uninstall.ocs.openshift.io/cleanup-policy="delete" --overwrite
# Graceful waits for all ODF PVCs and OBCs to be removed.
oc annotate storagecluster ocs-storagecluster -n openshift-storage \
  uninstall.ocs.openshift.io/mode="graceful" --overwrite
```

Use `mode="forced"` only when you accept orphaned ODF PVCs and OBCs. To preserve OSD disk data and `/var/lib/rook`, set `cleanup-policy="retain"` instead of `delete`; it does not change the forced/graceful consumer behavior.

### 3. Delete the StorageCluster

```bash
oc -n openshift-storage delete storagecluster ocs-storagecluster --wait=true --timeout=15m
```

`ocs-operator` tears down the reconciled Rook `CephCluster`, pools, filesystem, object store, and NooBaa system, and cleans OSD disks according to the cleanup policy. Watch it drain:

```bash
oc -n openshift-storage get storagecluster,cephcluster,noobaa -o wide
oc -n openshift-storage get pods -o wide
```

**Graceful uninstall blocked by `reconcileStrategy: ignore` (ODF 4.20 and 4.22 SNO workaround).** When the `StorageCluster` freezes managed resources with `reconcileStrategy: ignore` (see `references/validated-odf-sno.md`), `ocs-operator` skips those resources during uninstall and never deletes them. The freeze commonly covers **`cephBlockPools`, `cephObjectStores`, and `cephFilesystems`** — not just block pools — so the rook cluster-controller loops on:

```text
CephCluster "openshift-storage/ocs-storagecluster-cephcluster" will not be deleted until all dependents are removed: CephBlockPool: [builtin-mgr ocs-storagecluster-cephblockpool]
```

and the `StorageCluster` stays in `Deleting` past any timeout. Resolution: delete the frozen CRs directly — rook allows it while the destructive cleanup policy is active. Delete **all three kinds**, not only the block pools:

```bash
oc -n openshift-storage get cephblockpool cephfilesystem cephobjectstore
oc -n openshift-storage delete cephblockpool <leftover-pools>
oc -n openshift-storage delete cephfilesystem --all
oc -n openshift-storage delete cephobjectstore --all
```

**The CephCluster can stay `Deleting` even after the frozen pools/fs/object stores are gone.** It also waits on its remaining dependents, which the frozen teardown left behind, plus NooBaa. On a live ODF 4.20 SNO uninstall the blocker was:

```text
will not be deleted until all dependents are removed:
  CephBlockPoolRadosNamespace: [ocs-storagecluster-cephblockpool-builtin-implicit]
  CephClient: [csi-cephfs-node-... csi-cephfs-provisioner-... csi-rbd-node-... csi-rbd-provisioner-...]
  CephFilesystemSubVolumeGroup: [csi]
  CephObjectStoreUser: [noobaa-ceph-objectstore-user ocs-storagecluster-cephobjectstoreuser prometheus-user]
```

NooBaa itself holds a `noobaa.io/graceful_finalizer` and keeps the `noobaa-ceph-objectstore-user`. Delete NooBaa first (clear its finalizer if stuck), then the remaining dependents — the still-running CSI/ocs-client operators may recreate the `CephClient`s, so clear their finalizers as you delete:

```bash
oc -n openshift-storage patch noobaa noobaa --type merge -p '{"metadata":{"finalizers":[]}}'
oc -n openshift-storage delete noobaa noobaa --wait=false
for kind in cephobjectstoreuser cephclient cephfilesystemsubvolumegroup cephblockpoolradosnamespace; do
  for it in $(oc -n openshift-storage get "$kind" --no-headers -o custom-columns=:.metadata.name 2>/dev/null); do
    oc -n openshift-storage patch "$kind" "$it" --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null
    oc -n openshift-storage delete "$kind" "$it" --wait=false --ignore-not-found
  done
done
```

With `cleanup-policy="delete"`, rook runs a `cluster-cleanup-job-<node>` per node after the `CephCluster` is gone. That job removes `/var/lib/rook` and quick-sanitizes the OSD disks (metadata wipe, not full zeroing — see **Disk Cleanup** below if full erasure is required). **On raw-mode OSDs the cleanup job can hang on `ceph-volume lvm list`** (there is no LVM to enumerate): it finishes the `/var/lib/rook` cleanup but never completes. If it is stuck for minutes, delete the job and zap the disk manually (see **Disk Cleanup**):

```bash
oc -n openshift-storage get jobs | grep cluster-cleanup
oc -n openshift-storage logs job/cluster-cleanup-job-<node> --tail=5   # stuck at "ceph-volume ... raw/lvm list"?
oc -n openshift-storage delete job cluster-cleanup-job-<node>          # then wipe the disk manually
oc debug node/<node> -- chroot /host lsblk -f <osd-disk>   # expect no ceph_bluestore signature
```

Also confirm no **stale krbd device** was leaked (deleting a NooBaa DB / ceph-rbd PVC before it was unmapped wedges a `/dev/rbdN` that later hangs a reinstall's `ceph-volume raw list`). See the Rook cleanup runbook's "Stale krbd Devices" section:

```bash
oc debug node/<node> -- chroot /host bash -c 'ls /dev/rbd* 2>/dev/null || echo "no /dev/rbd*"; ls /sys/bus/rbd/devices/'
```

### 4. Remove the operators

Delete the ODF subscriptions by name, resolving each installed CSV from the subscription first — never delete all subscriptions wholesale (that also removes LVMS/LSO when they share the namespace), and never rely on the odf-operator CSV label selector, which matches only the odf-operator CSV and leaves the other component CSVs (ocs, rook, mcg, cephcsi, ...) behind:

```bash
# ODF package names; the subscription names may carry catalog suffixes — match on PACKAGE.
ODF_PKGS="odf-operator odf-dependencies ocs-operator ocs-client-operator rook-ceph-operator \
  cephcsi-operator mcg-operator odf-csi-addons-operator odf-external-snapshotter-operator \
  odf-prometheus-operator ocs-tls-profiles recipe"
for pkg in $ODF_PKGS; do
  sub=$(oc -n openshift-storage get subscription -o jsonpath="{.items[?(@.spec.name=='$pkg')].metadata.name}")
  [ -z "$sub" ] && continue
  csv=$(oc -n openshift-storage get subscription "$sub" -o jsonpath='{.status.installedCSV}')
  oc -n openshift-storage delete subscription "$sub"
  [ -n "$csv" ] && oc -n openshift-storage delete csv "$csv"
done
```

Delete the namespace only when the step-0 inventory showed ODF as the sole tenant:

```bash
# Guarded, and it fails closed: the namespace is deleted only when the subscription
# lookup SUCCEEDS and comes back empty.
#
# Do not write this as [ -z "$(oc get subscription ... 2>/dev/null)" ]. That cannot
# distinguish "no subscriptions" from "the lookup failed" — a missing RBAC verb, an
# API outage, or an already-removed CRD all yield an empty string, and the fallback
# is deleting a namespace that may still host LVMS and LSO. `-o name` prints nothing
# for an empty list, so an empty stdout with exit 0 is the only success signal.
if subs=$(oc -n openshift-storage get subscription -o name); then
  if [ -z "$subs" ]; then
    oc delete namespace openshift-storage --wait=true --timeout=15m
  else
    echo "namespace still has operator subscriptions - keeping it:"
    echo "$subs"
  fi
else
  echo "subscription lookup failed - keeping the namespace" >&2
  echo "resolve the error above and re-run; do not delete the namespace blind" >&2
fi
```

Remove the storage node labels after confirming the node no longer hosts another storage system:

```bash
oc label node <node> cluster.ocs.openshift.io/openshift-storage- || true
```

Before deleting LSO objects, inventory their ownership. LSO objects backing ODF are not always in `openshift-local-storage` — an ODF-dedicated `LocalVolumeSet` can live in `openshift-storage`. Discover the owning namespace from the local PV labels (`storage.openshift.com/owner-kind`, `storage.openshift.com/owner-namespace`):

```bash
oc get pv -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.labels.storage\.openshift\.com/owner-kind} {.metadata.labels.storage\.openshift\.com/owner-namespace}{"\n"}{end}'
oc -n <owner-namespace> get localvolumeset,localvolume,localvolumediscovery -o wide
```

Delete only named `LocalVolumeSet` and `LocalVolumeDiscovery` objects that were dedicated to ODF. Never use `--all`, and do not delete LSO resources when `LocalVolume`, Longhorn, LVMS, or another storage system shares the node or namespace. Deleting a `LocalVolumeSet` cascades to its PVs and StorageClass; do it promptly after the `StorageCluster` teardown, or the LSO provisioner re-creates an `Available` PV on the freshly wiped disk. Then remove the symlink directory on the node (`rm -rf /mnt/local-storage/<storageclass>` — symlinks only; the disk itself was already handled by the cleanup policy).

### 4b. Residue sweep when the namespace is kept

Namespace deletion normally garbage-collects everything below; keeping the namespace (shared with LVMS/LSO) means each item must be removed explicitly. All of these were observed to survive operator removal on a live 4.22.1 uninstall:

```bash
# ceph-csi driver instances: deleting the Driver CRs cascades their deployments/daemonsets
oc -n openshift-storage delete drivers.csi.ceph.io --all
oc delete csidriver openshift-storage.rbd.csi.ceph.com openshift-storage.cephfs.csi.ceph.com

# Remaining operator-scoped CRs
oc -n openshift-storage delete ocsinitializations.ocs.openshift.io,cephconnections.csi.ceph.io,operatorconfigs.csi.ceph.io --all

# Console: the Service must go first — while it exists, service-ca keeps re-creating its cert secret
oc -n openshift-storage delete svc ocs-client-operator-console
oc -n openshift-storage delete secret ocs-client-operator-console-serving-cert
oc delete consoleplugin odf-console odf-client-console

# Configmap pinned by an orphaned finalizer (its operator is gone; delete alone hangs)
oc -n openshift-storage patch cm ocs-client-operator-config --type merge -p '{"metadata":{"finalizers":[]}}'
oc -n openshift-storage delete cm ocs-client-operator-config --ignore-not-found
# finalizer: ocs-client-operator.ocs.openshift.io/storageused

# Rook/NooBaa state — stale mon keyrings and endpoints poison a later ODF reinstall
oc -n openshift-storage get secrets,cm | grep -iE 'rook|ceph|noobaa|ocs|odf'
oc -n openshift-storage delete cm rook-ceph-operator-config rook-ceph-pdbstatemap rook-config-override ocs-metrics-exporter-ceph-conf --ignore-not-found
# review the secret list and delete the rook/ceph/noobaa hits (mon keyrings, admin keyring, mon-endpoints)

# Cluster-scoped bundle objects OLM does not garbage-collect
oc delete scc ceph-csi-op-scc rook-ceph rook-ceph-csi noobaa noobaa-core noobaa-endpoint
oc delete mutatingwebhookconfiguration csv.odf.openshift.io
```

### 5. CRD cleanup

OLM removes most CRDs automatically when the operator is uninstalled, but they can linger — especially after forced or manual removal, and always when the namespace is kept. Sweep by API group rather than a fixed name list — the set changes per release (ODF 4.22 adds `storageautoscalers`/`storageclusterpeers`/`tlsprofiles` under `ocs.openshift.io` and the NooBaa embedded CloudNativePG group `postgresql.cnpg.noobaa.io`; `storagesystems.odf.openshift.io` is gone):

```bash
for group in ocs.openshift.io odf.openshift.io ceph.rook.io noobaa.io \
             postgresql.cnpg.noobaa.io csi.ceph.io local.storage.openshift.io; do
  echo "=== $group ==="; oc get crd 2>/dev/null | grep "$group" || echo "clean"
done
```

Delete every CR instance in a group before its CRDs, then the CRDs themselves:

```bash
# Skip local.storage.openshift.io when LSO stays installed (shared node/namespace).
for group in ocs.openshift.io odf.openshift.io ceph.rook.io noobaa.io \
             postgresql.cnpg.noobaa.io csi.ceph.io; do
  # 1. Discover the group's kinds. Fail closed: a suppressed discovery error
  #    returns an empty list, which would silently skip instance deletion and
  #    then delete the CRDs anyway, with instances still live.
  if ! kinds=$(oc api-resources --api-group="$group" --verbs=list -o name); then
    echo "kind discovery failed for $group - leaving its CRDs in place" >&2
    continue
  fi
  if ! namespaced=$(oc api-resources --api-group="$group" --namespaced=true -o name); then
    echo "scope discovery failed for $group - leaving its CRDs in place" >&2
    continue
  fi

  # 2. CR instances before their CRDs. Deleting a CRD while instances still carry
  #    finalizers leaves it in Terminating and stalls the rest of this sweep.
  instances_deleted=true
  for kind in $kinds; do
    # -F: resource names contain dots; without it they are read as regexes.
    if grep -Fqx -- "$kind" <<<"$namespaced"; then
      oc delete "$kind" --all -A --ignore-not-found || instances_deleted=false
    else
      oc delete "$kind" --all --ignore-not-found || instances_deleted=false
    fi
  done
  if [ "$instances_deleted" != true ]; then
    echo "instance deletion failed for $group - leaving its CRDs in place" >&2
    continue
  fi

  # 3. Only now the CRDs themselves.
  crds=$(oc get crd -o name | grep "\.$group$" || true)
  [ -n "$crds" ] && oc delete $crds
done
```

The `local.storage.openshift.io` CRDs belong to LSO; delete them only when LSO itself is being removed. The `groupsnapshot.storage.openshift.io` CRDs installed by `odf-external-snapshotter-operator` are shared snapshot infrastructure — leave them in place.

CRDs with the `customresourcecleanup.apiextensions.k8s.io` finalizer block until all CR instances are gone. If a CRD stays in `Terminating`, see **Stuck Namespace / Orphaned CRs** below.

## Post-Uninstall Audit

After uninstall, confirm:

- `openshift-storage` and `rook-ceph` namespaces are absent (or not Terminating). When the namespace was kept for LVMS/LSO: it contains no rook/ceph/noobaa/ocs/odf secrets, configmaps, services, or workloads, and the LVMS/LSO pods are still Running.
- The ODF CRD groups are clean: `ocs.openshift.io`, `odf.openshift.io`, `ceph.rook.io`, `noobaa.io`, `postgresql.cnpg.noobaa.io`, `csi.ceph.io` — plus `local.storage.openshift.io` only if LSO was removed too.
- No ODF SCCs (`rook-ceph*`, `noobaa*`, `ceph-csi-op-scc`), no `csv.odf.openshift.io` webhook, no `odf-console`/`odf-client-console` consoleplugins.
- No StorageClass uses an ODF provisioner (`openshift-storage.rbd.csi.ceph.com`, `openshift-storage.cephfs.csi.ceph.com`, `openshift-storage.noobaa.io/obc`, `openshift-storage.ceph.rook.io/bucket`).
- No PV/PVC uses an ODF StorageClass or is stuck Terminating.
- Exactly one intended default StorageClass remains.

Run the post-uninstall audit script:

```bash
bash scripts/post_uninstall_audit.sh
```

Equivalent manual checks:

```bash
# Namespaces
oc get ns openshift-storage rook-ceph 2>/dev/null || echo "namespaces gone"

# CRDs (all ODF groups; include local.storage.openshift.io only if LSO was removed)
for group in ocs.openshift.io odf.openshift.io ceph.rook.io noobaa.io \
             postgresql.cnpg.noobaa.io csi.ceph.io; do
  oc get crd 2>/dev/null | grep "$group" || true
done

# Orphaned PVCs or stuck Terminating PVCs/PVs
oc get pvc -A 2>/dev/null | grep -v Bound || echo "no stuck PVCs"
oc get pv -A  2>/dev/null | grep -v Bound || echo "no stuck PVs"

# StorageClasses and CSI drivers
oc get sc | grep -E 'openshift-storage|ocs-storagecluster' || true
oc get csidriver | grep openshift-storage || true
```

## Stuck Namespace / Orphaned CRs

When a namespace is deleted before its CRs are finalized (or when the operator that owns a finalizer is gone), objects can be permanently stuck in `Terminating`.

### Detect orphaned CRs

`oc get pvc -A` and `oc get <crd-kind> -A` will still show objects in a deleted namespace even after `oc get ns` returns NotFound. Check:

```bash
oc get pvc -A 2>/dev/null | grep -v Bound
for group in ocs.openshift.io ceph.rook.io noobaa.io csi.ceph.io; do
  oc get $(oc api-resources --api-group=$group -o name 2>/dev/null | head -1) -A --no-headers 2>/dev/null
done
```

### Clear orphaned CRs (namespace already deleted)

The API rejects PATCH/DELETE on objects in a non-existent namespace. Recreate the namespace briefly, strip finalizers, delete objects, then delete the namespace again:

```bash
NS="openshift-storage"   # or rook-ceph, etc.
oc create ns $NS

# For each stuck CR type, remove finalizers and delete
for cr_type in backingstores.noobaa.io bucketclasses.noobaa.io \
               cephclients.ceph.rook.io storageconsumers.ocs.openshift.io; do
  for name in $(oc get $cr_type -n $NS --no-headers 2>/dev/null | awk '{print $1}'); do
    oc patch $cr_type/$name -n $NS --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null
    oc delete $cr_type/$name -n $NS --wait=false 2>/dev/null
  done
done

# For cluster-scoped CRs (storageclients.ocs.openshift.io):
for name in $(oc get storageclients.ocs.openshift.io --no-headers 2>/dev/null | awk '{print $1}'); do
  oc patch storageclients.ocs.openshift.io/$name --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null
  oc delete storageclients.ocs.openshift.io/$name --wait=false 2>/dev/null
done

# Also clear orphaned PVCs (kubernetes.io/pvc-protection finalizer blocks deletion)
for name in $(oc get pvc -n $NS --no-headers 2>/dev/null | awk '{print $1}'); do
  oc patch pvc/$name -n $NS --type json -p '[{"op":"remove","path":"/metadata/finalizers/0"}]' 2>/dev/null
done

oc delete ns $NS --wait=false
```

### Force-finalize a stuck Terminating namespace

When a namespace is stuck in `Terminating` with `spec.finalizers: [kubernetes]` and all objects are gone, use the `/finalize` subresource to clear the finalizer (requires `oc proxy`):

```bash
oc proxy --port=8001 &
sleep 3
NS="openshift-storage"
oc get ns $NS -o json | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['spec']['finalizers'] = []
print(json.dumps(d))
" | curl -s -X PUT "http://localhost:8001/api/v1/namespaces/$NS/finalize" \
    -H "Content-Type: application/json" -d @-
```

Repeat for each stuck namespace (`rook-ceph`, `openshift-local-storage`, smoke/test namespaces). The namespace disappears within a few seconds after the finalizer is cleared.

## Disk Cleanup (Data Loss)

An uninstall with `cleanup-policy="delete"` wipes the OSD disks automatically. If the policy was not set, or you need to reclaim disks after the fact, clean each OSD disk only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target. `wipefs -af` and `sgdisk --zap-all` are sufficient for non-Ceph disks, but a disk that previously held a BlueStore OSD requires full-disk zeroing to clear the labels at its midpoint and end:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

# Standard signature and partition-table cleanup:
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"

# Required only when the disk previously held a BlueStore OSD:
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  dd if=/dev/zero of='${DISK}' bs=4M status=progress
  sync
  lsblk -f '${DISK}'
"
```

Full-disk zeroing can take a long time. See `references/local-storage-disks.md` for the BlueStore cleanup rationale and post-wipe checks.

## MachineConfig Cleanup

MachineConfig cleanup can reboot nodes. On SNO, warn about temporary API loss. Find ODF-specific MachineConfigs before deciding what to remove:

```bash
oc get machineconfig | grep -iE 'ocs|odf|rook' || true
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

ODF binds its own scoped SecurityContextConstraints through the operator bundle, and removing the operator removes them. Do not hand-remove the built-in `privileged` SCC from ODF service accounts unless you granted it manually during emergency repair. If a manual grant was made, remove only that exact grant:

```bash
oc get scc | grep -E 'rook-ceph|noobaa' || true
oc adm policy who-can use scc privileged
```
