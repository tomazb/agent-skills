# Validated ODF SNO Scenario

This is observed evidence for one OpenShift SNO / ODF scenario. Do not turn these host-specific values into defaults without confirming the target cluster.

## Cluster Details

- OpenShift version: 4.16
- ODF version: 4.16
- Topology: Single Node OpenShift (SNO)
- Deployment mode: internal-attached (Local Storage Operator)
- Storage services: ceph-rbd, cephfs, MCG/RGW object

## Disk Layout

- One dedicated NVMe disk for OSD data (SNO has one node, one disk).
- The disk was selected through a `LocalVolumeSet` (`localblock`) filtering by device attributes, not by naming a raw `/dev/sdX` path.

## StorageCluster Configuration (SNO)

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  manageNodes: false
  monDataDirHostPath: /var/lib/rook
  storageDeviceSets:
  - name: ocs-deviceset
    count: 1
    replica: 1
    portable: false
    dataPVCTemplate:
      spec:
        accessModes:
        - ReadWriteOnce
        volumeMode: Block
        storageClassName: localblock
        resources:
          requests:
            storage: "1"
  managedResources:
    cephBlockPools:
      reconcileStrategy: manage
```

## Pool Configuration

- Block pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS metadata pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- CephFS data pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- RGW metadata pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- RGW data pool: `replicated.size: 1`, `requireSafeReplicaSize: false`
- Single mon and single mgr (reduced counts for one failure domain).

## StorageClasses

- `lvms-vg1` remained the default StorageClass.
- `ocs-storagecluster-ceph-rbd` (non-default RBD).
- `ocs-storagecluster-cephfs` (non-default CephFS).
- `ocs-storagecluster-ceph-rgw` (RGW ObjectBucketClaim provisioning).
- `openshift-storage.noobaa.io` (MCG ObjectBucketClaim provisioning).

## Validation Notes

- After install, the `StorageCluster` reached `Ready` and `ceph -s` showed `HEALTH_OK`.
- One OSD was created on the dedicated LSO-provisioned disk.
- Smoke tests for RBD and CephFS passed.
- An ObjectBucketClaim created the expected Secret and ConfigMap against the MCG StorageClass.
- ODF metrics appeared in the OpenShift console **Storage → Data Foundation** dashboards using the built-in cluster Prometheus.
- Post-reboot checks showed mon in quorum, OSD up, MDS active, and cluster health remained `HEALTH_OK`.
