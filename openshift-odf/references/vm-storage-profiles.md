# VM Storage Defaults And CDI StorageProfiles

Use this runbook when configuring which StorageClass OpenShift Virtualization (CDI/KubeVirt) uses for VirtualMachine disks on ODF, when resolving the `CDIStorageProfilesIncomplete` alert, or when another storage operator keeps re-pinning the general default.

ODF owns its StorageClasses through `ocs-operator`. This runbook only changes StorageClass annotations and CDI `StorageProfile` objects; it never edits the ODF-owned Rook CRs.

## Two Defaults

Kubernetes and CDI use two independent default mechanisms:

- General-purpose default: `storageclass.kubernetes.io/is-default-class: "true"`. Applied when any PVC, including a non-VM workload, omits `spec.storageClassName`.
- VM default: `storageclass.kubevirt.io/is-default-virt-class: "true"`. When a DataVolume omits `spec.storage.storageClassName`, CDI prefers this over the general default.

Keep exactly one class of each kind when that default is expected. The ODF install does not have to own the general default. Zero general defaults is a valid policy: a PVC that omits `storageClassName` then stays Pending. The two annotations can sit on different classes. A common layout keeps the general default on LVMS (`lvms-vg1`) and puts the VM default on `ocs-storagecluster-ceph-rbd`.

## Choose The VM Class

| Role | ODF name |
| --- | --- |
| VM block default | `ocs-storagecluster-ceph-rbd` |
| Filesystem default, when CephFS is the VM default | `ocs-storagecluster-cephfs` |
| RBD provisioner | `openshift-storage.rbd.csi.ceph.com` |
| CephFS provisioner | `openshift-storage.cephfs.csi.ceph.com` |

For VM disks prefer `ocs-storagecluster-ceph-rbd` (raw block). Use `ocs-storagecluster-cephfs` when the guest needs a `ReadWriteMany` filesystem.

Remove the virt annotation from the previous class before annotating the new one, so CDI does not raise `CDIMultipleDefaultVirtStorageClasses`:

```bash
set -euo pipefail
oc get sc -o json \
  | python3 -c "import json,sys; [print(i['metadata']['name']) for i in json.load(sys.stdin)['items'] if i.get('metadata',{}).get('annotations',{}).get('storageclass.kubevirt.io/is-default-virt-class') == 'true']" \
  | xargs -r -I{} oc annotate storageclass {} storageclass.kubevirt.io/is-default-virt-class-
oc annotate storageclass ocs-storagecluster-ceph-rbd storageclass.kubevirt.io/is-default-virt-class=true --overwrite
```

Verify exactly one class carries it. Escape `/` in jsonpath annotation keys; `custom-columns` cannot resolve them and prints `<none>`:

```bash
oc get sc -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.annotations.storageclass\.kubevirt\.io/is-default-virt-class}{"\n"}{end}'
```

Remove it:

```bash
oc annotate storageclass ocs-storagecluster-ceph-rbd storageclass.kubevirt.io/is-default-virt-class-
```

## claimPropertySets

CDI creates one `StorageProfile` per StorageClass and recognizes both ODF provisioners, so `status.claimPropertySets` is already filled. Priority, highest first:

1. DataVolume `spec.storage` fields (`storageClassName`, `volumeMode`, `accessModes`).
2. User-defined `spec.claimPropertySets` on the StorageProfile.
3. CDI-provided `status.claimPropertySets`.
4. Kubernetes defaults.

Order the sets to make the first one the default CDI infers. For `ocs-storagecluster-ceph-rbd` the first set is `volumeMode: Block` with `accessModes: [ReadWriteMany]`, which live migration needs. Keep `ReadWriteOnce` as the fallback, and reverse the order when multi-attach is not confirmed. The CSI provisioner is `openshift-storage.rbd.csi.ceph.com`:

```bash
oc patch storageprofile ocs-storagecluster-ceph-rbd --type=merge -p '{"spec":{"claimPropertySets":[{"accessModes":["ReadWriteMany"],"volumeMode":"Block"},{"accessModes":["ReadWriteOnce"],"volumeMode":"Block"}]}}'
```

For `ocs-storagecluster-cephfs` (provisioner `openshift-storage.cephfs.csi.ceph.com`) the first set is `volumeMode: Filesystem` with `accessModes: [ReadWriteMany]`:

