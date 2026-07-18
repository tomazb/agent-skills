---
name: openshift-rook
description: Use when planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, or troubleshooting Rook Ceph on OpenShift/OKD — including Single Node OpenShift, multi-node clusters, dedicated block disks for OSDs, CephBlockPool RBD, CephFS filesystem, CephObjectStore RGW/S3, host networking, device discovery, stretch clusters, PG/PGP tuning, and operator lifecycle safety.
---

# OpenShift Rook Ceph Lifecycle

Use this skill as a lifecycle router for Rook Ceph on OpenShift/OKD. Do live discovery first, choose the relevant reference runbook, and write an actionable plan or command sequence with explicit safety gates.

## Product Ownership Gate

Before any install, upgrade, or remediation plan, classify who owns Ceph on the cluster with read-only discovery:

1. Check for a `StorageCluster` and ODF/OCS `Subscription` or CSV evidence.
2. Check for a `CephCluster` and whether Rook/ODF is reconciling it.
3. Do not treat namespace presence alone (`rook-ceph`, `openshift-storage`) as ownership proof.

Classify ownership as **ODF**, **upstream Rook**, **mixed/conflicting**, or **unknown**:

- **ODF**: `StorageCluster` plus ODF/OCS Subscription/CSV evidence → stop Rook mutation planning and hand off to `openshift-odf`.
- **Upstream Rook**: `CephCluster` without ODF ownership signals → continue with this skill.
- **Mixed/conflicting** or **unknown/insufficient access**: stop, report the evidence, and refuse mutating or destructive actions until ownership is resolved.

Never recommend applying upstream Rook manifests, wiping disks, or editing Ceph CRs until ownership is classified.

## Routing

- **Discovery, install, or prerequisite planning**: start with `references/install-and-preflight.md`.
- **Dedicated disk preparation for OSDs**: use `references/osd-disk-prep.md`.
- **RBD block storage pools and StorageClasses**: use `references/rbd-block-pools.md`.
- **CephFS filesystem pools and StorageClasses**: use `references/cephfs-filesystem.md`.
- **CephObjectStore (RGW/S3) setup**: use `references/rgw-object-store.md`.
- **Cluster expansion, shrink, or rebalancing**: use `references/cluster-expand-shrink.md`.
- **Rook upgrade or Ceph version selection**: use `references/upgrade.md`.
- **Backup, DR, and snapshot planning**: use `references/backup-restore-dr.md`.
- **Maintenance, node eviction, OSD replacement, operator uninstall, or cluster destruction**: use `references/maintenance-uninstall.md`.
- **Validation, hardening, post-reboot drift checks, or troubleshooting**: use `references/validation-hardening.md`.

## Core Safety Rules

- Never run or recommend `ceph-volume lvm zap`, `wipefs`, `sgdisk --zap-all`, `dd`, `mkfs`, or any OSD disk partitioning before the user gives explicit destructive confirmation for the exact target disk and intent.
- Before every destructive disk action, require `readlink -f`, `lsblk -f`, `wipefs -n`, and `ceph-volume lvm list` evidence for the target.
- Use stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` paths for destructive block-device targeting. Never use `/dev/sdX`, `/dev/nvmeXnY`, or guessed paths.
- Warn that MachineConfig changes and node drains can reboot nodes. On SNO, that removes API access until the single node returns; wait for MCP recovery and node readiness before continuing.
- Rook Ceph on SNO requires `mon.count: 1`, `mgr.count: 1`, `allowMultiplePerNode: true` under both `spec.mon` and `spec.mgr`, and reduced replica counts. Do not copy these SNO-only settings into multi-node production plans without explicit direction.
- Multi-node production requires at least three mons, three OSDs across failure domains, and a minimum replica count of 3 for Ceph data pools. Document explicit exceptions when the user overrides.
- Keep exactly one default StorageClass unless the user explicitly requests another policy.
- Ceph pool parameters are changeable but disruptive, not immutable: `pg_num` (the PG autoscaler is on by default), replica `size`, and failure-domain rules can all be modified on existing pools, but changes trigger rebalancing that is expensive and can degrade performance. Plan them at creation time and change them deliberately after verifying cluster health.
- For Rook operator updates, prefer the Operator Lifecycle Manager (OLM) path when the cluster uses OLM. For direct manifest installs, use version-pinned manifests and never apply a newer Rook manifest without reading the release notes and upgrade guide.
- Do not downgrade Rook operator or Ceph versions. For major version upgrades, verify all PGs are active+clean and OSDs are up before proceeding.
- Document the difference between Rook (operator) version and Ceph (cluster image) version. They can be upgraded independently, but each has documented compatibility.

## Required Source Checks

For install, upgrade, OSD operations, and operator changes, verify the current Rook Ceph docs and release notes when network access is available. Use pinned version docs for commands and live cluster discovery for the installed version; do not assume `v1.15` or `v18.2` is the target unless the user asks for it or the cluster already runs it.

For OpenShift channel, patch, or one-hop upgrade-path questions, use `openshift-versions`. Release availability is not cluster upgrade readiness and is not Rook/Ceph product compatibility.

## Inputs To Collect

- Cluster topology: SNO or multi-node, OpenShift/OKD version, node roles, target MachineConfigPool, and failure domain layout (host, rack, zone, or datacenter).
- Current Rook Ceph state: absent, operator installed, CephCluster CR exists, installed versions, mon/mgr/osd counts, pool health, StorageClasses, and any existing RGW/CephFS.
- Target storage services: RBD block, CephFS shared filesystem, RGW object/S3, or a combination.
- Target lifecycle action: install, OSD disk prep, RBD pool, CephFS pool, RGW object store, cluster expand, upgrade, backup/restore, maintenance, OSD replace, uninstall, cluster destroy, validation, hardening, or troubleshooting.
- Target disk inventory by node, preferably `/dev/disk/by-id/*`, plus whether each disk may be destroyed and whether it is raw (unpartitioned, no signatures) or already has data.
- Replica policy, PG counts, failure-domain rules, default StorageClass intent, backup/restore requirements, and maintenance window constraints.

## Output Expectations

- Start with discovered facts, assumptions, and safety gates.
- Name the exact reference runbook(s) used.
- Separate read-only discovery from mutating or destructive actions.
- Show commands with placeholders for cluster-specific values instead of fabricating node, disk, or version identifiers.
- Include post-change validation and rollback or stop conditions.
- For production work, include backup, monitoring, and restore validation guidance.
