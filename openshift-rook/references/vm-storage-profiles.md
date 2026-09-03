# VM Storage Defaults And CDI StorageProfiles

Use this runbook when configuring which StorageClass OpenShift Virtualization (CDI/KubeVirt) uses for VirtualMachine disks, when resolving the `CDIStorageProfilesIncomplete` alert, or when moving a default StorageClass between Rook and another storage operator.

## Two Default StorageClasses

Kubernetes and CDI use two independent default mechanisms:

- General-purpose default: `storageclass.kubernetes.io/is-default-class: "true"` on the StorageClass. Applied when any PVC (including non-VM workloads) omits `spec.storageClassName`. Keep exactly one of these cluster-wide.
- VM/virtualization default: `storageclass.kubevirt.io/is-default-virt-class: "true"` on the StorageClass. When a DataVolume omits `spec.storage.storageClassName`, CDI prioritizes this over the general-purpose default. At most one class should carry it.

The two can coexist on different classes without conflict. A common layout is a general-purpose default on `rook-nfs` or `rook-cephfs` and a VM default on `rook-ceph-block`.

Set the VM default on an RBD class:

```bash
oc annotate storageclass rook-ceph-block storageclass.kubevirt.io/is-default-virt-class=true --overwrite
```

Remove it:

```bash
oc annotate storageclass rook-ceph-block storageclass.kubevirt.io/is-default-virt-class-
```

Read annotations containing `/` with jsonpath (kubectl `custom-columns` cannot resolve keys containing `/` and prints `<none>`):

```bash
oc get sc rook-ceph-block -o jsonpath='{.metadata.annotations.storageclass\.kubevirt\.io/is-default-virt-class}{"\n"}'
```

## StorageProfile claimPropertySets

CDI auto-creates one `StorageProfile` per StorageClass. For recognized provisioners (for example `rook-ceph.rbd.csi.ceph.com`) it fills `status.claimPropertySets`; for unrecognized ones (for example `rook-ceph.nfs.csi.ceph.com`) it leaves them empty and sets `status.conditions[Recognized].reason: UnrecognizedProvisioner`.

Priority, highest first:

1. DataVolume `spec.storage` fields (`storageClassName`, `volumeMode`, `accessModes`).
2. User-defined `spec.claimPropertySets` on the StorageProfile.
3. CDI-provided defaults in `status.claimPropertySets`.
4. Kubernetes defaults.

Set user-defined `claimPropertySets` to override CDI auto-detection.

### RBD block mode for VM disks (recommended)

Prefer raw block RBD for VirtualMachine disks (fewer layers, better performance). Put `ReadWriteMany` first so live migration works when the pool supports multi-attach:

```bash
oc patch storageprofile rook-ceph-block --type=merge -p '{"spec":{"claimPropertySets":[{"accessModes":["ReadWriteMany"],"volumeMode":"Block"},{"accessModes":["ReadWriteOnce"],"volumeMode":"Block"}]}}'
```

CDI reconciles `status.claimPropertySets` to match. The StorageClass `fstype` parameter is ignored for `volumeMode: Block` PVCs (no filesystem on a raw block device). Explicit `volumeMode: Filesystem` on a DataVolume still wins.

### CephFS and NFS (filesystem mode)

File-based provisioners use `Filesystem` only. For `rook-cephfs` (recognized) the auto-profile already provides sets; override only to force RWX-first ordering. For `rook-nfs` (unrecognized) populate the profile yourself:

```bash
oc patch storageprofile rook-nfs --type=merge -p '{"spec":{"claimPropertySets":[{"accessModes":["ReadWriteMany"],"volumeMode":"Filesystem"},{"accessModes":["ReadWriteOnce"],"volumeMode":"Filesystem"}]}}'
```

## CDIStorageProfilesIncomplete Alert

Fires when a StorageProfile has no `claimPropertySets`, so CDI cannot infer `volumeMode`/`accessModes` for a DataVolume that omits them. Reference: openshift/runbooks `alerts/openshift-virtualization-operator/CDIStorageProfilesIncomplete.md`.

Diagnose:

```bash
oc get storageprofile <class> -o yaml
```

An empty `spec` and empty `status.claimPropertySets` with `reason: UnrecognizedProvisioner` confirms it. Fix by setting `spec.claimPropertySets` as shown above. The `Recognized` condition stays `False` after the fix; that is harmless because user-defined sets (priority 2) override the missing auto-detection (priority 3).

## Moving A Default Between Operators

Some storage operators reconcile the `is-default-class` annotation from their own CRs and will re-add it within seconds if you only delete the annotation. The LVMS operator is one example: it pins the default from `LVMCluster.spec.storage.deviceClasses[].default` and `LVMVolumeGroup.spec.default`. To stop it pinning a class as default, set `default: false` on the owning CR, not just the StorageClass annotation:

```bash
oc patch lvmcluster <name> -n openshift-storage --type=json -p '[{"op":"replace","path":"/spec/storage/deviceClasses/0/default","value":false}]'
oc patch lvmvolumegroup <name> -n openshift-storage --type=merge -p '{"spec":{"default":false}}'
oc annotate storageclass <lvms-class> storageclass.kubernetes.io/is-default-class-
```

Generalize: before fighting a re-pinning controller, check the StorageClass `metadata.managedFields` and the owning operator's CRs; change the declarative source, then clear the leftover annotation.

## Verification

Create a throwaway namespace and two resources, then delete it.

Plain PVC (omits `storageClassName`) should bind on the general-purpose default:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: default-sc-test-pvc
  namespace: storage-default-test
spec:
  accessModes: ["ReadWriteMany"]
  resources:
    requests:
      storage: 1Gi
```

VM with a blank DataVolume (omits `storageClassName`, `volumeMode`, `accessModes`) should bind on the VM default with `volumeMode`/`accessModes` inferred from the StorageProfile:

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: default-sc-test-vm
  namespace: storage-default-test
spec:
  running: false
  template:
    spec:
      domain:
        devices:
          disks:
            - name: rootdisk
              disk:
                bus: virtio
        resources:
          requests:
            memory: 128Mi
      volumes:
        - name: rootdisk
          dataVolume:
            name: default-sc-test-dv
  dataVolumeTemplates:
    - metadata:
        name: default-sc-test-dv
      spec:
        storage:
          resources:
            requests:
              storage: 1Gi
        source:
          blank: {}
```

Confirm:

```bash
oc -n storage-default-test get pvc default-sc-test-pvc -o jsonpath='sc={.spec.storageClassName} mode={.spec.volumeMode} phase={.status.phase}{"\n"}'
oc -n storage-default-test get pvc default-sc-test-dv -o jsonpath='sc={.spec.storageClassName} mode={.spec.volumeMode} ams={.spec.accessModes} phase={.status.phase}{"\n"}'
oc -n storage-default-test get dv default-sc-test-dv -o jsonpath='phase={.status.phase} progress={.status.progress}{"\n"}'
```

Expect the plain PVC on the general default (`Filesystem`), and the DataVolume PVC on the VM default with the StorageProfile's first set (for example `rook-ceph-block`, `Block`, `ReadWriteMany`) with DV `Succeeded`. Clean up:

```bash
oc delete ns storage-default-test --wait
```
