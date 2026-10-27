# Validate The SNO Internal Registry

Run this after deploy, and again after a redeploy. A previous `Removed` state still leaves the image-registry cluster operator `Available`, so these checks look at the deployment, the PVC, and a push plus a pull.

## Workload

```bash
target_context="<target-context>"
oc --context="$target_context" -n openshift-image-registry get deploy image-registry -o jsonpath='{.spec.strategy.type}{" "}{.spec.replicas}{" "}{.status.readyReplicas}{"\n"}'
oc --context="$target_context" -n openshift-image-registry get pvc image-registry-storage -o jsonpath='{.status.phase}{" "}{.spec.storageClassName}{" "}{.spec.volumeMode}{" "}{.spec.accessModes}{" "}{.status.capacity.storage}{"\n"}'
oc --context="$target_context" -n openshift-image-registry get pods -l docker-registry=default
oc --context="$target_context" get configs.imageregistry.operator.openshift.io cluster -o jsonpath='{.spec.managementState}{" "}{.spec.replicas}{" "}{.spec.rolloutStrategy}{" "}{.spec.storage.managementState}{" "}{.spec.storage.pvc.claim}{"\n"}'
oc --context="$target_context" -n openshift-image-registry get route default-route --ignore-not-found
```

Retry the route read after `openshift-apiserver` is `Available`. During the rollout that follows `Managed`, that API returns `ServiceUnavailable`, which is not evidence that `default-route` exists.

Pass requires `Recreate`, one ready replica, PVC `Bound` on the selected class, `volumeMode` `Filesystem`, access mode `ReadWriteOnce`, registry `managementState` `Managed`, storage `managementState` `Managed`, and claim `image-registry-storage`. No `default-route` is present unless the user asked for one.

## Push and pull

Use a new namespace. Refuse to reuse one that already exists. `oc import-image`, including `--reference-policy=local`, records image metadata and does not upload blobs. An empty registry filesystem stays a few kilobytes after an import, and a later pull can succeed through pull-through. Prove the PVC with an in-cluster `skopeo copy --remove-signatures`. Without `--remove-signatures` the copy writes blobs and then fails while uploading signatures.

Poll `.status.phase` instead of `oc wait --for=jsonpath`. That jsonpath condition is missing on older `oc` clients, and a completed pod's phase is `Succeeded` while `oc get` prints `Completed`.

```bash
smoke_namespace="registry-smoke"
existing=$(oc --context="$target_context" get namespace "$smoke_namespace" --ignore-not-found -o name)
if [ -n "$existing" ]; then
  echo "refusing to reuse existing namespace ${smoke_namespace}" >&2
  exit 1
fi
oc --context="$target_context" create namespace "$smoke_namespace"
before=$(oc --context="$target_context" -n openshift-image-registry exec deploy/image-registry -- du -s /registry)
python3 scripts/render_registry_push.py \
  --namespace "$smoke_namespace" \
  --source registry.access.redhat.com/ubi9/ubi-micro:9.5 \
  --destination "image-registry.openshift-image-registry.svc:5000/${smoke_namespace}/pushed:9.5" \
  --output /tmp/registry-smoke-push.yaml
oc --context="$target_context" apply -f /tmp/registry-smoke-push.yaml
wait_smoke_pod() {
  name="$1"
  phase=""
  for _ in $(seq 1 60); do
    phase=$(oc --context="$target_context" -n "$smoke_namespace" get pod "$name" -o jsonpath='{.status.phase}')
    if [ "$phase" = "Succeeded" ]; then
      return 0
    fi
    if [ "$phase" = "Failed" ]; then
      oc --context="$target_context" -n "$smoke_namespace" logs "pod/${name}"
      return 1
    fi
    sleep 5
  done
  echo "timed out waiting for ${name} phase=${phase}" >&2
  return 1
}
wait_smoke_pod registry-smoke-push
oc --context="$target_context" -n "$smoke_namespace" logs pod/registry-smoke-push | grep registry-push-ok
after=$(oc --context="$target_context" -n openshift-image-registry exec deploy/image-registry -- du -s /registry)
python3 scripts/render_registry_smoke.py \
  --namespace "$smoke_namespace" \
  --image "image-registry.openshift-image-registry.svc:5000/${smoke_namespace}/pushed:9.5" \
  --output /tmp/registry-smoke-pod.yaml
oc --context="$target_context" apply -f /tmp/registry-smoke-pod.yaml
wait_smoke_pod registry-smoke-pull
oc --context="$target_context" -n "$smoke_namespace" logs pod/registry-smoke-pull
oc --context="$target_context" delete namespace "$smoke_namespace" --wait=true
```

The push log must contain `registry-push-ok`. Compare the first field of `du -s /registry` as integers; `after` must be greater than `before`. A fresh PVC can report `0`. The pull log must be `registry-smoke-ok`, and the pull pod image must be the `pushed:9.5` tag. Delete only the smoke namespace. Leave `image-registry-storage` in place. Redact any credential that a failed `skopeo` log includes before saving the output.

A push or pull failure after the PVC is `Bound` is a registry failure, not a storage-class failure. Inspect the image-registry pod logs before changing storage.
