# Changelog

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
