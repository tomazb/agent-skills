# OpenShift Data Foundation Lifecycle

Red Hat OpenShift Data Foundation (ODF) lifecycle skill for OpenShift/OKD covering discovery, OLM install, Local Storage Operator disk preparation, ceph-rbd block, cephfs filesystem, MCG/NooBaa and RGW object storage, capacity expansion, upgrade, backup/restore/DR, maintenance, uninstall, validation, hardening, and troubleshooting. ODF is managed through the `odf-operator`/`ocs-operator` and the `StorageCluster` CR, not through raw upstream Rook manifests.

The package includes renderers for `StorageCluster` and RBD/CephFS smoke manifests, plus a post-uninstall audit. `references/validated-odf-sno.md` records observed SNO configurations and ODF 4.22-only workarounds; revalidate them against the target release before use.

Current version: **1.1.0**
