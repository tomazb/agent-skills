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
# Comma-separated resource types — space-separated names are invalid oc syntax.
oc -n openshift-storage get cephblockpool,cephfilesystem,cephobjectstore
oc -n openshift-storage delete cephblockpool <leftover-pools> --wait=false
oc -n openshift-storage delete cephfilesystem --all --wait=false
oc -n openshift-storage delete cephobjectstore --all --wait=false
```

**The CephCluster can stay `Deleting` even after the frozen pools/fs/object stores are gone.** It also waits on its remaining dependents, which the frozen teardown left behind, plus NooBaa. On a live ODF 4.20 SNO uninstall the blocker was:

```text
will not be deleted until all dependents are removed:
  CephBlockPoolRadosNamespace: [ocs-storagecluster-cephblockpool-builtin-implicit]
  CephClient: [csi-cephfs-node-... csi-cephfs-provisioner-... csi-rbd-node-... csi-rbd-provisioner-...]
  CephFilesystemSubVolumeGroup: [csi]
  CephObjectStoreUser: [noobaa-ceph-objectstore-user ocs-storagecluster-cephobjectstoreuser prometheus-user]
```

NooBaa itself holds a `noobaa.io/graceful_finalizer` and keeps the `noobaa-ceph-objectstore-user`. The `ocs-client-operator` and the ceph-csi controller **recreate** the `CephClient`s as fast as you delete them, so scale **those** reconcilers down first — **leave `rook-ceph-operator` running**, because rook is what deletes the `CephCluster` and launches the per-node `cluster-cleanup-job`. Then delete NooBaa (clear its finalizer if stuck) and sweep the dependents in a bounded loop that **fails** if they do not converge:

```bash
# Stop only the reconcilers that recreate CephClients (NOT rook-ceph-operator):
OC="oc --request-timeout=30s"
$OC -n openshift-storage scale deploy/ocs-client-operator-controller-manager deploy/ceph-csi-controller-manager --replicas=0

$OC -n openshift-storage patch noobaa noobaa --type merge -p '{"metadata":{"finalizers":[]}}'
$OC -n openshift-storage delete noobaa noobaa --wait=false

# Bounded sweep: repeat until every dependent kind reports none, else exit nonzero.
KINDS="cephobjectstoreuser cephclient cephfilesystemsubvolumegroup cephblockpoolradosnamespace"
for pass in $(seq 1 12); do
  left=0
  for kind in $KINDS; do
    items="$($OC -n openshift-storage get "$kind" --no-headers -o custom-columns=:.metadata.name)" || {
      echo "failed to list $kind" >&2
      exit 1
    }
    [ -z "$items" ] && continue
    left=1
    while IFS= read -r it; do
      [ -n "$it" ] || continue
      $OC -n openshift-storage patch "$kind" "$it" --type merge -p '{"metadata":{"finalizers":[]}}'
      $OC -n openshift-storage delete "$kind" "$it" --wait=false --ignore-not-found
    done <<EOF
$items
EOF
  done
  [ "$left" -eq 0 ] && break
  sleep 5
done
# Fail closed if anything remains — do not continue teardown with live dependents:
remaining="$($OC -n openshift-storage get ${KINDS// /,} --no-headers -o name)" || {
  echo "failed to recheck dependents" >&2
  exit 1
}
[ -z "$remaining" ] || { printf '%s\n' "$remaining"; echo "dependents did not converge" >&2; exit 1; }
```

Once the `CephCluster` is deleted, scale `rook-ceph-operator` back to its original replica count if you changed it, and re-enable the reconcilers you stopped after the namespace teardown completes.

**`StorageClient` status-reporter CrashLoop during teardown.** After the `CephCluster` is gone, the cluster-scoped `StorageClient` (and its CronJob `storageclient-*-status-reporter`) keeps trying to report client state and CrashLoops with `failed to produce client state hash`. That is noise from a half-torn-down cluster, not a separate outage — but leaving the CRs around can also keep the `StorageCluster` finalizer from clearing. Delete them (and the CronJob) as soon as Ceph is gone:

```bash
oc -n openshift-storage delete cronjob -l app.kubernetes.io/name=ocs-client-operator --ignore-not-found
# Name pattern if labels differ:
oc -n openshift-storage get cronjob -o name | grep storageclient | xargs -r oc -n openshift-storage delete --wait=false

for kind in storageclient storageconsumer; do
  for name in $(oc -n openshift-storage get "$kind" -o name --ignore-not-found); do
    oc -n openshift-storage patch "$name" --type merge -p '{"metadata":{"finalizers":[]}}'
    oc -n openshift-storage delete "$name" --wait=false --ignore-not-found
  done
done
# Cluster-scoped StorageClient (ocs.openshift.io): delete ONLY the client that
# matches the StorageCluster being removed (default name ocs-storagecluster).
# Other StorageClients may belong to a different / external consumer — do not
# wipe the whole cluster-scoped list without explicit confirmation.
TARGET_STORAGECLIENT="${TARGET_STORAGECLIENT:-ocs-storagecluster}"
for name in $(oc get storageclients.ocs.openshift.io -o name --ignore-not-found); do
  short="${name##*/}"
  if [ "$short" != "$TARGET_STORAGECLIENT" ]; then
    echo "skipping unrelated StorageClient $short (want $TARGET_STORAGECLIENT)" >&2
    continue
  fi
  oc patch "$name" --type merge -p '{"metadata":{"finalizers":[]}}'
  oc delete "$name" --wait=false --ignore-not-found
