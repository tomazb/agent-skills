# Changelog

## 1.8.0

A post-uninstall audit that can fail, coverage for the leftovers of an interrupted
uninstall, and an uninstall runbook that no longer deletes what a co-installed ODF
uses. The topology behind it: an OCP 4.20.34 SNO cluster running an upstream
(non-OLM) Rook v1.20.5 in `rook-ceph`, LVMS sharing `openshift-storage`, and
leftovers of ODF 4.20.17, which had been removed earlier. The same mechanisms were
recorded for ODF in `openshift-odf` 1.20.0; this release applies them from the Rook side.

- **`scripts/classify_ceph_ownership.sh`: who runs Ceph, before anything shared is
  deleted.** Read-only, with a three-outcome contract: exit 0 for "upstream Rook
  only" (its namespaces on stdout) or "no Rook or ODF"; exit 1 when ODF is present
  (hand off to `openshift-odf`) or ownership is unknown, or on any lookup or
  connectivity error; exit 2 for bad arguments. ODF is present with a
  `StorageCluster`, an ODF/OCS Subscription or CSV, a `CephCluster` in
  `openshift-storage`, owned by a `StorageCluster`, or named like ODF's, a
  `rook-ceph-operator` in `openshift-storage`, or an `openshift-storage.` Ceph CSI
  driver, Driver object, or PV. A `rook-ceph-operator` Deployment outside
  `openshift-storage` that OLM did not install is upstream Rook; an OLM-installed one,
  a `CephCluster` with no such operator, and a Ceph CSI driver, Driver object, or PV
  under another prefix are unknown. Only "the server doesn't have a resource type" on
  the `CephCluster` lookup reads as none; the `StorageCluster` and `drivers.csi.ceph.io`
  kinds are read only when API discovery serves them. `oc whoami` runs first, and the
  verdict names the server it classified. `--namespace` and `--csi-prefix` select the
  Rook namespace and driver prefix; `openshift-storage` is refused for both, and ODF's
  `openshift-storage.` prefix is checked before the Rook prefix. The rule lives in
  `scripts/rook_common.sh`, shared with the audit.
- **`post_uninstall_audit.sh` rewritten: it exits nonzero on any `WARN` or `FAIL`.**
  It used to end "Audit complete." with exit 0 whatever it found. It now follows the
  `openshift-odf` audit's contract: read-only, `oc`, `jq`, and bash builtins only
  (no `grep`), `--context`/`--kubeconfig`, stdout, stderr, and exit status kept apart,
  every absent kind or API group reported as such, a successful call that prints
  nothing reported as a `FAIL` (never as "none found"), the ownership lookups as strict
  as the classifier's, and ConfigMaps and Secrets read as names and finalizers only. `--namespace` and `--csi-prefix` select the Rook
  namespace and `CSI_DRIVER_NAME_PREFIX` (default: the namespace, as in Rook).
- **Residue is matched by driver, provisioner, and ownership, not by name.** The old
  audit grepped for `rook-ceph`: it missed a PV on the Rook driver with a custom
  StorageClass name, and reported ODF's own `rook-ceph-*` objects (ClusterRoles
  `rook-ceph-metrics`, `rook-ceph-monitor`, `rook-ceph-monitor-mgr`, Role
  `rook-ceph-metrics`, PDB `rook-ceph-mon-pdb`, all `olm.owner=ocs-operator...`) as Rook
  residue. StorageClasses, PVs, VolumeSnapshotClasses, CSIDrivers, `CSINode` driver
  registrations, and VolumeAttachments are now matched by
  `<prefix>.(rbd|cephfs|nfs|nvmeof).csi.ceph.com` and `<prefix>.ceph.rook.io/bucket`; PVCs by
  a Rook StorageClass or a bound Rook PV.
