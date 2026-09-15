# OpenShift Data Foundation Lifecycle

Red Hat OpenShift Data Foundation (ODF) lifecycle skill for OpenShift/OKD covering discovery, OLM install, Local Storage Operator disk preparation, ceph-rbd block, cephfs filesystem, MCG/NooBaa and RGW object storage, ODF console plugin enablement, capacity expansion, upgrade, backup/restore/DR, maintenance, uninstall, validation, hardening, and troubleshooting. ODF is managed through the `odf-operator`/`ocs-operator` and the `StorageCluster` CR, not through raw upstream Rook manifests.

The package includes renderers for `StorageCluster`, RBD/CephFS smoke manifests, and a console-plugin merge patch helper, plus a post-uninstall audit. `references/validated-odf-sno.md` records observed SNO configurations and ODF 4.20 and 4.22 SNO workarounds; revalidate them against the target release before use. Use `references/console-plugin.md` when **Storage → Data Foundation** is missing after a CLI install.

Current version: **1.17.2**