done
```

With `cleanup-policy="delete"`, rook runs a `cluster-cleanup-job-<node>` per node after the `CephCluster` is gone. That job removes `/var/lib/rook` and quick-sanitizes the OSD disks (metadata wipe, not full zeroing — see **Disk Cleanup** below if full erasure is required). **On raw-mode OSDs the cleanup job can hang on `ceph-volume lvm list`** (there is no LVM to enumerate): it finishes the `/var/lib/rook` cleanup but never completes. If it is stuck for minutes, delete the job, **wait for the Job and its pod to actually terminate**, then zap the disk manually (deleting with `--wait=false` returns before the pod is gone, and wiping a disk the cleanup pod still holds races it):

```bash
OC="oc --request-timeout=30s"
$OC -n openshift-storage get jobs | grep cluster-cleanup
$OC -n openshift-storage logs job/cluster-cleanup-job-<node> --tail=5   # stuck at "ceph-volume ... raw/lvm list"?
$OC -n openshift-storage delete job cluster-cleanup-job-<node> --wait=false --ignore-not-found
# Wait until the Job and its pod are gone before touching the disk:
job_gone=0
for i in $(seq 1 30); do
  job="$($OC -n openshift-storage get job/cluster-cleanup-job-<node> --ignore-not-found -o name)" || {
    echo "failed to query cleanup job" >&2
    exit 1
  }
  pods="$($OC -n openshift-storage get pods -l job-name=cluster-cleanup-job-<node> --no-headers -o custom-columns=:.metadata.name)" || {
    echo "failed to query cleanup pods" >&2
    exit 1
  }
  if [ -z "$job" ] && [ -z "$pods" ]; then
    job_gone=1
    break
  fi
  sleep 2
done
[ "$job_gone" -eq 1 ] || { echo "cleanup job/pod did not terminate within 60s" >&2; exit 1; }
oc debug node/<node> -- chroot /host lsblk -f <osd-disk>   # expect no ceph_bluestore signature; then wipe manually
```

**Cleanup-job success is not a clean disk.** On a live ODF 4.20 SNO uninstall with LSO `LocalVolume` and `cleanup-policy=delete`, the job can complete while still leaving:

1. An **empty** `/var/lib/rook` directory.
2. An **XFS** signature (when LSO used a filesystem path).
3. **BlueStore labels at 10 GiB / 100 GiB** (and other official offsets) that `wipefs -n` / `lsblk -f` do **not** show. A later OSD prepare then CrashLoopBackOffs with `osd.0 belonging to a different ceph cluster "<old-fsid>"`.

After the job (or after a manual zap), verify and finish host cleanup before calling the uninstall done:

```bash
oc debug node/<node> -- chroot /host bash -c '
set -e
DISK=/dev/disk/by-id/<stable-disk-id>
if [ -d /var/lib/rook ] && [ -z "$(ls -A /var/lib/rook)" ]; then
  rmdir /var/lib/rook
fi
ls -la /var/lib/rook 2>/dev/null || echo "no /var/lib/rook"
lsblk -f "$DISK"
wipefs -n "$DISK" || echo "no signatures (wipefs)"
'
# Authoritative BlueStore check (RHCOS has no ceph-volume on the host):
oc debug node/<node> --image=quay.io/ceph/ceph:v19.2.2 -- bash -c '
  mount --rbind /host/dev /dev
  ceph-volume raw list /dev/disk/by-id/<stable-disk-id> --format json   # must be {}
'
```

If `ceph-volume raw list` is non-empty, or `lsblk -f` still shows a filesystem, run **Disk Cleanup** in `references/local-storage-disks.md` (BlueStore labels at **0 / 1 GiB / 10 GiB / 100 GiB / 1000 GiB**, or full-disk zero) with destructive confirmation for that exact by-id path. Also remove the LSO symlink dir if present: `rm -rf /mnt/local-storage/<storageclass>`.

**If the cleanup pod left host processes in D-state (`sgdisk`, `lvs`) on the OSD disk**, `kill -9` will not free the device and a later OSD prepare hangs forever inside `ceph-volume raw prepare` / `lvs`. Confirm with `oc debug node/<node> -- chroot /host bash -c 'fuser -v /dev/disk/by-id/<id>; ps -eo pid,stat,comm | awk "\$2 ~ /D/"'`.

Before rebooting: delete any stuck `rook-ceph-osd-prepare` Job/pod so prepare does not resume into the same blocked I/O on boot. On SNO, warn hard — a soft `systemctl reboot` after disk D-state can put the node into a **reboot loop** (brief Ready, then API/SSH refused for long stretches). Prefer an out-of-band hypervisor power cycle or console recovery; if the node does not stabilize, rebuild it rather than waiting indefinitely.

Also confirm no **stale krbd device** was leaked (deleting a NooBaa DB / ceph-rbd PVC before it was unmapped wedges a `/dev/rbdN` that later hangs a reinstall's `ceph-volume raw list`). See the Rook cleanup runbook's "Stale krbd Devices" section:

```bash
oc debug node/<node> -- chroot /host bash -c 'ls /dev/rbd[0-9]* 2>/dev/null || echo "no /dev/rbd[0-9]*"; ls /sys/bus/rbd/devices/'
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

Delete the namespace only when the step-0 inventory showed ODF as the sole tenant.

**Before deleting the namespace, clear finalizer-bearing residue that step 4b
documents for the kept-namespace case.** Those objects also block *namespace*
deletion: on a live ODF 4.20 SNO uninstall, `openshift-storage` stayed
`Terminating` on `csiaddonsnodes.csiaddons.openshift.io` (per-node CRs with
operator finalizers) and ConfigMap `ocs-client-operator-config` (finalizer
`ocs-client-operator.ocs.openshift.io/storageused`). Step 4b is not optional
when the namespace is going away — run this sweep first, then delete the ns:

```bash
# Finalizer residue that hangs namespace deletion (operators already gone):
if oc -n openshift-storage get cm ocs-client-operator-config >/dev/null 2>&1; then
  oc -n openshift-storage patch cm ocs-client-operator-config --type merge \
    -p '{"metadata":{"finalizers":[]}}'
  oc -n openshift-storage delete cm ocs-client-operator-config --wait=false
fi

if oc api-resources --api-group=csiaddons.openshift.io -o name 2>/dev/null \
  | grep -qx csiaddonsnodes.csiaddons.openshift.io; then
  for name in $(oc -n openshift-storage get csiaddonsnodes.csiaddons.openshift.io \
    -o name --ignore-not-found); do
    oc -n openshift-storage patch "$name" --type merge -p '{"metadata":{"finalizers":[]}}'
    oc -n openshift-storage delete "$name" --wait=false --ignore-not-found
  done
fi
```

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

If the namespace still hangs in `Terminating` after that sweep, use **Stuck
Namespace / Orphaned CRs** below. Do not skip the pre-delete patch and rely on
`/finalize` alone — that leaves orphaned CRs the API can no longer PATCH.
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

**ODF-only LSO install (fresh-cluster expectation).** When LSO was installed solely to feed ODF (typical `openshift-local-storage` with no other consumers) and the goal is a cluster that looks like ODF was never present, also remove LSO after the ODF LocalVolume/LocalVolumeSet objects are gone: delete its Subscription/CSV, sweep `local.storage.openshift.io` CRDs, and delete `openshift-local-storage`. Skip this when LVMS, Longhorn, or another product still needs LSO.

### 4a. Disable ODF console plugins (cluster-scoped)

`console.operator.openshift.io/cluster` and the `ConsolePlugin` CRs are
**cluster-scoped**. Namespace deletion does not clear `spec.plugins`, and it
does not garbage-collect `odf-console` / `odf-client-console`. After a CLI
enable (see `references/console-plugin.md`), stale enabled names keep pointing
at plugins that no longer exist. Always prune here — whether the namespace is
kept or deleted.

```bash
CURRENT=$(oc get console.operator.openshift.io cluster -o jsonpath='{.spec.plugins}')
[ -n "$CURRENT" ] || CURRENT='[]'

python3 scripts/render_console_plugin_patch.py \
  --current-plugins "$CURRENT" \
  --remove odf-console odf-client-console \
  --output /tmp/odf-console-plugins-remove.patch.json

# Review: non-ODF plugins (monitoring, networking, ...) MUST remain.
cat /tmp/odf-console-plugins-remove.patch.json
oc patch console.operator.openshift.io cluster --type merge \
  --patch-file /tmp/odf-console-plugins-remove.patch.json

# Then delete the ConsolePlugin CRs themselves.
oc delete consoleplugin odf-console odf-client-console --ignore-not-found

oc get console.operator.openshift.io cluster -o jsonpath='{.spec.plugins}{"\n"}'
oc get consoleplugin 2>/dev/null | grep -E 'odf-console|odf-client-console' || echo "no ODF consoleplugins"
```

Never replace `spec.plugins` with `[]` unless discovery showed that only ODF
plugins were enabled — that would disable monitoring and networking on a
typical cluster.

### 4b. Residue sweep when the namespace is kept

Namespace deletion normally garbage-collects most namespaced residue below;
keeping the namespace (shared with LVMS/LSO) means each item must be removed
explicitly. Console plugins are handled in step 4a because they are
cluster-scoped and survive namespace deletion. All of these were observed to
survive operator removal on a live 4.22.1 uninstall:

```bash
# ceph-csi driver instances: deleting the Driver CRs cascades their deployments/daemonsets
oc -n openshift-storage delete drivers.csi.ceph.io --all
oc delete csidriver openshift-storage.rbd.csi.ceph.com openshift-storage.cephfs.csi.ceph.com

# Remaining operator-scoped CRs
oc -n openshift-storage delete ocsinitializations.ocs.openshift.io,cephconnections.csi.ceph.io,operatorconfigs.csi.ceph.io --all

# Console Service/cert residue (ConsolePlugin CRs were removed in step 4a).
# The Service must go first — while it exists, service-ca keeps re-creating its cert secret.
oc -n openshift-storage delete svc ocs-client-operator-console
oc -n openshift-storage delete secret ocs-client-operator-console-serving-cert

# Configmap pinned by an orphaned finalizer (its operator is gone; delete alone hangs)
oc -n openshift-storage patch cm ocs-client-operator-config --type merge -p '{"metadata":{"finalizers":[]}}'
oc -n openshift-storage delete cm ocs-client-operator-config --ignore-not-found
# finalizer: ocs-client-operator.ocs.openshift.io/storageused

# Rook/NooBaa state — stale mon keyrings and endpoints poison a later ODF reinstall
oc -n openshift-storage get secrets,cm | grep -iE 'rook|ceph|noobaa|ocs|odf'
oc -n openshift-storage delete cm rook-ceph-operator-config rook-ceph-pdbstatemap rook-config-override ocs-metrics-exporter-ceph-conf --ignore-not-found
# review the secret list and delete the rook/ceph/noobaa hits (mon keyrings, admin keyring, mon-endpoints)

# Unowned RBAC, PDB and alert rules created by the ODF install (observed with ODF 4.20.17).
# Nothing owns them, so removing the operators never collects them.
oc -n openshift-storage get pdb,sa,role,rolebinding,cm | grep -iE 'rook|ceph|noobaa|ocs-|odf'
oc -n openshift-storage get prometheusrule,servicemonitor 2>/dev/null | grep -iE 'rook|ceph|noobaa|ocs-|odf'
oc -n openshift-storage delete pdb rook-ceph-mon-pdb --ignore-not-found
oc -n openshift-storage delete sa ocs-status-reporter --ignore-not-found
oc -n openshift-storage delete role,rolebinding ocs-provider-server ocs-status-reporter \
  odf-operator-controller-manager-metrics-service rook-ceph-metrics rook-ceph-monitor --ignore-not-found
oc -n openshift-storage delete prometheusrule ocs-prometheus-rules --ignore-not-found
oc -n openshift-storage delete cm odf-info --ignore-not-found

# Cluster-scoped bundle objects OLM does not garbage-collect. If an upstream Rook
# cluster runs elsewhere (see step 5), rook-ceph and rook-ceph-csi are ITS SCCs:
#   oc get scc rook-ceph rook-ceph-csi -o jsonpath='{range .items[*]}{.metadata.name}: {.users}{"\n"}{end}'
# and leave out any SCC whose users are all service accounts of that Rook namespace.
oc delete scc ceph-csi-op-scc rook-ceph rook-ceph-csi noobaa noobaa-core noobaa-endpoint
oc delete mutatingwebhookconfiguration csv.odf.openshift.io
```

