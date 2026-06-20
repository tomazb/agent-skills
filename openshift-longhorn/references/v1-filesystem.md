# V1 Filesystem Data Engine

Use this runbook for Longhorn V1 Data Engine deployments that store replica data on filesystem-mounted disks.

## Target Shape

- `iscsid.service` enabled and active on every Longhorn node.
- Dedicated storage uses ext4 or XFS on a filesystem path such as `/var/mnt/longhorn`.
- The host mount is persisted through MachineConfig on OpenShift/RHCOS.
- SNO uses `numberOfReplicas: "1"` and `default-replica-count` set to one replica. Multi-node production normally uses two or three replicas.
- Exactly one default StorageClass exists when defaulting is requested.

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

## Validation

Create a test PVC and pod. Confirm:

- PVC is `Bound`.
- Pod can write and read data.
- Longhorn volume is attached and healthy.
- SNO volume has exactly one replica.
- Replica is on `/var/mnt/longhorn`, not `/var/lib/longhorn`.
- `oc get sc` shows exactly one default StorageClass.
