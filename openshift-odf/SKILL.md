---
name: openshift-odf
description: Use when planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, or troubleshooting Red Hat OpenShift Data Foundation (ODF) on OpenShift/OKD — including Single Node OpenShift, multi-node clusters, internal mode with Local Storage Operator disks, StorageCluster sizing, ceph-rbd block, cephfs shared filesystem, Multicloud Object Gateway (MCG/NooBaa) and RGW object storage, OLM operator lifecycle, and default StorageClass safety.
---

# OpenShift Data Foundation Lifecycle

Use this skill as a lifecycle router for Red Hat OpenShift Data Foundation (ODF) on OpenShift/OKD. Do live discovery first, choose the relevant reference runbook, and write an actionable plan or command sequence with explicit safety gates. ODF is the productized, OLM-managed distribution of Ceph (via Rook) and the Multicloud Object Gateway; manage it through the `odf-operator`/`ocs-operator` and the `StorageCluster` CR, not through raw upstream Rook manifests.

## Routing

- **Discovery, install, or prerequisite planning**: start with `references/install-and-preflight.md`.
- **Dedicated disk preparation with the Local Storage Operator**: use `references/local-storage-disks.md`.
- **ceph-rbd block StorageClasses and pools**: use `references/block-rbd.md`.
- **cephfs shared filesystem StorageClasses**: use `references/cephfs-filesystem.md`.
- **Object storage with MCG/NooBaa and RGW**: use `references/object-mcg-rgw.md`.
- **Capacity expansion, node addition, or device set scaling**: use `references/cluster-expand-shrink.md`.
- **ODF operator or Ceph version upgrades**: use `references/upgrade.md`.
- **Backup, DR (Regional/Metro-DR), and snapshot planning**: use `references/backup-restore-dr.md`.
- **Maintenance, node drain, OSD replacement, operator uninstall, or cluster removal**: use `references/maintenance-uninstall.md`.
- **Validation, hardening, post-reboot drift checks, or troubleshooting**: use `references/validation-hardening.md`.
- **Observed SNO configurations or ODF 4.22 SNO regression workarounds**: use `references/validated-odf-sno.md` as version-scoped evidence, not as a universal default.

## Core Safety Rules

