# Block Volumes

Use this runbook for provisioning raw block PVCs via TopoLVM CSI on OpenShift/OKD.

## StorageClass for Block Volumes

Block volumes do not have a filesystem. They are used directly by the application as a raw device (e.g., databases, VMs, or custom filesystems).

### TopoLVM Block StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: lvms-vg1-block
provisioner: topolvm.io
parameters:
  topolvm.io/device-class: vg1
  # No csi.storage.k8s.io/fstype parameter for raw block
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

**Critical**: `volumeBindingMode: WaitForFirstConsumer` is required for TopoLVM. Do not change this to `Immediate`.

**Note**: Do not set `csi.storage.k8s.io/fstype` for block volumes. The absence of this parameter signals to TopoLVM that the volume should be provisioned as a raw block device.

## PVC for Raw Block

Set `volumeMode: Block`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-block-pvc
  namespace: my-app
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: lvms-vg1-block
  volumeMode: Block
  resources:
    requests:
      storage: 10Gi
```

## Pod Using Raw Block Volume

Use `volumeDevices` instead of `volumeMounts`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-block-app
  namespace: my-app
spec:
  containers:
    - name: app
      image: registry.access.redhat.com/ubi9/ubi-minimal:9.5
      command: ["sh", "-c", "sleep 3600"]
      volumeDevices:
        - name: block-data
          devicePath: /dev/block-device
  volumes:
    - name: block-data
      persistentVolumeClaim:
        claimName: my-block-pvc
```

## Block Volume Expansion

TopoLVM supports online expansion for block volumes if `allowVolumeExpansion: true` is set in the StorageClass. Patch the PVC:

```bash
oc patch pvc my-block-pvc -n my-app --type=merge -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
```

Verify expansion:

```bash
oc -n my-app get pvc my-block-pvc
# `lsblk` is not present in ubi-minimal; `test -b` works in any shell.
oc -n my-app exec my-block-app -- sh -c 'test -b /dev/block-device && echo "block device present"'
```

## Block Volume Snapshots

TopoLVM supports snapshots for thin pool-backed volumes. Create a `VolumeSnapshotClass`:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: lvms-snapshot-class
driver: topolvm.io
deletionPolicy: Delete
```

`deletionPolicy` is a required field. Use `Delete` so the underlying thin-pool snapshot is removed when its `VolumeSnapshotContent` is deleted, or `Retain` to keep it.

Then create a snapshot:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-block-snapshot
  namespace: my-app
spec:
  volumeSnapshotClassName: lvms-snapshot-class
  source:
    persistentVolumeClaimName: my-block-pvc
```

## Safety Rules

- Block volumes do not have a filesystem. The consuming application must handle the raw device directly.
- `volumeMode: Block` is required in the PVC. `volumeDevices` (not `volumeMounts`) is required in the pod spec.
- On SNO, the block volume is bound to the single node. Document this as a topology constraint.
- `volumeBindingMode: WaitForFirstConsumer` is required for capacity-aware scheduling.
- Snapshots are thin pool snapshots. They share the same physical VG and thin pool. Monitor thin pool capacity when using snapshots extensively.
