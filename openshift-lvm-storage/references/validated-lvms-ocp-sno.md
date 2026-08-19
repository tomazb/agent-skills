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

`default: true` below is what *this* cluster used, where no other default StorageClass existed. It is an observed value, not a recommendation: if the target cluster already has a default (ODF, or a prior LVMS install), copying it verbatim creates a second one, and the most recently created default silently wins for PVCs that omit `storageClassName`. Check first — see the decide-`default:`-first section in `install-and-preflight.md`.

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

---

# Scenario: LVMS 4.20.1 Alongside ODF on SNO, virtio Disk Without a by-id Entry

Observed on a live install. Two things distinguish it from the template above:
the target disk had no `/dev/disk/by-id/` entry, and `openshift-storage` was
already occupied by ODF.

## Environment

- OpenShift: 4.20.32, `controlPlaneTopology: SingleReplica`, one node
- LVMS: `lvms-operator.v4.20.1`, channel `stable-4.20`
- Coexisting: ODF 4.20.16-rhodf in the same `openshift-storage` namespace

The catalog served only `stable-4.19` and `stable-4.20`, with `stable-4.20` as
`defaultChannel`. Reading it from the PackageManifest matters here: a guessed
bare `stable` is not served and the Subscription would sit with no CSV.

`openshift-storage` and its `OperatorGroup` already existed from the ODF
install, so both creation steps were skipped — a second OperatorGroup in one
namespace breaks OLM resolution for every operator in it.

## Disk Selection

The 300 GiB virtio disk had **no `/dev/disk/by-id/` entry at all** — virtio
without a serial — so `by-path` was the only stable identity available:

```text
/dev/disk/by-path/pci-0000:00:0b.0 -> ../../vdc
```

Evidence captured before claiming it (all four agreed the disk was raw):

| Check | Output |
|---|---|
| `lsblk -f` | no FSTYPE, no UUID, no mountpoint |
| `wipefs -n` | empty (no signatures) |
| `pvs --devices` | `Failed to find physical volume "/dev/vdc"` |
| `vgs` / `lvs` | no VGs or LVs on the node |

The node's other disks were left alone: `vda` (OS) and `vdb` (500 GiB,
`ceph_bluestore`, ODF's OSD).

## LVMCluster

`deviceClass` `vg1`, `thinPoolConfig` `thin-pool-1` with
`overprovisionRatio: 10` and `sizePercent: 90`, `deviceSelector.paths` set to
the by-path entry above, node-pinned by `kubernetes.io/hostname`.

`default: false` — the cluster had no default StorageClass and the intent was
to keep it that way. The operator warns at apply time that PVCs must then name
the StorageClass explicitly, and on a cluster with no default at all a PVC that
omits `storageClassName` stays `Pending` with nothing in the LVMS logs to
explain it.

## Observed Result

- `LVMCluster` reached `Ready`; VG `vg1` = 1 PV (`/dev/vdc`), `<300.00g`, 30.00g free
- `thin-pool-1` = 269.73g, `Data% 0.00`, `Meta% 10.42`
- StorageClass `lvms-vg1`, provisioner `topolvm.io`, `WaitForFirstConsumer`, not default
- Filesystem PVC bound; pod wrote and read back a probe file; xfs on a `vg1` LV
- Raw block PVC bound; `brw-rw-rw-` device node appeared at the container's `devicePath`
- ODF unaffected throughout: `StorageCluster` Ready, `HEALTH_OK`, `vdb` still `ceph_bluestore`

**Workload names on 4.20.1:** only `lvms-operator` and `vg-manager` run in the
namespace. There are no `topolvm-controller` or `topolvm-node` pods to look for,
and provisioning works without them — list workloads and read the names rather
than waiting on a pod that this version does not create.

Not exercised in this scenario: reboot persistence, thin-pool growth under
load, and expansion by adding a second disk.