- Never run or recommend destructive disk-wiping commands such as `ceph-volume lvm zap`, `wipefs -a`, `sgdisk --zap-all`, `dd`, `mkfs`, or any OSD disk partitioning before the user gives explicit destructive confirmation for the exact target disk and intent.
- Before every destructive disk action, require `readlink -f`, `lsblk -f`, `wipefs -n`, and `ceph-volume lvm list` evidence for the target.
- Use stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` paths for destructive block-device targeting. Never use `/dev/sdX`, `/dev/nvmeXnY`, or guessed paths. Prefer the Local Storage Operator `LocalVolumeSet`/`LocalVolumeDiscovery` to select disks by stable device attributes instead of naming raw kernel devices.
- Install and upgrade ODF only through OLM: an OperatorHub `Subscription` in the `openshift-storage` namespace. Never apply upstream Rook `operator.yaml`/`crds.yaml` on top of an ODF-managed cluster; it corrupts the CSV/operator state.
- Do not edit the Rook `CephCluster`, `CephBlockPool`, `CephFilesystem`, or `CephObjectStore` CRs directly on an ODF cluster. `ocs-operator` owns and reconciles them from the `StorageCluster` CR; hand edits are reverted and can break reconciliation. Change behavior through `StorageCluster` (and documented overrides) instead.
  - **Exception (ODF 4.22 SNO only):** ODF 4.22 has a known regression where pool replica sizes are not reduced for single-OSD SNO deployments. After setting `managedResources.cephBlockPools.reconcileStrategy: ignore` and `managedResources.cephObjectStores.reconcileStrategy: ignore` in the `StorageCluster`, it is necessary to patch the `CephBlockPool` and `CephObjectStore` CRs directly and set pool sizes via `ceph osd pool set`. Do not enable CephFS with this workaround: its pool-reconciliation path was not validated for ODF 4.22 SNO. Document this as a temporary workaround and re-enable `reconcileStrategy: manage` when ODF is upgraded to a version with the fix.
- Warn that MachineConfig changes and node drains can reboot nodes. On SNO, that removes API access until the single node returns; wait for MCP recovery and node readiness before continuing.
- ODF on SNO uses a single replica-1 device set with `replica: 1` (`resiliencePolicy` reduced) and reduced mon/mgr counts. A compact three-node cluster remains a multi-node deployment and uses the standard three OSDs across three failure domains. Do not copy single-node settings into a compact or other multi-node production plan without explicit direction.
- Multi-node production requires at least three OSDs spread across three failure domains and the default replica count of 3 for Ceph data pools. Document explicit exceptions when the user overrides.
- Keep exactly one default StorageClass unless the user explicitly requests another policy. Discover the current default from the `storageclass.kubernetes.io/is-default-class` annotation; do not assume whether an ODF StorageClass is default on the target platform.
- Ceph pool parameters are changeable but disruptive, not immutable: `pg_num` (the PG autoscaler is on by default), replica `size`, and failure-domain rules can be modified, but changes trigger expensive rebalancing. Plan them at `StorageCluster` creation time and change them deliberately after verifying cluster health.
- Do not downgrade the ODF operator or Ceph versions. For upgrades, verify all PGs are active+clean and OSDs are up before proceeding.
- Document the difference between the ODF operator channel/version and the Ceph (cluster image) version. ODF bundles a specific Ceph version per release; do not mix-and-match.

## Required Source Checks

For install, upgrade, OSD operations, and operator changes, verify the current Red Hat OpenShift Data Foundation documentation, release notes, and the ODF/OpenShift interoperability matrix when network access is available. Use pinned version docs for commands and live cluster discovery for the installed version; do not assume a specific ODF channel such as `stable-4.16` is the target unless the user asks for it or the cluster already runs it.

## Inputs To Collect

- Cluster topology: SNO, compact (3-node), or multi-node; OpenShift/OKD version; node roles; target MachineConfigPool; and failure domain layout (host, rack, zone, or datacenter).
- Deployment mode: internal (ODF-managed OSDs on local/attached disks), internal-attached with the Local Storage Operator, or external (connecting to an existing Ceph cluster).
- Current ODF state: absent, operator installed, `StorageCluster` exists, installed ODF/Ceph versions, mon/mgr/osd counts, pool health, StorageClasses, and any existing MCG/RGW object stores.
- Target storage services: ceph-rbd block, cephfs shared filesystem, MCG/RGW object, or a combination.
- Target lifecycle action: install, disk prep, block pool, filesystem, object store, capacity expand, upgrade, backup/restore, maintenance, OSD replace, uninstall, cluster removal, validation, hardening, or troubleshooting.
- Target disk inventory by node, preferably `/dev/disk/by-id/*`, plus whether each disk may be destroyed and whether it is raw (unpartitioned, no signatures) or already has data.
- Replica policy, device set count/replica, failure-domain rules, default StorageClass intent, backup/restore requirements, and maintenance window constraints.

## Output Expectations

- Start with discovered facts, assumptions, and safety gates.
- Name the exact reference runbook(s) used.
- Separate read-only discovery from mutating or destructive actions.
- Show commands with placeholders for cluster-specific values instead of fabricating node, disk, or version identifiers.
- Drive changes through the `StorageCluster` CR and OLM Subscription; never hand-edit the ODF-owned Rook CRs except for the version-scoped ODF 4.22 SNO pool workaround in Core Safety Rules and `references/validated-odf-sno.md`.
- Include post-change validation and rollback or stop conditions.
- For production work, include backup, monitoring, and restore validation guidance.
