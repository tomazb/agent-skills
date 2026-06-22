# RGW Object Store

Use this runbook for creating and managing CephObjectStore (RGW/S3) on Rook Ceph.

## CephObjectStore Creation

Create a `CephObjectStore` with gateway and data pool settings. Plan replica counts and failure domains at creation time.

### Multi-Node Production

```yaml
apiVersion: ceph.rook.io/v1
kind: CephObjectStore
metadata:
  name: rook-ceph-rgw
  namespace: rook-ceph
spec:
  metadataPool:
    replicated:
      size: 3
      requireSafeReplicaSize: true
  dataPool:
    replicated:
      size: 3
      requireSafeReplicaSize: true
  gateway:
    type: s3
    port: 80
    securePort: 443
    instances: 2
    placement:
      nodeAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          nodeSelectorTerms:
          - matchExpressions:
            - key: node.ocs.openshift.io/storage
              operator: In
              values:
              - "true"
    resources:
      limits:
        memory: "2Gi"
      requests:
        memory: "1Gi"
```

### SNO

```yaml
apiVersion: ceph.rook.io/v1
kind: CephObjectStore
metadata:
  name: rook-ceph-rgw
  namespace: rook-ceph
spec:
  metadataPool:
    replicated:
      size: 1
      requireSafeReplicaSize: false
  dataPool:
    replicated:
      size: 1
      requireSafeReplicaSize: false
  gateway:
    type: s3
    port: 80
    instances: 1
    placement:
      all:
        tolerations:
        - key: "node.ocs.openshift.io/storage"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
    resources:
      limits:
        memory: "1Gi"
      requests:
        memory: "512Mi"
```

Do not copy `size: 1` or `requireSafeReplicaSize: false` into multi-node production plans without explicit direction.

## Object Bucket Claim (OBC) StorageClass

Create an OBC StorageClass for S3 bucket provisioning:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: rook-ceph-rgw-obc
provisioner: rook-ceph.ceph.rook.io/bucket
parameters:
  objectStoreName: rook-ceph-rgw
  objectStoreNamespace: rook-ceph
  region: us-east-1
reclaimPolicy: Delete
```

## Object Bucket Claim

Create an OBC to request an S3 bucket:

```yaml
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: rook-ceph-obc
  namespace: <app-namespace>
spec:
  generateBucketName: my-bucket
  storageClassName: rook-ceph-rgw-obc
```

## Validation

Check RGW health and object store status:

```bash
oc -n rook-ceph get cephobjectstores.ceph.rook.io
oc -n rook-ceph exec deploy/rook-ceph-tools -- ceph -s
oc -n rook-ceph get pods -l app=rook-ceph-rgw -o wide
```

Create a test OBC, verify:

- OBC is `Bound`.
- Secret with S3 credentials is created.
- ConfigMap with bucket endpoint is created.
- A bucket exists in the RGW object store.

## TLS and Ingress

TLS passthrough requires `securePort: 443` in the CephObjectStore `gateway` spec (multi-node example above includes it; add it to the SNO spec if TLS is needed there). Without `securePort`, the RGW service will not expose port 443 and the Route will fail to connect.

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: rook-ceph-rgw
  namespace: rook-ceph
spec:
  to:
    kind: Service
    name: rook-ceph-rgw-<objectstore-name>
  port:
    targetPort: https
  tls:
    termination: passthrough
    insecureEdgeTerminationPolicy: Redirect
```