- **New checks.** Ownership (a Rook operator or `CephCluster` still running, objects of
  unknown owner, ODF reported as present and not residue); the Rook namespace absent,
  or, while it exists, its pods and Rook/Ceph/CSI-named objects; namespaces, PVCs, PVs,
  and Pods deleting for over 10 minutes, by `metadata.deletionTimestamp` (a deleting
  PVC keeps phase `Bound`; there is no `Terminating` phase); the `csi.ceph.io` and
  `objectbucket.io` groups next to `ceph.rook.io`, with every instance that still holds
  them, or, with ODF present, the groups retained and only instances in the Rook
  namespace reported; ObjectBucketClaims and ObjectBuckets by StorageClass (Rook
  provisioner: residue; ODF provisioner: ODF's; class gone: residue, or for review
  when ODF is present); ConfigMaps and Secrets held by `objectbucket.io/finalizer`
  without a live claim, also after the `objectbucket.io` CRDs are gone; SCCs `rook-ceph` and `rook-ceph-csi` judged by their users and
  groups (Rook namespace: residue; `openshift-storage`: ODF's; mixed or empty: decide
  by hand); cluster RBAC by liveness; MachineConfigs named for Rook, listed for review
  without failing the audit.
- **Cluster RBAC by liveness, not by label.** A ClusterRoleBinding is dead only if its
  ClusterRole is missing or none of its ServiceAccount subjects exists (a User or Group
  subject keeps it); a ClusterRole is dead only if no live binding references it and no
  aggregation selector (matchLabels and matchExpressions with In, NotIn, Exists,
  DoesNotExist) selects it. An empty selector selects every ClusterRole, as Kubernetes
  reads it, so it keeps the role; a selector that cannot be evaluated keeps it too. A candidate
  with `olm.owner` or `operators.coreos.com/*` labels is not upstream Rook's and is
  reported with its operator, installed or not.
