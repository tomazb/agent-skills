# VM Storage Defaults And CDI StorageProfiles

Use this runbook when configuring which StorageClass OpenShift Virtualization (CDI/KubeVirt) uses for VirtualMachine disks, when resolving the `CDIStorageProfilesIncomplete` alert, or when moving a default StorageClass between Rook and another storage operator.

## Two Default StorageClasses

Kubernetes and CDI use two independent default mechanisms:

- General-purpose default: `storageclass.kubernetes.io/is-default-class: "true"` on the StorageClass. Applied when any PVC (including non-VM workloads) omits `spec.storageClassName`. Keep exactly one when defaulting is expected. Zero general defaults is a valid policy: a PVC that omits `storageClassName` then stays Pending.
- VM/virtualization default: `storageclass.kubevirt.io/is-default-virt-class: "true"` on the StorageClass. When a DataVolume omits `spec.storage.storageClassName`, CDI prioritizes this over the general-purpose default. At most one class should carry it.

The two can coexist on different classes without conflict. A common layout is a general-purpose default on `rook-nfs` or `rook-cephfs` and a VM default on `rook-ceph-block`.

Set the VM default on an RBD class. First remove the annotation from any class that already holds it to prevent `CDIMultipleDefaultVirtStorageClasses`:

```bash
set -euo pipefail
oc get sc -o json \
  | python3 -c "import json,sys; [print(i['metadata']['name']) for i in json.load(sys.stdin)['items'] if i.get('metadata',{}).get('annotations',{}).get('storageclass.kubevirt.io/is-default-virt-class') == 'true']" \
  | xargs -r -I{} oc annotate storageclass {} storageclass.kubevirt.io/is-default-virt-class-
oc annotate storageclass rook-ceph-block storageclass.kubevirt.io/is-default-virt-class=true --overwrite
```

Verify exactly one class carries the annotation:

```bash
oc get sc -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.annotations.storageclass\.kubevirt\.io/is-default-virt-class}{"\n"}{end}'
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

Prefer raw block RBD for VirtualMachine disks (fewer layers, better performance). Ceph RBD block mode supports multi-attach (RWX) via the CSI driver, which is required for live migration. Put `ReadWriteMany` first so CDI infers RWX as the default when a DataVolume omits `accessModes`; keep `ReadWriteOnce` as the fallback. If live migration is not needed or multi-attach is not confirmed, reverse the order:

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

Some storage operators reconcile the `is-default-class` annotation from their own CRs and will re-add it within seconds if you only delete the annotation. The LVMS operator is one example: it pins the default from `LVMCluster.spec.storage.deviceClasses[].default` and `LVMVolumeGroup.spec.default`. To stop it pinning a class as default, set `default: false` on the owning CR, not just the StorageClass annotation.

First, find the index of the deviceClass that is currently pinned as default:

```bash
oc get lvmcluster <name> -n openshift-storage -o jsonpath='{range .spec.storage.deviceClasses[*]}{.name}: default={.default}{"\n"}{end}'
```

Then patch using the correct index (0, 1, …):

```bash
oc patch lvmcluster <name> -n openshift-storage --type=json -p '[{"op":"replace","path":"/spec/storage/deviceClasses/<index>/default","value":false}]'
oc patch lvmvolumegroup <name> -n openshift-storage --type=merge -p '{"spec":{"default":false}}'
oc annotate storageclass <lvms-class> storageclass.kubernetes.io/is-default-class-
```

Generalize: before fighting a re-pinning controller, check the StorageClass `metadata.managedFields` and the owning operator's CRs; change the declarative source, then clear the leftover annotation.

## Verification

Create a throwaway namespace:

```bash
oc create ns rook-vm-smoke
```

Default-class selection and provisioning are separate checks. Selection is complete when `spec.storageClassName` is set. Binding is optional, and only when that binding is the intended policy.

A plain PVC omits `storageClassName`. It records which general default the cluster selected:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: default-sc-test-pvc
  namespace: rook-vm-smoke
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 1Gi
```

A VM with a blank DataVolume omits `storageClassName`, `volumeMode`, and `accessModes`. It records which virt default CDI selected, and the StorageProfile's first claim property set:

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: default-sc-test-vm
  namespace: rook-vm-smoke
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

Apply both manifests, then read the selected class. `spec.storageClassName` is set on create, before the PVC binds:

```bash
oc apply -n rook-vm-smoke -f <pvc-manifest.yaml>
oc apply -n rook-vm-smoke -f <vm-manifest.yaml>
oc -n rook-vm-smoke get pvc default-sc-test-pvc -o jsonpath='sc={.spec.storageClassName}{"\n"}'
oc -n rook-vm-smoke get pvc default-sc-test-dv -o jsonpath='sc={.spec.storageClassName} mode={.spec.volumeMode} ams={.spec.accessModes}{"\n"}'
```

