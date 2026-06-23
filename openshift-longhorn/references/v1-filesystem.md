# V1 Filesystem Data Engine

Use this runbook for Longhorn V1 Data Engine deployments that store replica data on filesystem-mounted disks.

## Target Shape

- `iscsid.service` enabled and active on every Longhorn node.
- Dedicated storage uses ext4 or XFS on a filesystem path such as `/var/mnt/longhorn`.
- The host mount is persisted through MachineConfig on OpenShift/RHCOS.
- V2/SPDK-only host configuration such as hugepage kernel arguments and
  `/etc/modules-load.d/longhorn-v2-spdk.conf` is absent unless the user is
  deliberately testing a mixed host-prep transition.
- SNO uses `numberOfReplicas: "1"` and `default-replica-count` set to one replica. Multi-node production normally uses two or three replicas.
- Exactly one default StorageClass exists when defaulting is requested.

For a non-production smoke test, V1 can use `/var/lib/longhorn` on the root
filesystem when the user accepts that it is not a dedicated data disk. Do not
claim dedicated-disk validation unless `/var/mnt/longhorn` is a real mount.

## V1 Preflight

Run the generic Longhorn preflight and keep the result scoped to V1 host
requirements:

```bash
longhornctl --kubeconfig "${KUBECONFIG}" check preflight
```

Do not use `--enable-spdk` for a V1-only check. That flag belongs to the V2
Data Engine path and can fail on hosts that are valid for V1 filesystem disks.

On OpenShift, if the preflight checker is blocked by SCC, use the temporary
`longhorn-preflight-checker` privileged SCC workflow from
`install-and-preflight.md`, then remove the SCC grant after the preflight.

## Destructive Disk Gate

Formatting a disk requires explicit destructive confirmation for the exact `/dev/disk/by-id/*` path. Before every `mkfs`, collect:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  readlink -f '${DISK}'
  lsblk -f '${DISK}'
  findmnt -S '${DISK}' || true
  wipefs -n '${DISK}' || true
"
```

Only after confirmation:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  mkfs.ext4 -F -L longhorn '${DISK}'
"
```

## Persist The Mount

On SNO, the MachineConfigPool role is usually `master`; on multi-node clusters it is usually `worker` or a storage-specific pool. Warn that MachineConfig can reboot nodes and wait for MCP recovery.

```yaml
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  name: 80-longhorn-prereqs-master
  labels:
    machineconfiguration.openshift.io/role: master
spec:
  config:
    ignition:
      version: 3.5.0
    systemd:
      units:
      - name: iscsid.service
        enabled: true
      - name: var-mnt-longhorn.mount
        enabled: true
        contents: |
          [Unit]
          Description=Mount Longhorn data disk
          Before=local-fs.target

          [Mount]
          What=/dev/disk/by-label/longhorn
          Where=/var/mnt/longhorn
          Type=ext4
          Options=rw,relatime,discard

          [Install]
          WantedBy=local-fs.target
```

Validate after the MCP settles:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  systemctl is-active iscsid
  findmnt /var/mnt/longhorn
  df -h /var/mnt/longhorn
"
```

If reusing an existing labeled filesystem, verify it is mounted before
installing Longhorn:

```bash
oc debug "node/${NODE}" -- chroot /host bash -c "
  set -e
  systemctl is-active iscsid
  findmnt /var/mnt/longhorn
  lsblk -f
"
```

If `/var/mnt/longhorn` is only a directory on the root filesystem, either stop
for explicit disk formatting confirmation or run a root-backed smoke test using
`/var/lib/longhorn` and label the result as non-production.

## Default Disk Discovery

Configure node annotations before Longhorn manager first starts when possible:

```bash
oc annotate node "${NODE}" --overwrite \
  node.longhorn.io/default-disks-config='[{"path":"/var/mnt/longhorn","allowScheduling":true,"tags":["dedicated"]}]'

oc label node "${NODE}" --overwrite \
  node.longhorn.io/create-default-disk=config
```

Set or preserve:

```bash
oc -n longhorn-system patch settings.longhorn.io create-default-disk-labeled-nodes \
  --type=merge -p '{"value":"true"}'
oc -n longhorn-system patch settings.longhorn.io default-data-path \
  --type=merge -p '{"value":"/var/mnt/longhorn/"}'
```

If Longhorn created `/var/lib/longhorn` and the root disk should not hold replicas, leave the disk object if needed but set `allowScheduling=false`.

## SNO StorageClass

For SNO, keep one replica and one default class:

```yaml
metadata:
  name: longhorn
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: driver.longhorn.io
allowVolumeExpansion: true
reclaimPolicy: Delete
volumeBindingMode: Immediate
parameters:
  numberOfReplicas: "1"
  staleReplicaTimeout: "30"
  fromBackup: ""
  fsType: ext4
  dataLocality: disabled
  unmapMarkSnapChainRemoved: ignored
  disableRevisionCounter: "true"
  dataEngine: v1
  backupTargetName: default
```

Keep the `longhorn-storageclass` ConfigMap aligned with the live class when Longhorn reconciles default StorageClass state.

When Longhorn must not become the cluster default, use the same parameters but
set `storageclass.kubernetes.io/is-default-class: "false"` and verify another
class, such as `lvms-vg1`, is the only default.

## Validation

Create a test PVC and pod. Confirm:

- PVC is `Bound`.
- Pod can write and read data.
- Longhorn volume is attached and healthy.
- SNO volume has exactly one replica.
- Replica is on `/var/mnt/longhorn`, not `/var/lib/longhorn`.
- `oc get sc` shows exactly one default StorageClass.

For a root-backed smoke test, replace the disk-path assertion with:

- the replica is on `/var/lib/longhorn`;
- the result is reported as a smoke-only validation, not a dedicated-disk V1
  production layout.