- **The uninstall runbook no longer deletes ODF's CRDs.** `oc delete -f
  /tmp/rook-ceph-crds.yaml` removed the `ceph.rook.io` and `objectbucket.io` CRDs (and,
  with the CSI manifests, `csi.ceph.io`) that a co-installed ODF also uses, and its
  guard only checked whether the API group existed. `rook_delete_crds` now
  re-classifies, refuses unless the verdict is "no Rook or ODF", lists every instance
  of the three groups in all namespaces and cluster-scoped, refuses while any remains,
  refuses when any CRD of those groups carries OLM labels, another Helm release's
  annotation, or is owned or required by a ClusterServiceVersion (a community
  `noobaa-operator` or a standalone ceph-csi-operator with no instance yet), and
  deletes only CRDs of exactly those groups by `spec.group`.
- **No install manifest is deleted by file.** The CRD manifest and `csi-operator.yaml`
  define CRDs, and `common.yaml`/`operator-openshift.yaml` cluster-scoped RBAC and SCCs
  whose names ODF and a second Rook share. `rook_delete_operator` now deletes by kind
  in the Rook namespace only (ceph-csi CRs, Deployments, DaemonSets, ServiceAccounts,
  Roles, RoleBindings, then the namespace); cluster-scoped RBAC and SCCs follow the
  liveness and ownership rules, and every CRD is left to `rook_delete_crds`. The
  package validator rejects any `oc`/`kubectl delete -f`/`--filename` of those
  manifests in the reference runbooks.
- **Every destructive runbook step is a function that classifies first.** An ownership
  gate (`rook_classify`) precedes Operator Uninstall. The steps that act on a running
  Rook (`rook_helm_uninstall`, `rook_set_cleanup_policy`, `rook_delete_ceph_crs`,
  `rook_delete_operator`) need a fresh "upstream Rook only" verdict naming exactly the
  Rook namespace (`rook_only`; a second Rook namespace shares cluster-scoped names);
  the steps that remove what nothing may still use (`rook_delete_crds`,
  `rook_remove_sccs`, `rook_wipe_data_dir`, `rook_wipe_osd_disk`) need a fresh "no Rook
  or ODF" verdict (`rook_gone`). The flag is set only on success and checked with the
  return status; every function refuses an empty, invalid, or `openshift-storage`
  namespace and uses `return` rather than `exit`. `rook_helm_uninstall` refuses a
  release whose manifest holds a CRD without `helm.sh/resource-policy: keep`;
  `rook_set_cleanup_policy` needs `ROOK_CONFIRM_DESTROY_DATA=yes-really-destroy-data`;
  `rook_wipe_osd_disk` takes only a `/dev/disk/by-id/` path and needs
  `ROOK_CONFIRM_WIPE_DISK` set to exactly that path. `rook_delete_ceph_crs` skips a
  kind whose CRD is not installed. `rook_list_cluster_scoped` lists StorageClasses,
  CSIDrivers, and VolumeSnapshotClasses by provisioner or driver, read-only. Deletes use `--wait=false`, followed by a bounded poll
  or an instance check, so a finalizer whose controller is gone cannot hang the step.
  `rook_clear_finalizers` is bounded to the Rook namespace instead, refuses
  `openshift-storage`, and refuses while workloads are left there.
- **`dataDirHostPath` wipe guarded.** `rook_record_data_dir` reads the path, this
  cluster's mon IDs, and the API server before the `CephCluster` is deleted.
  `rook_wipe_data_dir` removes only `<path>/<namespace>` and `<path>/mon-<id>` for those
  mons, never every child (ODF's leftover `<path>/openshift-storage` survives). It
  refuses a path that is not plain and absolute, has fewer than two components or a
  `.`/`..` component, is a system directory, or does not name `rook` (unless
  `ROOK_DATA_DIR_ANY_NAME=yes`); a path recorded on another server; and any verdict but
  "no Rook or ODF", because ODF and a second Rook keep their mon stores under
  `/var/lib/rook` by default too.
- **SCC ownership.** ODF 4.20 has SCCs named `rook-ceph` and `rook-ceph-csi`; the
  runbook now judges them by `users`, and `rook_remove_sccs` deletes only those whose
  every user is a service account of the Rook namespace.
- **New runbook section "Orphans After An Interrupted Uninstall".** The proofs to
  collect before stripping any finalizer (driver absent from `oc get csidriver` and the
  node's `CSINode`, StorageClass gone, no `CephCluster`, no Rook operator, no other Ceph
  product owning the objects) and the removal order that avoids new stuck objects: the
  Pod the kubelet cannot release (force-delete it, then restart the kubelet on that
  node; never remove `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~csi/<pv>` under
  a running kubelet, which turned a two-minute retry into about 590 log lines a minute
  without backoff), its PVC held by `kubernetes.io/pvc-protection`, VolumeAttachments
  held by `external-attacher/<prefix>-rbd-csi-ceph-com`, PVs held by
  `external-provisioner.volume.kubernetes.io/finalizer` and `kubernetes.io/pv-protection`,
  consumer namespaces held by `objectbucket.io/finalizer` on each claim and its
  same-named ConfigMap and Secret, ObjectBuckets, `csi.ceph.io` and `ceph.rook.io` CRs
  with operator finalizers, then cluster RBAC ("Cluster RBAC left by Rook") and CRDs.
- **Destructive steps tightened further.** `rook_helm_uninstall` refuses while any
  `ceph.rook.io` object is left in the Rook namespace (removing the operator would
  orphan the `CephCluster`). It parses the release manifest as YAML with
  `oc create --dry-run=client -o json` (nothing is created), flattens Lists, and
  refuses any CRD without `metadata.annotations` `helm.sh/resource-policy: keep`,
  any CRD without a readable `metadata.name`, and a manifest `oc` cannot parse; a
  keep line inside another annotation's value or a folded name reads as YAML means
  it. The live CRDs must agree: every CRD the manifest names, with or without Helm
  ownership annotations, and every live CRD that carries this release's. `rook_delete_crds` treats a CRD with either
  `meta.helm.sh/release-name` or `meta.helm.sh/release-namespace` as Helm-owned
  and accepts it only when both match this Rook, so a same-named release in
  another namespace is another product's.
  `rook_delete_operator` refuses while a ValidatingWebhookConfiguration,
  MutatingWebhookConfiguration, or APIService is served from the Rook namespace.
  `rook_clear_finalizers` strips finalizers only from objects already being deleted,
  refuses while any Deployment, DaemonSet, or StatefulSet is left in the namespace, and
  refuses while a `rook-ceph-operator` Deployment that is not being deleted exists in
  any namespace or any `app=rook-ceph-operator` pod exists, terminating ones included.
  A `CephCluster` deleted after its operator stays `Deleting` and keeps its daemon
  workloads, which block that check; new `rook_delete_ceph_daemons` deletes only the
  Deployments, DaemonSets, and StatefulSets owned by a `CephCluster` already being
  deleted, refuses while any Rook operator is left, and the refusal names it.
  `rook_record_data_dir` also records the namespace, and `rook_wipe_data_dir` refuses a
  path recorded for another namespace and warns when no mon IDs were recorded.
  `rook_wipe_osd_disk` refuses a `-part<N>` link and runs one node-side script that
  checks the disk and wipes the resolved device right after the last check, only if
  every check passed. That narrows the window between check and wipe; it does not
  lock the disk, so nothing else on the node may be claiming it meanwhile. A check
  that cannot run (a failed `readlink`, `blockdev`, read, `lsblk`, holders listing, `wipefs` probe,
  `findmnt`, `swapon`, or `pvs`, `blkid -p` with any status but 0 or 2, or no
  `pvs`) blocks the wipe, and before any probe the script proves the first and last
  MiB of the disk can be read, because a probe that cannot read reports "nothing
  found" like an empty disk. The disk must be a whole disk with no partitions,
  holders, host mount, active swap, or `pvs` entry, and the only signature `wipefs`
  and an independent `blkid -p` probe may find is `ceph_bluestore`. Every other
  signature blocks it, a partition table included, even an empty one: its backup
  copy or a hybrid MBR can list partitions that neither the primary table nor the
  kernel shows. A wipe that fails after it started is reported as possibly
  partial, not as "disk not wiped".
- **1.7.0's audit rules carried into the rewrite.** `PRIOR_DEFAULT_STORAGE_CLASS`
  keeps its meaning: unset requires exactly one default, empty accepts a cluster with
  no default, and a name must match the current default. A `rook-ceph-metrics` binding
  whose only live subject is `openshift-monitoring/prometheus-k8s` is dead once no Ceph
  runs, because that ServiceAccount exists on every OpenShift cluster. It is kept
  while upstream Rook, ODF, or a Ceph object of unknown owner remains, or when
  ownership could not be classified. A subject listed twice counts once.
- **An audit or classification that cannot name its cluster fails.** When
  `oc whoami --show-server` fails or prints nothing, `post_uninstall_audit.sh` reports
  `FAIL` and exits 1, and `classify_ceph_ownership.sh` stops with "unknown"; both used
  to go on against "unknown server".
- Tests: 65 to 449. The classifier, every audit check (residue, clean, and kind-absent
  variants), and the runbook functions, extracted verbatim from the markdown, run
  against a fake `oc` driven by a cluster description.

## 1.7.0

- The post-uninstall audit warns when `rook-ceph` ClusterRoles remain after both `rook-ceph` and `openshift-storage` are gone. `rook-ceph-metrics` bound only to `openshift-monitoring/prometheus-k8s` is residue in that case and stays while either namespace still runs Ceph.
- `PRIOR_DEFAULT_STORAGE_CLASS` records the pre-install default, including when there was none, so a cluster that started without a default StorageClass is not reported as unfinished.
- Uninstall states that finalizer `csi.ceph.com/cleanup` on `clientprofiles.csi.ceph.io` does not clear itself after the CSI operator Deployment is gone, and that those objects have to be deleted while the operator is still running.
- `oc wait --for=jsonpath` that fails with `unrecognized condition` is polled by field instead of treated as a failed object.

## 1.6.0

- Added **VM storage defaults and CDI StorageProfiles** guidance in `references/vm-storage-profiles.md`: the two-default model (`storageclass.kubernetes.io/is-default-class` for general PVCs vs `storageclass.kubevirt.io/is-default-virt-class` for CDI/KubeVirt VirtualMachine disks), StorageProfile `claimPropertySets` priority and block-mode RBD tuning, resolving the `CDIStorageProfilesIncomplete` alert for unrecognized provisioners (for example `rook-ceph.nfs.csi.ceph.com`), and the operator-reconcile gotcha when moving a default between Rook and another operator (LVMS re-pins `is-default-class` from `LVMCluster`/`LVMVolumeGroup` `default`).
- Cross-linked `references/rbd-block-pools.md` and `references/cephfs-filesystem.md` to the VM storage reference.
- Extended the package validator and tests to enforce the new VM storage profile guidance.

## 1.5.0
- Addressed PR review feedback: made preflight/uninstall commands runnable (no shell-invalid placeholders, non-repeatable `--api-group` split, `/dev/rbd[0-9]*` glob, per-path stale-dir checks), discover ceph-csi version pre-install from the operator image-set, read `dataDirHostPath` instead of hardcoding `/var/lib/rook`, use `--wait=false` and a converging reconciler-stop loop in ODF teardown, gate destructive zeroing on confirmed abandonment, route 4.20.17 health checks off the toolbox, and bind the 4.20.17 validator check to its section.
- Added **stale krbd device** detection and remediation, learned from a live Rook→ODF→Rook round-trip on SNO. A prior teardown that deleted an RBD-backed PVC (or its namespace) before the volume was unmapped — or destroyed the pool under a mapped image — leaves a wedged `/dev/rbdN` that hangs a new Rook OSD prepare forever at `ceph-volume raw list`. `references/install-and-preflight.md` now checks `/dev/rbd*` and `/sys/bus/rbd/devices`, and `references/maintenance-uninstall.md` adds a "Stale krbd Devices" section (drain consumers first, `rbd unmap`, and reboot/power-cycle a wedged VM).
- Fixed the leftover-detection `/var/lib/rook` check to count entries instead of relying on `ls` exit code (an empty dir returns 0, a false "stale" positive).
- Extended the package validator and tests to enforce the krbd guidance.

## 1.4.0

- Added a **Leftover Install Detection (Rook or ODF)** preflight to `references/install-and-preflight.md` that checks for a prior Rook *or* ODF footprint — leftover namespaces, CRDs (`ceph.rook.io`/`ocs.openshift.io`/`csi.ceph.io`/`noobaa.io`), orphaned StorageClasses/CSIDrivers/SCCs, stale `/var/lib/rook/mon-*` dirs, and residual BlueStore disk labels — before deploying, with a cleanup handoff.
- Added **Ceph Version And ceph-csi Compatibility** guidance: pin `cephVersion.image` to a Ceph release whose cephx key cipher the deployed ceph-csi can decode. Documents the Tentacle `v20.2.4` AES256K vs ceph-csi v3.17 (librados 20.2.1) incompatibility that fails CSI provisioning with `failed to decode key` / `rados: ret=-22` while RGW/OBC keeps working, and recommends Squid `v19.2.2`.
- Extended `references/maintenance-uninstall.md` with `cephnfs` teardown ordering, stuck `clientprofiles.csi.ceph.io` finalizer clearing that blocks namespace deletion, removal of orphaned cluster-scoped StorageClasses/CSIDriver objects, and `/var/lib/rook` clearing on each node.
- Extended the package validator and tests to enforce the new leftover-detection, version-compatibility, and uninstall-cleanup guidance.

## 1.3.0

- Added Product Ownership Gate for Rook vs ODF classification, openshift-versions handoff, and concrete helper invocations in install/validation runbooks.

## 1.2.0

- Updated the direct-manifest install and upgrade runbooks to create `rook-ceph` explicitly, apply `csi-operator.yaml`, and explain the `CephConnection` reconciliation failure when the `csi.ceph.io/v1` resources are missing.
- Reworked the SNO guidance around explicit `/dev/disk/by-id/...` device pinning, validated `cephConfig.global` defaults, and the `ceph mgr module enable rook` / `ceph orch set backend rook` backend step.
- Expanded RGW, dashboard, and validation guidance with OpenShift Route details, OBC validation, persistent internal Prometheus fallback, and `mon_max_pg_per_osd` advice for single-OSD SNO clusters.
- Refreshed the validated SNO evidence and extended the package validator/tests to enforce the new install, monitoring, and orchestrator guidance.

## 1.1.0

- Fixed CephObjectStore examples: removed the invalid `gateway.type` field, corrected the SNO gateway `placement` structure, and switched RGW to non-privileged ports (8080/8443) so it runs as non-root on OpenShift.
- Reworked RGW TLS/Route guidance: edge termination by default, with passthrough/reencrypt requiring `securePort` + `sslCertificateRef` (or the OpenShift service serving-cert).
- Led the OpenShift install with `operator-openshift.yaml` (dedicated `rook-ceph` SCC, `ROOK_HOSTPATH_REQUIRES_PRIVILEGED`); corrected the manual SCC fallback to include `rook-ceph-rgw` and `rook-ceph-default`.
- Rewrote PG planning around the PG autoscaler (on by default since Octopus) and corrected the inaccurate "pool parameters are immutable" claim.
- Added server-side CRD apply guidance, Rook-native `cleanupPolicy` disk-wipe, and Helm operator-vs-cluster clarification.
- Added validator regression checks and tests covering the fixed anti-patterns.

## 1.0.0

- Initial release of the OpenShift Rook Ceph lifecycle skill.
- Covers discovery, install, OSD disk prep, RBD, CephFS, RGW, cluster expand/shrink, upgrade, backup/restore, maintenance, uninstall, validation, hardening, and troubleshooting.