Cluster-scoped RBAC and the CRD groups are left out of this sweep on purpose: decide them with **Cluster RBAC left by ODF** below and step 5, because some of them still carry ODF labels while another product uses them.

### 5. CRD cleanup

OLM removes most CRDs automatically when the operator is uninstalled, but they can linger — especially after forced or manual removal, and always when the namespace is kept. Sweep by API group rather than a fixed name list — the set changes per release (ODF 4.22 adds `storageautoscalers`/`storageclusterpeers`/`tlsprofiles` under `ocs.openshift.io` and the NooBaa embedded CloudNativePG group `postgresql.cnpg.noobaa.io`; `storagesystems.odf.openshift.io` is gone). A live ODF 4.20 SNO uninstall also left **`csiaddons.openshift.io`** (from `odf-csi-addons-operator`) and **`objectbucket.io`** (OBC/OB) after the core ODF groups were gone, and ODF 4.20.17 leftovers on an OCP 4.20.34 SNO cluster included **`replication.storage.openshift.io`** (five CRDs, package `odf-csi-addons-operator`) and **`ramendr.openshift.io`** (`recipes`, package `recipe`), each with zero instances — include them.

**Re-run the ownership gate before sweeping.** `ceph.rook.io`, `csi.ceph.io`, and `objectbucket.io` are not ODF's alone: an upstream (non-OLM) Rook cluster uses the same CRDs. On a cluster where upstream Rook ran in `rook-ceph` after ODF was removed, the unguarded sweep below would have deleted that cluster's `CephCluster`, its `drivers.csi.ceph.io`, its bucket claims, and the CRDs under it. Classify every `CephCluster` the way `SKILL.md` does — one outside `openshift-storage` with no `StorageCluster` owner is upstream Rook — and fail closed if the lookup errors:

```bash
# Fail closed: a lookup error must not read as "no upstream Rook".
if ! clusters=$(oc get cephclusters.ceph.rook.io -A -o json 2>&1); then
  case "$clusters" in
    *"doesn't have a resource type"*) clusters='{"items":[]}' ;;
    *) echo "CephCluster lookup failed - stop and resolve: $clusters" >&2; exit 1 ;;
  esac
fi
ROOK_NAMESPACES=$(jq -r '[.items[]
  | select(.metadata.namespace != "openshift-storage")
  | select(any(.metadata.ownerReferences[]?; .kind == "StorageCluster") | not)
  | .metadata.namespace] | unique | join(" ")' <<<"$clusters")
echo "upstream Rook namespaces: ${ROOK_NAMESPACES:-none}"

ODF_GROUPS="ocs.openshift.io odf.openshift.io noobaa.io postgresql.cnpg.noobaa.io \
  csiaddons.openshift.io replication.storage.openshift.io ramendr.openshift.io"
if [ -z "$ROOK_NAMESPACES" ]; then
  ODF_GROUPS="$ODF_GROUPS ceph.rook.io csi.ceph.io objectbucket.io"
fi
```

When `ROOK_NAMESPACES` is not empty, leave the three shared groups and their CRDs in place, and delete only ODF's own instances, which live in `openshift-storage`:

```bash
for group in ceph.rook.io csi.ceph.io objectbucket.io; do
  kinds=$(oc api-resources --api-group="$group" --namespaced=true --verbs=list -o name) || {
    echo "kind discovery failed for $group" >&2; continue; }
  for kind in $kinds; do
    oc -n openshift-storage get "$kind" -o name
  done
done
# Review that list, then delete those objects by name with -n openshift-storage.
```

ODF's cluster-scoped `ObjectBucket`s and bucket claims in consumer namespaces are decided by their StorageClass (see **Orphans After An Interrupted Uninstall**), not by group. Anything about the running Rook cluster itself — its health, its CRDs, its SCCs — is the `openshift-rook` skill's job; hand it off rather than changing it from this runbook.

```bash
for group in $ODF_GROUPS local.storage.openshift.io groupsnapshot.storage.openshift.io; do
  echo "=== $group ==="; oc get crd 2>/dev/null | grep "$group" || echo "clean"
done
```

Delete every CR instance in a group before its CRDs, then the CRDs themselves:

```bash
# Skip local.storage.openshift.io when LSO stays installed (shared node/namespace).
for group in $ODF_GROUPS; do
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

The `local.storage.openshift.io` CRDs belong to LSO; delete them only when LSO itself is being removed.

The `groupsnapshot.storage.openshift.io` CRDs need a decision, not a default. **Keep them** when any instance exists, when they carry `release.openshift.io` annotations (the release payload owns them), when the `VolumeGroupSnapshot` feature gate is enabled, or when another snapshotter or workload uses the group. **They are ODF residue** when they are labelled for `odf-external-snapshotter-operator`, have no instances and no release-payload annotations, the feature gate is off, and nothing references the group. That was the case with ODF 4.20.17 leftovers on an OCP 4.20.34 SNO cluster, and removing them had no effect. `post_uninstall_audit.sh` checks the first four conditions; check the last one by hand:

```bash
G=groupsnapshot.storage.openshift.io
oc get crd -o json | jq -r --arg g "$G" '.items[] | select(.spec.group == $g)
  | "\(.metadata.name) labels=\(.metadata.labels // {} | keys) annotations=\(.metadata.annotations // {} | keys)"'
for r in $(oc api-resources --api-group="$G" --verbs=list -o name); do oc get "$r" -A --no-headers; done
oc get featuregate cluster -o jsonpath='{.status.featureGates[*].enabled[*].name}' | tr ' ' '\n' | grep -x VolumeGroupSnapshot
# Anything that names the group: workloads, roles that grant it, webhooks.
oc get deploy,ds,sts -A -o json | jq -r --arg g "$G" '.items[] | select(tostring | contains($g)) | "\(.kind) \(.metadata.namespace)/\(.metadata.name)"'
oc get clusterrole -o json | jq -r --arg g "$G" '.items[] | select(any(.rules[]?; (.apiGroups // []) | index($g))) | .metadata.name'
oc get validatingwebhookconfiguration,mutatingwebhookconfiguration -o json | jq -r --arg g "$G" '.items[] | select(tostring | contains($g)) | .metadata.name'
```

The same four questions — zero instances, no workload or configuration names the group, no webhook targets it, and its owning operator is gone — decide any other CRD that still carries an `operators.coreos.com/<odf-package>.openshift-storage` label. ClusterRoles that grant a group (the `clusterrole` query above) count as "configuration names the group" only when a live binding uses them; see **Cluster RBAC left by ODF**.

CRDs with the `customresourcecleanup.apiextensions.k8s.io` finalizer block until all CR instances are gone. If a CRD stays in `Terminating`, see **Stuck Namespace / Orphaned CRs** below.

## Post-Uninstall Audit

After uninstall, confirm:

- `openshift-storage` and `rook-ceph` namespaces are absent (or not Terminating). When the namespace was kept for LVMS/LSO: it contains no rook/ceph/noobaa/ocs/odf secrets, configmaps, services, workloads, service accounts, roles, role bindings, PodDisruptionBudgets, jobs, cronjobs, ServiceMonitors, or PrometheusRules; no ODF pod and no pod with a `deletionTimestamp` remains there; and the LVMS/LSO pods are still Running.
- When an upstream Rook `CephCluster` runs (outside `openshift-storage`, no `StorageCluster` owner), its namespace, the `ceph.rook.io`, `csi.ceph.io`, and `objectbucket.io` CRDs, and the SCCs whose users are all its service accounts are retained, not residue. Instances of those groups inside `openshift-storage` still are, and so is any `CephCluster` in `openshift-storage` or owned by a `StorageCluster`.
- The ODF CRD groups are clean: `ocs.openshift.io`, `odf.openshift.io`, `ceph.rook.io`, `noobaa.io`, `postgresql.cnpg.noobaa.io`, `csi.ceph.io`, `csiaddons.openshift.io`, `objectbucket.io`, `replication.storage.openshift.io`, `ramendr.openshift.io` — plus `local.storage.openshift.io` only if LSO was removed too, and `groupsnapshot.storage.openshift.io` decided as in step 5.
- OSD disks pass `ceph-volume raw list` → `{}` (not only a clean `wipefs -n`), and `/var/lib/rook` is absent (not merely empty).
- No ODF SCCs (`rook-ceph*`, `noobaa*`, `ceph-csi-op-scc`), no `csv.odf.openshift.io` webhook, no `odf-console`/`odf-client-console` consoleplugins, and neither name remains in `console.operator.openshift.io/cluster` `spec.plugins`.
- No StorageClass uses an ODF provisioner (`openshift-storage.rbd.csi.ceph.com`, `openshift-storage.cephfs.csi.ceph.com`, `openshift-storage.noobaa.io/obc`, `openshift-storage.ceph.rook.io/bucket`).
- No PV/PVC uses an ODF StorageClass or has a `deletionTimestamp`, and no `VolumeAttachment` names an ODF attacher.
- No ObjectBucketClaim or ObjectBucket whose StorageClass is missing or uses an ODF provisioner, no ConfigMap or Secret held by `objectbucket.io/finalizer` without a live claim, and no namespace stuck `Terminating`.
- No dead ODF ClusterRole or ClusterRoleBinding (see **Cluster RBAC left by ODF**).
- Exactly one intended default StorageClass remains.

Run the post-uninstall audit script:

```bash
bash scripts/post_uninstall_audit.sh
```

Any `WARN` or `FAIL` line exits nonzero. `OK: ... retained: <reason>` lines name objects that look like ODF's but are in use (upstream Rook, a live RBAC subject, platform-owned group-snapshot CRDs); they do not fail the audit. "Terminating" for a PVC or PV is only how `oc get` prints it — the phase stays `Bound` or `Released` and the deletion shows as `metadata.deletionTimestamp`, which is what the audit tests. A namespace deleted seconds ago is not stuck; re-run before acting on that line.

Equivalent manual checks:

```bash
# Namespaces
oc get ns openshift-storage rook-ceph 2>/dev/null || echo "namespaces gone"
oc get ns | grep Terminating || echo "no Terminating namespaces"