When a general default exists, the plain PVC's `storageClassName` is that class. Skip the plain PVC bind wait when no general default is expected: `storageClassName` stays empty and the phase stays `Pending`, which is that policy. Expect the DataVolume PVC on the virt default with the StorageProfile's first set (for example `rook-ceph-block`, `Block`, `ReadWriteMany`).

Prove provisioning only when a default is expected and a bound volume is required. `volumeBindingMode: Immediate` is the Rook Ceph default. `WaitForFirstConsumer` (the LVMS default) leaves a PVC Pending until a pod is scheduled. The test VM uses its DataVolume, not `default-sc-test-pvc`, so starting the VM or setting `cdi.kubevirt.io/storage.bind.immediate.requested` on the DataVolume does not consume the plain PVC. For the plain PVC, add a pod that mounts `default-sc-test-pvc` before waiting.

For the DataVolume, inspect its own selected class and start the test VM only for `WaitForFirstConsumer`, before waiting for CDI readiness. The block below patches the existing `kubevirt.io/v1` VM's `spec.running` field; do not add the mutually exclusive `runStrategy` field. KubeVirt creates a temporary first-consumer pod with the VM's placement constraints before launching the guest, as implemented in [KubeVirt 1.6](https://github.com/kubevirt/kubevirt/blob/v1.6.0/pkg/virt-controller/watch/vmi/lifecycle.go). `Immediate` leaves the VM stopped. The blank disk need not boot an OS for this storage check. See [KubeVirt running semantics](https://kubevirt.io/user-guide/compute/run_strategies/) and [CDI first-consumer handling](https://github.com/kubevirt/containerized-data-importer/blob/main/doc/waitforfirstconsumer-storage-handling.md).

If `oc wait --for=jsonpath=...` fails with `unrecognized condition`, the client is older than that condition. Poll `.status.phase` until it is `Bound`.

The DataVolume wait runs after its binding trigger when needed. The plain-PVC wait runs only when a general default was selected. Its `WaitForFirstConsumer` pod mounts only `default-sc-test-pvc`; the VM consumes only the DataVolume. Run this block in Bash with an [OpenShift 4.20 CLI](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html-single/cli_tools/index) or another client supporting `oc wait --for=create`. CDI creates the DataVolume PVC asynchronously, so wait for it to exist before reading its class. A failed query, consumer creation, VM patch, or wait stops verification.

```bash
set -euo pipefail
sc=$(oc -n rook-vm-smoke get pvc default-sc-test-pvc -o jsonpath='{.spec.storageClassName}')
phase=$(oc -n rook-vm-smoke get pvc default-sc-test-pvc -o jsonpath='{.status.phase}')
if [ -z "$sc" ]; then
  printf 'plain PVC has no storageClassName and is %s; Pending is expected when no general default exists\n' "$phase"
else
  mode=$(oc -n rook-vm-smoke get sc "$sc" -o jsonpath='{.volumeBindingMode}')
  if [ "$mode" = "WaitForFirstConsumer" ]; then
    oc apply -n rook-vm-smoke -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: default-sc-test-consumer
  namespace: rook-vm-smoke
spec:
  restartPolicy: Never
  containers:
  - name: consumer
    image: registry.access.redhat.com/ubi9/ubi
    command: ["sleep", "3600"]
    volumeMounts:
    - name: data
      mountPath: /data
    securityContext:
      allowPrivilegeEscalation: false
      runAsNonRoot: true
      capabilities:
        drop: ["ALL"]
      seccompProfile:
        type: RuntimeDefault
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: default-sc-test-pvc
EOF
  fi
  oc wait -n rook-vm-smoke pvc/default-sc-test-pvc \
    --for=jsonpath='{.status.phase}'=Bound --timeout=120s
fi
oc wait -n rook-vm-smoke pvc/default-sc-test-dv --for=create --timeout=120s
dv_sc=$(oc -n rook-vm-smoke get pvc default-sc-test-dv -o jsonpath='{.spec.storageClassName}')
dv_mode=$(oc -n rook-vm-smoke get sc "$dv_sc" -o jsonpath='{.volumeBindingMode}')
if [ "$dv_mode" = "WaitForFirstConsumer" ]; then
  oc patch -n rook-vm-smoke vm default-sc-test-vm --type=merge -p '{"spec":{"running":true}}'
fi
oc wait -n rook-vm-smoke datavolume/default-sc-test-dv \
  --for=condition=Ready --timeout=300s
```

Clean up:

```bash
bash scripts/cleanup_smoke_namespace.sh --namespace rook-vm-smoke
```
