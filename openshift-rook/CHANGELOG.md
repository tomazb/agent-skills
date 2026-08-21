# Changelog

## 1.5.0

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