# CRDs (all ODF groups; include local.storage.openshift.io only if LSO was removed;
# leave out ceph.rook.io csi.ceph.io objectbucket.io when upstream Rook runs)
for group in ocs.openshift.io odf.openshift.io ceph.rook.io noobaa.io \
             postgresql.cnpg.noobaa.io csi.ceph.io \
             csiaddons.openshift.io objectbucket.io \
             replication.storage.openshift.io ramendr.openshift.io; do
  oc get crd 2>/dev/null | grep "$group" || true
done

# Deleting PVCs/PVs (deletionTimestamp set, whatever the phase)
oc get pvc -A -o jsonpath='{range .items[?(@.metadata.deletionTimestamp)]}{.metadata.namespace}/{.metadata.name} {.status.phase}{"\n"}{end}'
oc get pv -o jsonpath='{range .items[?(@.metadata.deletionTimestamp)]}{.metadata.name} {.status.phase}{"\n"}{end}'

# StorageClasses, CSI drivers, VolumeAttachments
oc get sc | grep -E 'openshift-storage|ocs-storagecluster' || true
oc get csidriver | grep openshift-storage || true
oc get volumeattachment -o custom-columns=NAME:.metadata.name,ATTACHER:.spec.attacher,PV:.spec.source.persistentVolumeName | grep openshift-storage || true
```

## Orphans After An Interrupted Uninstall

When the ODF operators and CSI driver are removed **before** the workloads and volumes that need them — an uninstall stopped halfway, operators deleted first, or a forced uninstall — the steps above leave objects that can never go away by themselves: every one of them waits for a controller or driver that no longer exists. Seen with ODF 4.20.17 leftovers on an OCP 4.20.34 SNO cluster (LVMS sharing `openshift-storage`, an upstream Rook cluster in `rook-ceph` installed later) 47 days after ODF was removed. A reboot cleared none of it.

### Prove nothing stands behind a finalizer

Stripping a finalizer skips whatever cleanup it guards. Do it only after collecting all of this evidence, and stop if any of it fails:

```bash
oc get csidriver | grep openshift-storage                        # expect nothing
oc get csinode <node> -o jsonpath='{.spec.drivers[*].name}{"\n"}' # no openshift-storage.* driver
oc get sc ocs-storagecluster-ceph-rbd ocs-storagecluster-cephfs ocs-storagecluster-ceph-rgw openshift-storage.noobaa.io
                                                                  # expect NotFound for each
oc -n openshift-storage get cephcluster 2>&1                       # no CephCluster (or no such type)
oc api-resources --api-group=noobaa.io; oc api-resources --api-group=ocs.openshift.io
oc api-resources --api-group=postgresql.cnpg.noobaa.io            # expect no output: CRDs gone
oc get csv,subscription -A | grep -E 'odf-|ocs-|mcg-|cephcsi|rook-ceph-operator|recipe'
                                                                  # no ODF CSV or Subscription anywhere
oc get pv <pv> -o jsonpath='{.spec.csi.driver} {.spec.csi.volumeAttributes.clusterID}{"\n"}'
                                                                  # the removed driver, clusterID openshift-storage
