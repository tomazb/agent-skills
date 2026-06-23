# Changelog

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
