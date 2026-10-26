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

### Repeatable object smoke

After the product ownership gate, use the packaged helper with an approved,
pinned image containing Python 3 and compatible with restricted SCC:

```bash
python3 scripts/check_object_smoke.py --context "<target-context>" \
  --namespace openshift-storage --storage-class ocs-storagecluster-ceph-rgw \
  --image "<approved-python-image>@sha256:<digest>" \
  --tls-ca service-ca --ca-configmap "<injected-service-ca-configmap>"
```

For MCG, replace the class with `openshift-storage.noobaa.io`. The helper uses the
NooBaa provisioner/readiness path, not RGW's namespace watch configuration. For
RGW it resolves the operator's effective OBC watch scope, including ConfigMap
references. It never broadens the scope to run a test.

The CA ConfigMap must already contain the correct injected service CA, or use
`--tls-ca /etc/rgw-ca/ca-bundle.crt --ca-configmap <private-ca-configmap>` for a
private CA. Publicly trusted endpoints use `--tls-ca public` without a CA mount.
Verify TLS; do not assume that a service-account projection contains the required
CA on every platform. Only a trusted in-cluster HTTP path permits `--allow-http`.

Pass requires PUT, GET byte comparison, DELETE, confirmation of object deletion,
and verified cleanup of the owned pod, OBC, ObjectBucket, Secret, and ConfigMap.
Credentials remain inside the pod. Failed tests stay failed after successful
cleanup; UID changes or unverified cleanup stop with an error. No namespace,
StorageClass, StorageCluster, existing bucket, or supplied CA ConfigMap is deleted.

### Manual provisioning checks

The following checks establish provisioning only; they do not replace the S3
roundtrip. Their namespace-deletion cleanup applies only to disposable smoke
namespaces, never the operator namespace used by the helper above.

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
buckets="$(oc get objectbucket -o json)" || exit 1
printf '%s' "$buckets" | python3 -c '
import json, sys
data = json.load(sys.stdin)
items = data.get("items") or []
found = False
for item in items:
    claim = (item.get("spec") or {}).get("claimRef") or {}
    if claim.get("namespace") == "odf-rgw-smoke" and claim.get("name") == "odf-obc":
        found = True
        break
if not found:
    sys.stderr.write("no ObjectBucket claims odf-rgw-smoke/odf-obc\n")
    sys.exit(1)
' || exit 1
bash scripts/cleanup_smoke_namespace.sh --namespace odf-rgw-smoke --object
```

Create that test claim in `odf-rgw-smoke` only. The check above exits before cleanup unless an ObjectBucket `claimRef` is exactly namespace `odf-rgw-smoke` and name `odf-obc`. The cleanup command then deletes that namespace and fails if an ObjectBucket still claims it. A bucket whose name merely contains `odf-rgw-smoke` belongs to whatever namespace its `claimRef` names.

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


### Schema-pruned bucket references

Some OLM-managed ObjectBucket schemas prune every `spec.claimRef` field. The
smoke helper accepts an exactly empty reference only when the served structural
CRD schema proves pruning and field preservation is disabled. It verifies the
run-owned Bound OBC's authoritative `spec.objectBucketName`, both object UIDs,
a bucket absent from the pre-test inventory, matching Delete policy/StorageClass,
and the exact generated bucket identity. The result reports
`binding_source: claim-forward-reference`; retain a schema compatibility warning
alongside the passing data-path result. Other schemas require a normal reverse
reference, and contradictory references always fail. The helper never patches
the shared CRD.

Cleanup recovers the forward binding before deleting the owned claim and tracks
new run-prefixed buckets even after a committed-create timeout. It requires their
disappearance and never manually deletes global ObjectBuckets. Unverified identity
or cleanup fails the test. This follows the library's
[authoritative OBC binding contract](https://github.com/kube-object-storage/lib-bucket-provisioner/blob/master/pkg/apis/objectbucket.io/v1alpha1/objectbucket_types.go).
