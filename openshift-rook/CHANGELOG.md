# Changelog

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
