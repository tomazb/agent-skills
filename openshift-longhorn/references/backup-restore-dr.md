# Backup Restore And DR

Use this runbook for backup targets, recurring jobs, Longhorn system backup, restore, and disaster recovery planning.

## Backup Target

For production, require a backup target before risky lifecycle actions. Prefer object storage such as S3-compatible storage when available; NFS can work but adds mount and failover considerations.

Collect:

```bash
oc -n longhorn-system get settings.longhorn.io backup-target backup-target-credential-secret -o yaml
oc -n longhorn-system get backuptargets.longhorn.io,backups.longhorn.io,backupvolumes.longhorn.io 2>/dev/null || true
```

Validate credentials, network reachability, and retention requirements before relying on backups.

## Recurring Jobs

Production volumes should have recurring backups. If a backupstore is not available, recurring snapshots are a weaker fallback and do not protect against cluster or disk loss.

Record:

- target volume selectors;
- snapshot and backup schedules;
- retention counts;
- concurrency;
- whether jobs are inherited from StorageClass parameters or Longhorn recurring job resources.

## System Backup

Create a Longhorn system backup before upgrades, uninstall planning, cluster restore exercises, or broad settings changes. A system backup preserves Longhorn custom resources and stores them in the remote backup target.

Check:

```bash
oc -n longhorn-system get systembackups.longhorn.io,systemrestores.longhorn.io 2>/dev/null || true
```

Do not describe system backup as a replacement for application-consistent backups of data inside volumes.

## Restore Planning

For volume restore:

- confirm the target StorageClass and data engine;
- check replica count and disk selectors;
- validate namespace, PVC name, access mode, and workload cutover;
- test a restored canary before restoring production.

For StatefulSets:

- preserve stable PVC naming expectations;
- scale workloads down when required;
- restore PVCs before scaling up;
- verify application-level consistency after restore.

For system restore:

- use a matching Longhorn version unless the documented restore path says otherwise;
- restore into a prepared cluster with Longhorn prerequisites satisfied;
- validate CRDs, settings, nodes, disks, engines, and StorageClasses before attaching workloads.

## DR Output

A DR answer should include recovery point objective, recovery time objective, backup target health, restore order, validation commands, and explicit data-loss assumptions.
