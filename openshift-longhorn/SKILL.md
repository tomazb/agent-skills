---
name: openshift-longhorn
description: Use when discovering, planning, installing, validating, hardening, upgrading, migrating, backing up, restoring, maintaining, uninstalling, or troubleshooting Longhorn on OpenShift/OKD — including Single Node OpenShift, dedicated disk preparation, V1 filesystem data disks, V2 block/SPDK data engine, oauth-proxy handling, SCC/MachineConfig workflows, StorageClass defaulting, and lifecycle safety.
---

# OpenShift Longhorn Lifecycle

Use this skill as a lifecycle router for Longhorn on OpenShift/OKD. Do live discovery first, choose the relevant reference runbook, and write an actionable plan or command sequence with explicit safety gates.

Treat `references/validated-v2-ocp422-sno.md` as observed evidence for one OpenShift 4.22 SNO / Longhorn v1.12.0 V2 scenario. Do not turn those host-specific values into defaults without confirming the target cluster.

## Routing

- **Discovery, install, or prerequisite planning**: start with `references/install-and-preflight.md`.
- **V1 Data Engine with filesystem disks**: use `references/v1-filesystem.md`.
- **V2 Data Engine, SPDK, NVMe/TCP, or raw block disks**: use `references/v2-block-data-engine.md`.
- **V1 to V2 or V2 to V1 migration**: use `references/migration-v1-v2.md`.
- **Longhorn upgrade or version selection**: use `references/upgrade.md`.
- **Backup target, system backup, restore, or DR planning**: use `references/backup-restore-dr.md`.
- **Node maintenance, disk removal, SCC cleanup, MachineConfig cleanup, or uninstall**: use `references/maintenance-uninstall.md`.
- **Validation, hardening, post-reboot drift checks, or troubleshooting**: use `references/validation-hardening.md`.

## Core Safety Rules

- Never run or recommend `mkfs`, `wipefs`, partitioning, mount removal, or Longhorn uninstall until the user gives explicit destructive confirmation for the exact target and intent.
- Before every destructive disk action, require `readlink -f`, `lsblk -f`, `findmnt`, and `wipefs -n` evidence for the target.
- Use stable `/dev/disk/by-id/*` paths for destructive block-device targeting. Use labels such as `/dev/disk/by-label/longhorn` or `LABEL=longhorn` only for filesystem mounts.
- Warn that MachineConfig changes can reboot nodes. On SNO, that can temporarily remove API access; wait for MCP recovery and node readiness before continuing.
- Keep exactly one default StorageClass unless the user explicitly requests another policy.
- On SNO, use one Longhorn replica unless the user explicitly accepts degraded or unschedulable behavior from a higher replica count. Do not copy SNO single-replica defaults into multi-node production plans without explicit direction.
- Treat StorageClass parameters as effectively immutable for existing volumes. Recreate or create a new StorageClass when changing `numberOfReplicas`, `dataEngine`, selectors, or related behavior.
- Use YAML-aware manifest patching for OpenShift oauth-proxy image updates. Prefer Helm values or a YAML parser; do not rely on blind text replacement for production instructions.
- For `longhornctl check preflight --enable-spdk` on OpenShift, grant privileged SCC only temporarily to `system:serviceaccount:longhorn-system:longhorn-preflight-checker`, then remove it after the preflight DaemonSet completes.
- Do not downgrade Longhorn and do not skip unsupported minor versions. For V2 upgrades, verify all V2 Data Engine volumes are detached and replicas are stopped before upgrading.

## Required Source Checks

For install, upgrade, uninstall, and V2 planning, verify the current Longhorn docs and release notes when network access is available. Use pinned version docs for commands and live cluster discovery for the installed version; do not assume `v1.12.0` is the target unless the user asks for it or the cluster already runs it.

For OpenShift channel, patch, or one-hop upgrade-path questions, use `openshift-versions`. Release availability is not cluster upgrade readiness and is not Longhorn product compatibility.

## Inputs To Collect

- Cluster topology: SNO or multi-node, OpenShift/OKD version, node roles, and target MachineConfigPool.
- Current Longhorn state: absent, partially installed, installed version, data engines enabled, volume health, StorageClasses, and backup target.
- Target lifecycle action: install, V1 filesystem, V2 block, migration, upgrade, backup/restore, maintenance, uninstall, validation, hardening, or troubleshooting.
- Target disk inventory by node, preferably `/dev/disk/by-id/*`, plus whether each disk may be destroyed.
- Replica policy, default StorageClass intent, backup/restore requirements, and maintenance window constraints.

## Output Expectations

- Start with discovered facts, assumptions, and safety gates.
- Name the exact reference runbook(s) used.
- Separate read-only discovery from mutating or destructive actions.
- Show commands with placeholders for cluster-specific values instead of fabricating node, disk, or version identifiers.
- Include post-change validation and rollback or stop conditions.
- For production work, include backup, monitoring, and restore validation guidance.