```

An upstream Rook cluster's driver is `rook-ceph.rbd.csi.ceph.com` (or another prefix), never `openshift-storage.*`; if a PV names a driver that is still registered, it is not an orphan.

### Order of removal

Work in this order — each step releases the next, and the reverse creates new stuck objects:

1. The Pod the kubelet cannot release (then its PVC goes by itself).
2. `VolumeAttachment`s of the removed driver.
3. PVs of the removed driver.
4. Finalizers in consumer namespaces stuck `Terminating` (bucket claims and their ConfigMaps/Secrets).
5. Cluster-scoped `ObjectBucket`s.
6. Cluster RBAC and CRDs (**Cluster RBAC left by ODF**, step 5).

### Pod the kubelet holds after its CSI driver is gone

Recognise it: a Pod in `openshift-storage` (seen: `noobaa-db-pg-cluster-1`, label `cnpg.io/cluster=noobaa-db-pg-cluster`) with phase `Failed`, its container terminated, `deletionTimestamp` set, **no finalizers**, and an ownerReference to a kind whose CRD is gone (a CNPG `Cluster`). Its PVC is `Bound` with a weeks-old `deletionTimestamp`, held only by `kubernetes.io/pvc-protection`. The kubelet journal repeats an `UnmountVolume` start followed by a failure naming `openshift-storage.rbd.csi.ceph.com` as not registered, every couple of minutes. Without the driver the kubelet can never unmount, so it never lets the Pod object go.

```bash
oc -n openshift-storage get pods -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,DELETING:.metadata.deletionTimestamp,NODE:.spec.nodeName
oc -n openshift-storage get pod <pod> -o jsonpath='{.metadata.uid}{"\n"}{.metadata.finalizers}{"\n"}{.metadata.ownerReferences}{"\n"}'
oc adm node-logs <node> -u kubelet --tail=500 | grep -E 'UnmountVolume|openshift-storage\.(rbd|cephfs)\.csi\.ceph\.com'
```

Fix: force-delete the Pod object, then **restart the kubelet on that node**:

```bash
oc -n openshift-storage delete pod <pod> --grace-period=0 --force
# The debug session runs through the kubelet and may drop when it restarts; that is expected.
# SSH to the node and `sudo systemctl restart kubelet` works too.
oc debug node/<node> -- chroot /host systemctl restart kubelet
```

On SNO the API is briefly unavailable while the kubelet restarts; running containers, including the static control-plane pods, keep running. Afterwards the kubelet journal must show no further lines for that volume, and the kubelet removes `/var/lib/kubelet/pods/<uid>` itself:

```bash
oc adm node-logs <node> -u kubelet --tail=500 | grep -E 'UnmountVolume|openshift-storage\.(rbd|cephfs)\.csi\.ceph\.com' || echo "quiet"
oc debug node/<node> -- chroot /host ls /var/lib/kubelet/pods/<uid> 2>&1   # expect: No such file or directory
oc -n openshift-storage get pvc                                           # the held PVC is gone
```

> **Warning — never delete the volume directory under a running kubelet.** Removing `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~csi/<pv>` by hand looks safe when it holds only `vol_data.json`, nothing is mounted, and no rbd device is mapped. It is not: the kubelet still holds the volume in memory, can no longer even build an unmounter (`UnmountVolume.NewUnmounter failed`), and retries without backoff — about 590 log lines a minute — until the kubelet is restarted. Restart the kubelet instead; it cleans the directory itself.

### VolumeAttachments of the removed driver

Recognise it: `spec.attacher` is `openshift-storage.rbd.csi.ceph.com` (or `.cephfs.`), often still `status.attached=true`, held by `external-attacher/openshift-storage-rbd-csi-ceph-com`. No attacher remains to honour that finalizer.

```bash
oc get volumeattachment -o custom-columns=NAME:.metadata.name,ATTACHER:.spec.attacher,PV:.spec.source.persistentVolumeName,ATTACHED:.status.attached,FINALIZERS:.metadata.finalizers
oc delete volumeattachment <name> --wait=false
oc patch volumeattachment <name> --type merge -p '{"metadata":{"finalizers":null}}'
```

### PVs of the removed driver

Recognise it: `spec.csi.driver` is the removed driver, `volumeAttributes.clusterID` is `openshift-storage`, the StorageClass (for example `ocs-storagecluster-ceph-rbd`) no longer exists, phase `Bound` or `Released`, reclaim `Delete`, and finalizers `external-provisioner.volume.kubernetes.io/finalizer`, `kubernetes.io/pv-protection`, and `external-attacher/openshift-storage-rbd-csi-ceph-com`. No provisioner or attacher remains, and the Ceph cluster behind the volume is gone, so there is nothing for reclaim to delete. A `Bound` PV must have lost its claim first (the Pod fix above), or the claim must be one you are removing on purpose.

```bash
oc get pv -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,DRIVER:.spec.csi.driver,CLUSTERID:.spec.csi.volumeAttributes.clusterID,SC:.spec.storageClassName,CLAIM:.spec.claimRef.name,FINALIZERS:.metadata.finalizers
oc delete pv <pv> --wait=false
oc patch pv <pv> --type merge -p '{"metadata":{"finalizers":null}}'
```

### Consumer namespace stuck Terminating on bucket claims

Recognise it: an application namespace `Terminating` for weeks that still holds `ObjectBucketClaim`s **and**, for each claim, a ConfigMap and a Secret of the same name — every one with a `deletionTimestamp` and the single finalizer `objectbucket.io/finalizer`. Their StorageClasses (`openshift-storage.noobaa.io`, `ocs-storagecluster-ceph-rgw`) are gone and neither bucket provisioner runs. Only claims whose class is missing or uses an ODF provisioner (`openshift-storage.noobaa.io/obc`, `openshift-storage.ceph.rook.io/bucket`) qualify; claims served by a running upstream Rook use the same finalizer legitimately.

```bash
oc get ns | grep Terminating
oc -n <ns> get obc -o custom-columns=NAME:.metadata.name,SC:.spec.storageClassName,DELETING:.metadata.deletionTimestamp,FINALIZERS:.metadata.finalizers
oc -n <ns> get configmap,secret -o custom-columns=KIND:.kind,NAME:.metadata.name,FINALIZERS:.metadata.finalizers | grep objectbucket.io/finalizer
oc get sc <class>                                                       # expect NotFound or an openshift-storage.* provisioner

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

### Other leftovers of the same uninstall

- `csiaddonsnodes.csiaddons.openshift.io` in `openshift-storage` whose owner Pods and DaemonSets are gone: the step-4 finalizer sweep.
- Namespaced RBAC, `rook-ceph-mon-pdb`, `ocs-prometheus-rules`, and `odf-info` in a kept `openshift-storage`: step 4b.
- Stale `odf-console`/`odf-client-console` in `console.operator.openshift.io/cluster` `spec.plugins`: step 4a.
- CRDs in `replication.storage.openshift.io`, `ramendr.openshift.io`, `groupsnapshot.storage.openshift.io`, and `csiaddons.openshift.io`: step 5.
- MachineConfig `99-odf-virtio-disk-udev`: **MachineConfig Cleanup** below — decide, do not delete by reflex.

### Cluster RBAC left by ODF

ODF's operators leave ClusterRoles and ClusterRoleBindings that OLM does not collect: labelled `olm.owner=<csv>` for CSVs that no longer exist (seen: `odf-prometheus`, `odf-operator-metrics-reader`, `ocs-client-operator-metrics-reader`, eleven `ceph-csi-*-role` / `ceph-csi-metrics-reader`, `k8s-metrics-sm-prometheus-k8s`, `csi-addons-csiaddons-networkfenceclass-editor-role` and `-viewer-role`; bindings `odf-prometheus`, `ocs-metrics-exporter-hostnetwork`, `k8s-metrics-sm-prometheus-k8s`), and three with no label at all (ClusterRoles `ocs-metrics-exporter`, `ocs-metrics-reader`; ClusterRoleBinding `ocs-metrics-exporter`).

