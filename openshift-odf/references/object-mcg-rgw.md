# Object Storage (MCG/NooBaa And RGW)

Use this runbook for S3-compatible object storage in ODF. ODF provides two object interfaces: the Multicloud Object Gateway (MCG/NooBaa), installed by default with the `StorageCluster`, and the Ceph RGW object store. Both are managed by ODF operators; do not create Rook `CephObjectStore` CRs by hand on an ODF cluster.

## MCG / NooBaa (default)

The `mcg-operator` deploys a `NooBaa` system in `openshift-storage` when the `StorageCluster` is created. Verify it is ready:

```bash
oc -n openshift-storage get noobaa noobaa -o wide
oc -n openshift-storage get pods -l app=noobaa -o wide
oc get sc openshift-storage.noobaa.io
```

MCG provisions S3 buckets through the `openshift-storage.noobaa.io` `ObjectBucketClaim` StorageClass and can tier to cloud backing stores. Change MCG behavior through the `NooBaa`/`BackingStore`/`BucketClass` CRs the operator owns, not by editing NooBaa pods directly.

## Ceph RGW object store

ODF also creates a Ceph RGW `CephObjectStore` (`ocs-storagecluster-cephobjectstore`) and the `ocs-storagecluster-ceph-rgw` StorageClass from the `StorageCluster`. Manage RGW replica policy through the `StorageCluster` `managedResources.cephObjectStores` settings, not by editing the Rook `CephObjectStore`:

```yaml
apiVersion: ocs.openshift.io/v1
kind: StorageCluster
metadata:
  name: ocs-storagecluster
  namespace: openshift-storage
spec:
  managedResources:
    cephObjectStores:
      reconcileStrategy: manage
```

### Multi-Node Production replica policy

RGW metadata and data pools use `replicated.size: 3` with `requireSafeReplicaSize: true`. The RGW gateway runs multiple instances for availability. Do not lower these for multi-node production without explicit direction.

### SNO

RGW metadata and data pools use `replicated.size: 1` with `requireSafeReplicaSize: false`, and a single RGW instance runs. Do not copy `size: 1` or `requireSafeReplicaSize: false` into multi-node production plans without explicit direction. On SNO, the extra RGW pools can push a single OSD above the default `mon_max_pg_per_osd` ceiling once rbd, cephfs, and RGW pools coexist; raise it deliberately through the documented `StorageCluster` override and record why.

## ObjectBucketClaim

Request an S3 bucket with an `ObjectBucketClaim`, referencing either the MCG or the RGW StorageClass:

```yaml
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: odf-obc
  namespace: <app-namespace>
spec:
  generateBucketName: my-bucket
  storageClassName: openshift-storage.noobaa.io
```

For an RGW-backed bucket instead of MCG, set `storageClassName: ocs-storagecluster-ceph-rgw`. ODF's RGW StorageClass uses the `openshift-storage.ceph.rook.io/bucket` provisioner.

## Validation

Check object store health and OBC binding:

```bash
oc -n openshift-storage get cephobjectstore ocs-storagecluster-cephobjectstore -o wide
oc -n openshift-storage get pods -l app=rook-ceph-rgw -o wide
oc -n openshift-storage exec deploy/rook-ceph-tools -- ceph -s
```

Create a test OBC in the `odf-rgw-smoke` namespace and verify:

- OBC is `Bound`.
- A Secret with S3 credentials is created.
- A ConfigMap with the bucket endpoint is created.
- The `ObjectBucket` resource exists and is bound to the OBC.

```bash
oc -n odf-rgw-smoke get objectbucketclaim odf-obc -o wide
oc -n odf-rgw-smoke get secret odf-obc
oc -n odf-rgw-smoke get configmap odf-obc
oc get objectbucket -o wide | grep odf-rgw-smoke || true
```

## S3 Route And TLS

ODF exposes the RGW service inside the cluster. To reach it externally, expose it through an OpenShift Route. Prefer edge termination so RGW stays plain HTTP internally and TLS terminates at the Route:

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: ocs-storagecluster-cephobjectstore
  namespace: openshift-storage
spec:
  to:
    kind: Service
    name: rook-ceph-rgw-ocs-storagecluster-cephobjectstore
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

For MCG, the S3 endpoint is published by NooBaa; read it from the `NooBaa` status or the `noobaa` service and expose it through a Route the same way. Enable RGW/MCG TLS via Route for production.