```bash
oc patch storageprofile ocs-storagecluster-cephfs --type=merge -p '{"spec":{"claimPropertySets":[{"accessModes":["ReadWriteMany"],"volumeMode":"Filesystem"},{"accessModes":["ReadWriteOnce"],"volumeMode":"Filesystem"}]}}'
```

The StorageClass `fstype` is ignored for `volumeMode: Block` PVCs. An explicit `volumeMode: Filesystem` on a DataVolume still wins.

If `CDIStorageProfilesIncomplete` fires for another class, run `oc get storageprofile <class> -o yaml`. Empty `status.claimPropertySets` means CDI does not recognize that provisioner; set `spec.claimPropertySets` as above.

## LVMS Re-Pin

Some operators reconcile `is-default-class` from their own CRs and re-add it within seconds if you only delete the annotation. LVMS does this for `lvms-vg1` (or another LVMS class). Change the declarative source, `LVMCluster.spec.storage.deviceClasses[].default`, in the namespace that owns the LVMCluster. Do not only edit the StorageClass annotation; it gets reconciled away.

Find the index of the pinned device class:

```bash
oc get lvmcluster <name> -n <lvms-namespace> -o jsonpath='{range .spec.storage.deviceClasses[*]}{.name}: default={.default}{"\n"}{end}'
```

Set `default: false` to release the general default, or `true` on the class that should hold it:

```bash
oc patch lvmcluster <name> -n <lvms-namespace> --type=json -p '[{"op":"replace","path":"/spec/storage/deviceClasses/<index>/default","value":false}]'
```

Then clear any leftover annotation on a class that should no longer be the general default:

```bash
oc annotate storageclass <lvms-class> storageclass.kubernetes.io/is-default-class-
```

## Verification

Use the throwaway namespace `odf-vm-smoke`:

```bash
oc create ns odf-vm-smoke
```

Default-class selection and provisioning are separate checks. Selection is complete when `spec.storageClassName` is set. Binding is optional, and only when that binding is the intended policy.

A plain PVC omits `storageClassName`. It records which general default the cluster selected:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: default-sc-test-pvc
  namespace: odf-vm-smoke
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 1Gi
```

A VM with a blank DataVolume (omits `storageClassName`, `volumeMode`, `accessModes`) should bind on the VM default, with `volumeMode` and `accessModes` inferred from the StorageProfile:

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: default-sc-test-vm
  namespace: odf-vm-smoke
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

Apply both, then read the selected class. `spec.storageClassName` is set on create, before the PVC binds:

```bash
oc apply -n odf-vm-smoke -f <pvc-manifest.yaml>
oc apply -n odf-vm-smoke -f <vm-manifest.yaml>
oc -n odf-vm-smoke get pvc default-sc-test-pvc -o jsonpath='sc={.spec.storageClassName}{"\n"}'
oc -n odf-vm-smoke get pvc default-sc-test-dv -o jsonpath='sc={.spec.storageClassName} mode={.spec.volumeMode} ams={.spec.accessModes}{"\n"}'
```

When a general default exists, the plain PVC's `storageClassName` is that class. Skip the plain PVC bind wait when no general default is expected: `storageClassName` stays empty and the phase stays `Pending`, which is that policy. Expect the DataVolume PVC on the virt default with the StorageProfile's first set: `ocs-storagecluster-ceph-rbd`, `Block`, `ReadWriteMany` when RBD is the VM default.

Prove provisioning only when a default is expected and a bound volume is required. `volumeBindingMode: WaitForFirstConsumer` leaves a PVC Pending until a pod is scheduled. The test VM uses its DataVolume, not `default-sc-test-pvc`, so starting the VM or setting `cdi.kubevirt.io/storage.bind.immediate.requested` on the DataVolume does not consume the plain PVC. For the plain PVC, add a pod that mounts `default-sc-test-pvc` before waiting. For the DataVolume, either set `running: true` on the test VM or set that annotation, then wait.

If `oc wait --for=jsonpath=...` fails with `unrecognized condition`, poll `.status.phase` until it is `Bound`:

```bash
oc wait -n odf-vm-smoke pvc/default-sc-test-pvc \
  --for=jsonpath='{.status.phase}'=Bound --timeout=120s
oc wait -n odf-vm-smoke datavolume/default-sc-test-dv \
  --for=condition=Ready --timeout=300s
```

Clean up once the result is recorded:

```bash
bash scripts/cleanup_smoke_namespace.sh --namespace odf-vm-smoke
```