**A stale ODF label means ODF created the object, not that nothing uses it.** On the same cluster these carried ODF CSV or package labels but were in use by the running upstream Rook and had to be kept: ClusterRoleBinding `objectstorage-provisioner-role-binding` (subject ServiceAccount `rook-ceph/objectstorage-provisioner` exists) and its ClusterRole; ClusterRoleBinding `rook-ceph-metrics` (subject `openshift-monitoring/prometheus-k8s` exists) and its ClusterRole; ClusterRoles `rook-ceph-monitor` and `rook-ceph-monitor-mgr` (bound by live bindings); and the two `objectbucket.io` CRDs (used by the running Rook bucket provisioner).

Find candidates by label, across every kind, not only RBAC:

```bash
ODF_PKGS="odf-operator odf-dependencies ocs-operator ocs-client-operator rook-ceph-operator \
  cephcsi-operator mcg-operator odf-csi-addons-operator odf-external-snapshotter-operator \
  odf-prometheus-operator ocs-tls-profiles recipe"
oc get clusterrole,clusterrolebinding -l olm.owner -L olm.owner \
  | grep -E "$(echo $ODF_PKGS | tr ' ' '|')"
for r in $(oc api-resources --verbs=list -o name); do
  for pkg in $ODF_PKGS; do
    oc get "$r" -A -l "operators.coreos.com/$pkg.openshift-storage" -o name --ignore-not-found 2>/dev/null
  done
done
oc get clusterrole ocs-metrics-exporter ocs-metrics-reader --ignore-not-found
oc get clusterrolebinding ocs-metrics-exporter --ignore-not-found
```

Then decide each one by liveness, not by label:

- **A ClusterRoleBinding is dead** only if its ClusterRole is missing, or none of its ServiceAccount subjects exists. A `User` or `Group` subject cannot be proven absent — keep that binding. (Seen: `k8s-metrics-sm-prometheus-k8s` bound only a ServiceAccount in a namespace `odf-storage` that did not exist.)
- **A ClusterRole is dead** only if no live ClusterRoleBinding or RoleBinding anywhere references it and it does not aggregate into another role. A binding you have just judged dead does not keep its role alive.
- **A CRD is dead** only if it has zero instances, no workload or configuration names its group, no webhook targets it, and its owning operator is gone (step 5).

```bash
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

`post_uninstall_audit.sh` applies the same tests to ODF-labelled and known unlabelled ClusterRoles and ClusterRoleBindings: dead ones `WARN`, in-use ones print `OK: ... retained: <reason>`.

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

An uninstall with `cleanup-policy="delete"` wipes the OSD disks automatically. If the policy was not set, or you need to reclaim disks after the fact, clean each OSD disk only after explicit destructive confirmation for the exact `/dev/disk/by-id/*` target. `wipefs -af` and `sgdisk --zap-all` are sufficient for non-Ceph disks, but a disk that previously held a BlueStore OSD must clear labels at **0 / 1 GiB / 10 GiB / 100 GiB / 1000 GiB** (or be fully zeroed) — see `references/local-storage-disks.md`. Head/tail-only wipes leave the 10 GiB and 100 GiB copies and break the next install:

```bash
NODE="<node>"
DISK="/dev/disk/by-id/<stable-disk-id>"

# Standard signature and partition-table cleanup:
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  wipefs -af '${DISK}'
  sgdisk --zap-all '${DISK}'
"

# Required when the disk previously held a BlueStore OSD (fast path):
oc debug "node/${NODE}" -- chroot /host bash -ceu "
  DISK='${DISK}'
  BYTES=\$(blockdev --getsize64 \"\$DISK\")
  G=\$((1024*1024*1024))
  for mult in 0 1 10 100 1000; do
    off=\$((mult * G))
    [ \"\$off\" -ge \"\$BYTES\" ] && continue
    dd if=/dev/zero of=\"\$DISK\" bs=4096 seek=\$((off/4096)) count=256 status=none conv=fsync
  done
  sync
"

# Authoritative check — must print {}:
oc debug "node/${NODE}" --image=quay.io/ceph/ceph:v19.2.2 -- bash -c '
  mount --rbind /host/dev /dev
  ceph-volume raw list '"${DISK}"' --format json
'
```

Full-disk zeroing remains valid when policy requires total erasure; it can take a long time. See `references/local-storage-disks.md` for the BlueStore cleanup rationale.

## MachineConfig Cleanup

MachineConfig cleanup can reboot nodes. On SNO, warn about temporary API loss. Find ODF-specific MachineConfigs before deciding what to remove:

```bash
oc get machineconfig | grep -iE 'ocs|odf|rook' || true
oc get machineconfig <name> -o yaml
```

An ODF install can leave `99-odf-virtio-disk-udev` (role master on SNO; one udev rules file). Observed after an ODF 4.20.17 uninstall on an OCP 4.20.34 SNO cluster and deliberately **not** removed. Before removing it or any other ODF MachineConfig, check:

- Removal rolls the pool, which reboots every node in it — on SNO, an API outage.
- A storage system installed later on the same disks may rely on the rule (for example on the `/dev/disk/by-id` links it creates). Read the rule, then check whether the current storage's device selectors, `LocalVolumeSet`s, LVMS device paths, or Rook `CephCluster` device lists use the paths it provides:

```bash
oc get machineconfig 99-odf-virtio-disk-udev -o jsonpath='{range .spec.config.storage.files[*]}{.path}{"\n"}{.contents.source}{"\n"}{end}'
# contents.source is a data: URL; decode it locally and read the rule before deciding.
```

Remove it only when no remaining storage system depends on what it creates, in a window where the reboot is acceptable.

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
