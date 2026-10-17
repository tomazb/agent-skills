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
```

If an OpenShift Route was deployed (see the TLS and Ingress section below), also check:

```bash
oc -n rook-ceph get route rook-ceph-rgw -o wide
```

Create the test claim in `rook-rgw-smoke`, not in an application namespace. Cleanup deletes that namespace. Verify:

- OBC is `Bound`.
- Secret with S3 credentials is created.
- ConfigMap with bucket endpoint is created.
- The `ObjectBucket` resource exists and is bound to the OBC.
- The RGW Route returns an HTTP response from `Ceph Object Gateway`
  (for example `200`, `403`, or `405`) instead of a TLS or connection failure.

```bash
(
set -euo pipefail
oc apply -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: rook-rgw-smoke
---
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: rook-ceph-obc
  namespace: rook-rgw-smoke
spec:
  generateBucketName: my-bucket
  storageClassName: rook-ceph-rgw-obc
EOF
oc wait -n rook-rgw-smoke objectbucketclaim/rook-ceph-obc \
  --for=jsonpath='{.status.phase}'=Bound --timeout=300s
oc -n rook-rgw-smoke get objectbucketclaim rook-ceph-obc -o wide
oc -n rook-rgw-smoke get secret rook-ceph-obc
oc -n rook-rgw-smoke get configmap rook-ceph-obc
claim_ref=$(oc get objectbucket obc-rook-rgw-smoke-rook-ceph-obc \
  -o jsonpath='{.spec.claimRef.namespace}/{.spec.claimRef.name}')
if [ "$claim_ref" != "rook-rgw-smoke/rook-ceph-obc" ]; then
  printf 'ObjectBucket claims %s; expected rook-rgw-smoke/rook-ceph-obc\n' "$claim_ref" >&2
  exit 1
fi
curl -kI "https://$(oc -n rook-ceph get route rook-ceph-rgw -o jsonpath='{.spec.host}')"
)
```

Proceed only if the block succeeds and the ObjectBucket claims exactly `rook-rgw-smoke/rook-ceph-obc`. The subshell returns query and claim-validation failures without changing the caller's shell options. A `Bound` OBC with a ConfigMap and a Secret proves provisioning only. Put an object and read it back from `rook-rgw-smoke` before deleting that namespace. The ConfigMap supplies `BUCKET_HOST`, `BUCKET_PORT`, and `BUCKET_NAME`; the Secret supplies `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. Wire both with `envFrom`. The default gateway listens on HTTP port 8080. Use `http` for `80` and `8080` only when pod-to-gateway traffic stays on a trusted in-cluster network. For an untrusted path, require an HTTPS endpoint. RGW pod termination needs `securePort: 8443` and `gateway.sslCertificateRef`, as shown in the TLS section below. An edge-terminated HTTPS Route remains valid when its router-to-RGW HTTP hop is trusted. For `443` and `8443`, use `https` and set `RGW_TLS_CA` from the certificate source. Keep verification enabled. `service-ca` uses an injected service CA mounted into the pod, and only when `gateway.sslCertificateRef` is an OpenShift serving certificate (`service.beta.openshift.io/serving-cert-secret-name`). `public` uses the image trust store for a publicly trusted certificate. A private CA is a bundle mounted into the pod, and `RGW_TLS_CA` is that path.

Choose one trust source before creating the pod. The Pod block below expands `RGW_TLS_CA` from your shell, defaults to `public`, and mounts the optional `rgw-smoke-ca` ConfigMap at `/etc/rgw-ca`.

For HTTP on a trusted network or HTTPS with a publicly trusted certificate, use the image trust store. No CA ConfigMap is needed:

```bash
export RGW_TLS_CA=public
```

For an OpenShift service serving certificate, inject the service CA and wait for its key before creating the pod ([OpenShift service CA injection](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/security_and_compliance/configuring-certificates)):

```bash
export RGW_TLS_CA=service-ca
(
set -euo pipefail
oc apply -n rook-rgw-smoke -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: rgw-smoke-ca
  annotations:
    service.beta.openshift.io/inject-cabundle: "true"
EOF
oc wait -n rook-rgw-smoke configmap/rgw-smoke-ca \
  --for=jsonpath='{.data.service-ca\.crt}' --timeout=120s
)
```

For a private CA, replace the file path with the CA bundle that issued the gateway certificate. Use this alternative instead of the injected ConfigMap. The block below first reads the private CA file and renders a new ConfigMap locally. A missing or unreadable file stops the switch before changing the existing ConfigMap. It then replaces the throwaway ConfigMap so any old service-CA injection annotation cannot overwrite the private bundle. Recreate the smoke Pod afterward:

```bash
export RGW_TLS_CA=/etc/rgw-ca/ca-bundle.crt
(
set -euo pipefail
private_ca_manifest=$(oc create configmap rgw-smoke-ca -n rook-rgw-smoke \
  --from-file=ca-bundle.crt=/path/to/ca-bundle.pem --dry-run=client -o yaml)
oc delete configmap rgw-smoke-ca -n rook-rgw-smoke --ignore-not-found
printf '%s\n' "$private_ca_manifest" | oc apply -n rook-rgw-smoke -f -
)
```

Proceed only after the chosen preparation succeeds. Recreate the throwaway Pod after changing its environment or mounts. Create it in `rook-rgw-smoke`; it runs under the restricted pod security profile and idles so the check runs in it with `oc exec`:

```bash
oc apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: rgw-smoke
  namespace: rook-rgw-smoke
spec:
  containers:
  - name: s3
    image: registry.access.redhat.com/ubi9/python-311
    command: ["sleep", "3600"]
    env:
    - name: HOME
      value: /tmp
    - name: RGW_TLS_CA
      value: "${RGW_TLS_CA:-public}"
    envFrom:
    - configMapRef:
        name: rook-ceph-obc
    - secretRef:
        name: rook-ceph-obc
    volumeMounts:
    - name: rgw-ca
      mountPath: /etc/rgw-ca
      readOnly: true
    securityContext:
      allowPrivilegeEscalation: false
      runAsNonRoot: true
      capabilities:
        drop: ["ALL"]
      seccompProfile:
        type: RuntimeDefault
  volumes:
  - name: rgw-ca
    configMap:
      name: rgw-smoke-ca
      optional: true
EOF
oc -n rook-rgw-smoke wait pod/rgw-smoke --for=condition=Ready --timeout=5m
oc -n rook-rgw-smoke exec rgw-smoke -- pip install --user boto3
```

`registry.access.redhat.com/ubi9/python-311` needs `pip install boto3`, which needs egress. A disconnected cluster needs a mirrored image that already has an S3 client; replace `image` and skip the `pip install` line. Save the script below as `smoke.py` and run it with `oc -n rook-rgw-smoke exec -i rgw-smoke -- python3 - < smoke.py`.

```python
import boto3, os
host = os.environ["BUCKET_HOST"].rstrip("/")
port = os.environ["BUCKET_PORT"]
if "://" not in host:
    scheme = "https" if port in ("443", "8443") else "http"
    host = scheme + "://" + host
ep = "%s:%s" % (host, port)
kwargs = dict(
    endpoint_url=ep,
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
)
if host.startswith("https://"):
    ca = os.environ.get("RGW_TLS_CA", "")
    if ca == "service-ca":
        kwargs["verify"] = "/etc/rgw-ca/service-ca.crt"
    elif ca == "public":
        pass
    elif ca.startswith("/"):
        kwargs["verify"] = ca
    else:
        raise SystemExit("set RGW_TLS_CA to service-ca, public, or a mounted CA bundle path")
s3 = boto3.client("s3", **kwargs)
b = os.environ["BUCKET_NAME"]
s3.put_object(Bucket=b, Key="smoke-probe", Body=b"rook-rgw-smoke-ok")
assert s3.get_object(Bucket=b, Key="smoke-probe")["Body"].read() == b"rook-rgw-smoke-ok"
s3.delete_object(Bucket=b, Key="smoke-probe")
```

Any S3 client is enough; the check is that the PUT is readable back by GET. After the GET matches, run the existing cleanup:

```bash
bash scripts/cleanup_smoke_namespace.sh --namespace rook-rgw-smoke --object
```

`--object` fails the cleanup when an ObjectBucket `claimRef` still names `rook-rgw-smoke`. Deleting the namespace does not by itself prove the bucket object is gone.

## TLS and Ingress

On OpenShift, expose RGW through a Route. The RGW service exposes a port named
`http` (and `https` only when `securePort` is set). Two common patterns:

### Edge termination (simplest — RGW stays HTTP)

The Route terminates TLS at the edge and talks plain HTTP (`port: 8080`) to the
RGW service. No certificate or `securePort` is needed on the RGW pod. Use this
pattern only when the router-to-RGW network is trusted; an untrusted backend
path needs pod TLS with passthrough or reencrypt termination.

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
