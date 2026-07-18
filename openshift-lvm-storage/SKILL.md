---
name: openshift-lvm-storage
description: Use when planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, or troubleshooting LVM Storage (LVMS) on OpenShift/OKD — including Single Node OpenShift, multi-node clusters, volume group provisioning, thin pool configuration, TopoLVM CSI filesystem and raw block volumes, volume group expansion, disk management, StorageClass defaulting, and lifecycle safety.
---

# OpenShift LVM Storage Lifecycle

Use this skill as a lifecycle router for LVM Storage (LVMS) on OpenShift/OKD. Do live discovery first, choose the relevant reference runbook, and write an actionable plan or command sequence with explicit safety gates.

## Routing

- **Discovery, install, or prerequisite planning**: start with `references/install-and-preflight.md`.
- **Volume group provisioning, thin pool configuration, and disk management**: use `references/volume-group-provisioning.md`.
- **Filesystem volumes (ext4/xfs) via TopoLVM CSI**: use `references/filesystem-volumes.md`.
- **Raw block volumes via TopoLVM CSI**: use `references/block-volumes.md`.
- **Volume group expansion, disk addition/removal, or shrink**: use `references/expand-shrink.md`.
- **LVMS operator or TopoLVM CSI upgrade**: use `references/upgrade.md`.
- **Backup target, restore, or DR planning for local storage**: use `references/backup-restore-dr.md`.
- **Node maintenance, disk removal, VG cleanup, operator uninstall, or cluster cleanup**: use `references/maintenance-uninstall.md`.
- **Validation, hardening, post-reboot drift checks, or troubleshooting**: use `references/validation-hardening.md`.

## Core Safety Rules

- Never run or recommend `pvcreate`, `vgcreate`, `vgremove`, `lvremove`, `wipefs`, partitioning, or LVMS uninstall until the user gives explicit destructive confirmation for the exact target disk and intent.
- Before every destructive disk action, require `readlink -f`, `lsblk -f`, `pvs`, `vgs`, `lvs`, and `wipefs -n` evidence for the target.
- Use stable `/dev/disk/by-id/*` or `/dev/disk/by-path/*` paths for destructive block-device targeting. Never use `/dev/sdX`, `/dev/nvmeXnY`, or guessed paths.
- Warn that `LVMCluster` changes and node-level VG operations can disrupt running workloads. On SNO, warn that node maintenance removes API access until the single node returns.
- Keep exactly one default StorageClass unless the user explicitly requests another policy.
- On SNO, use one TopoLVM replica or document the single-node constraint. Do not copy SNO single-node defaults into multi-node production plans without explicit direction.
- `volumeBindingMode: WaitForFirstConsumer` is required for TopoLVM so capacity-aware scheduling works. Do not change this to `Immediate` on TopoLVM StorageClasses.
- Do not downgrade the LVMS operator. For major upgrades, verify all `LogicalVolume` CRs are healthy and all PVCs are bound before upgrading.
- Document the difference between LVMS operator version and TopoLVM CSI driver version when applicable.
- Thin pool over-provisioning risks running out of physical space. Monitor thin pool usage and set alerts before the pool reaches critical capacity.

## Required Source Checks

For install, upgrade, and uninstall operations, verify the current LVMS / TopoLVM docs and release notes when network access is available. Use pinned version docs for commands and live cluster discovery for the installed version; do not assume the latest version is the target unless the user asks for it or the cluster already runs it.

For OpenShift channel, patch, or one-hop upgrade-path questions, use `openshift-versions`. Release availability is not cluster upgrade readiness and is not LVMS product compatibility.

## Inputs To Collect

- Cluster topology: SNO or multi-node, OpenShift/OKD version, node roles, target MachineConfigPool.
- Current LVMS state: absent, operator installed, `LVMCluster` CR exists, installed versions, VG health, thin pool usage, StorageClasses, `LogicalVolume` CRs.
- Target lifecycle action: install, VG provisioning, filesystem volume, block volume, expand/shrink, upgrade, backup/restore, maintenance, uninstall, validation, hardening, or troubleshooting.
- Target disk inventory by node, preferably `/dev/disk/by-id/*`, plus whether each disk may be destroyed and whether it is raw or already has LVM signatures.
- Thin provisioning policy (over-provisioning ratio, `thinLvPercent`, `sizePercent`, spare GB), default StorageClass intent, filesystem type (ext4/xfs), volume mode (filesystem vs block), backup/restore requirements, and maintenance window constraints.

## Output Expectations

- Start with discovered facts, assumptions, and safety gates.
- Name the exact reference runbook(s) used.
- Separate read-only discovery from mutating or destructive actions.
- Show commands with placeholders for cluster-specific values instead of fabricating node, disk, or version identifiers.
- Include post-change validation and rollback or stop conditions.
- For production work, include backup, monitoring, and restore validation guidance.
