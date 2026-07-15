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
    # On OpenShift the RGW pod runs as a non-root, arbitrary UID and cannot bind
    # privileged ports (<1024). Use 8080 for HTTP. To enable HTTPS, set a
    # non-privileged securePort (e.g. 8443) and gateway.sslCertificateRef — see
    # "TLS and Ingress" below. There is no gateway.type field.
    port: 8080
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
    # Use 8080 (non-privileged) — RGW runs non-root on OpenShift. No gateway.type field.
    port: 8080
    instances: 1
    placement:
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

On SNO, the extra RGW pools can push a single OSD above the default
`mon_max_pg_per_osd` ceiling once RBD, CephFS, and RGW all coexist. If
`ceph health detail` warns about too many PGs per OSD, raise
`CephCluster.spec.cephConfig.global.mon_max_pg_per_osd` deliberately (for
example `500`) and record why the override is needed.

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
oc -n rook-ceph get route rook-ceph-rgw -o wide
```

Create a test OBC, verify:

- OBC is `Bound`.
- Secret with S3 credentials is created.
- ConfigMap with bucket endpoint is created.
- The `ObjectBucket` resource exists and is bound to the OBC.
- The RGW Route returns an HTTP response from `Ceph Object Gateway`
  (for example `200`, `403`, or `405`) instead of a TLS or connection failure.

Example checks:

```bash
oc -n rook-rgw-smoke get objectbucketclaim rook-ceph-obc -o wide
oc -n rook-rgw-smoke get secret rook-ceph-obc
oc -n rook-rgw-smoke get configmap rook-ceph-obc
oc get objectbucket obc-rook-rgw-smoke-rook-ceph-obc -o wide
curl -kI "https://$(oc -n rook-ceph get route rook-ceph-rgw -o jsonpath='{.spec.host}')"
```

## TLS and Ingress

On OpenShift, expose RGW through a Route. The RGW service exposes a port named
`http` (and `https` only when `securePort` is set). Two common patterns:

### Edge termination (simplest — RGW stays HTTP)

The Route terminates TLS at the edge and talks plain HTTP (`port: 8080`) to the
RGW service. No certificate or `securePort` is needed on the RGW pod.

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
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

### Passthrough / reencrypt (RGW terminates TLS)

To terminate TLS at the RGW pod, set a non-privileged `securePort` (e.g. `8443`,
**not** 443 — the non-root RGW cannot bind privileged ports) and reference a TLS
secret in the `rook-ceph` namespace via `gateway.sslCertificateRef`. Without a
certificate the secure port is not served and a passthrough Route will fail to
connect.

```yaml
spec:
  gateway:
    port: 8080
    securePort: 8443
    sslCertificateRef: <tls-secret-name>   # secret in rook-ceph, type kubernetes.io/tls
    instances: 1
```

You can let OpenShift generate the serving certificate by annotating the RGW
service with `service.beta.openshift.io/serving-cert-secret-name: <secret>` and
referencing that secret in `sslCertificateRef`. Then use a passthrough (or
reencrypt) Route targeting the `https` port:

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
