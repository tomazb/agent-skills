# Validated LVMS OCP SNO

Use this document as observed evidence from a validated OpenShift SNO + LVMS deployment. Do not turn these host-specific values into defaults without confirming the target cluster.

## Environment

- OpenShift version: <version>
- LVMS operator version: <version>
- Topology: Single Node OpenShift (SNO)
- Node name: <node-name>

## Disk Configuration

### Disk Inventory

```bash
oc debug node/<node> -- chroot /host bash -c "lsblk -f; pvs; vgs; lvs"
```

Observed values (example, not default):

- Disk: `/dev/disk/by-id/wwn-0x<wwn>`
- VG name: `vg1`
- Thin pool name: `thin-pool-1`
- Thin pool size: 90% of VG
- Over-provisioning ratio: 10

### LVMCluster CR

```yaml
apiVersion: lvm.topolvm.io/v1alpha1
kind: LVMCluster
metadata:
  name: lvmcluster
  namespace: openshift-storage
spec:
  storage:
    deviceClasses:
      - name: vg1
        thinPoolConfig:
          name: thin-pool-1
          overprovisionRatio: 10
          sizePercent: 90
        deviceSelector:
          paths:
            - /dev/disk/by-id/wwn-0x<wwn>
        default: true
        nodeSelector:
          nodeSelectorTerms:
            - matchExpressions:
                - key: kubernetes.io/hostname
                  operator: In
                  values:
                    - <node-name>
```

## StorageClass

The operator created `lvms-vg1` as the default StorageClass:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: lvms-vg1
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: topolvm.io
parameters:
  csi.storage.k8s.io/fstype: ext4
  topolvm.io/device-class: vg1
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

## Validation Results

- `LVMCluster` reached `Ready` in <time>.
- TopoLVM CSI node and controller pods running.
- PVC `Bound` successfully.
- Pod scheduled and volume mounted.
- Write/read test passed.
- `lvs` shows thin pool `data_percent` within expected bounds.
- Post-reboot: VGs and thin pools persisted, `LVMCluster` reconciled to `Ready`.

## Notes

- These are observed values from one specific deployment. They are not universal defaults.
- Disk paths (WWN, by-id, by-path) are host-specific. Always discover them on the target cluster.
- Thin pool settings (`sizePercent`, `overprovisionRatio`) were chosen for this workload. Adjust based on target capacity and usage patterns.
- On SNO, all storage is local and non-redundant. Plan accordingly for backup and DR.
