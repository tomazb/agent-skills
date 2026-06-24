# Filesystem Volumes

Use this runbook for provisioning filesystem PVCs (ext4 or xfs) via TopoLVM CSI on OpenShift/OKD.

## StorageClass for Filesystem Volumes

TopoLVM creates a StorageClass automatically when the `LVMCluster` has `default: true` in a `DeviceClass`. You can also create custom StorageClasses for different filesystem types or policies.

### Default TopoLVM Filesystem StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: lvms-vg1
provisioner: topolvm.io
parameters:
  csi.storage.k8s.io/fstype: ext4
  topolvm.io/device-class: vg1
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

### Custom XFS StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: lvms-vg1-xfs
provisioner: topolvm.io
parameters:
  csi.storage.k8s.io/fstype: xfs
  topolvm.io/device-class: vg1
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

**Critical**: `volumeBindingMode: WaitForFirstConsumer` is required for TopoLVM. It enables capacity-aware scheduling so the pod is scheduled to a node with sufficient VG capacity before the volume is provisioned. Do not change this to `Immediate`.

## PVC for Filesystem

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
  namespace: my-app
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: lvms-vg1
  resources:
    requests:
      storage: 10Gi
```

## Pod Using Filesystem PVC

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
  namespace: my-app
spec:
  containers:
    - name: app
      image: registry.access.redhat.com/ubi9/ubi-minimal:latest
      command: ["sh", "-c", "sleep 3600"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: my-pvc
```

## Capacity-Aware Scheduling

TopoLVM uses the `topolvm.io/capacity` extended resource on each node to expose available VG capacity. The scheduler considers this when placing pods with TopoLVM PVCs. Verify the extended resource is present:

```bash
oc describe node <node> | grep -i topolvm
oc get node <node> -o json | jq '.status.capacity | with_entries(select(.key | contains("topolvm")))'
```

If capacity is not reported, check:
- The `LVMCluster` is `Ready`.
- The TopoLVM CSI node pod is running on the node.
- The VG has free space (`vgs` on the node).

## Volume Expansion

TopoLVM supports online expansion for filesystem volumes if `allowVolumeExpansion: true` is set in the StorageClass. Patch the PVC:

```bash
oc patch pvc my-pvc -n my-app --type=merge -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
```

Verify expansion:

```bash
oc -n my-app get pvc my-pvc
oc -n my-app exec my-app -- df -h /data
```

## Safety Rules

- Keep exactly one default StorageClass unless the user explicitly requests another policy.
- On SNO, the volume is bound to the single node. Document this as a topology constraint, not high availability.
- `volumeBindingMode: WaitForFirstConsumer` is required. Changing it to `Immediate` breaks capacity-aware scheduling.
- Filesystem volumes use `ext4` by default. XFS is supported via `csi.storage.k8s.io/fstype: xfs`.
