# Deploy The SNO Internal Registry

Use this runbook to bring up one replica of the OpenShift internal image registry on a filesystem ReadWriteOnce volume.

## Discovery

```bash
target_context="<target-context>"
oc --context="$target_context" version
oc --context="$target_context" get nodes --no-headers
oc --context="$target_context" get configs.imageregistry.operator.openshift.io cluster -o yaml
oc --context="$target_context" -n openshift-image-registry get deploy,pods,pvc,route
oc --context="$target_context" get sc -o json > /tmp/registry-storage-classes.json
python3 scripts/select_registry_storage.py --input /tmp/registry-storage-classes.json
```

Stop when the cluster has more than one node unless the user explicitly asked for this single-replica layout anyway.

Read the selector JSON:

- `use-class` continues below. `precreatePVC` is true. The PVC names `storageClass` explicitly, including when that class is the default.
- `install-lvms` means no filesystem class exists. Follow `openshift-lvm-storage` `references/install-and-preflight.md`, including its disk confirmation gates. When that install is Ready, run the selector again.
- `stop` means the default class cannot hold the registry, or the choice is ambiguous. Report `reason` and wait for a named class or a default-class fix. Pass `--storage-class <name>` only after the user names one.

When the user names a class:

```bash
python3 scripts/select_registry_storage.py \
  --input /tmp/registry-storage-classes.json \
  --storage-class "<storage-class>"
```

Honor `warnings`. `reclaimPolicy: Delete` means removing the PVC deletes the registry images. `WaitForFirstConsumer` means the PVC stays `Pending` until the registry pod is scheduled.

Stop when `spec.storage` already contains `s3`, `azure`, `gcs`, `swift`, `oss`, or `ibmcos`. This runbook does not replace object storage. Stop when `spec.defaultRoute` is true unless the user wants the route to stay.

## Why the PVC is pre-created

On OpenShift 4.18, an empty `spec.storage.pvc.claim` makes the image registry operator create `image-registry-storage` as ReadWriteMany at 100Gi and then write that claim name back into the config. LVM Storage serves ReadWriteOnce and ReadWriteOncePod, so that generated claim stays `Pending`. A PVC that already exists without the operator annotation `imageregistry.openshift.io` makes the empty-claim path fail with "not owned by the operator".

Create the claim first, with ReadWriteOnce and `volumeMode: Filesystem`, and set `spec.storage.pvc.claim` to `image-registry-storage`. The operator then uses that claim. It does not recreate an explicitly named claim after `Removed` deletes it, so a redeploy creates the PVC again before returning the config to `Managed`.

## Create the PVC

Confirm `openshift-image-registry` exists. The registry operator creates that namespace; do not invent a replacement.

A fresh deploy has no `image-registry-storage` claim. Render 100Gi and apply it. A redeploy after `Removed` is the same case, because that removal deletes the claim and the operator does not recreate an explicitly named ReadWriteOnce claim.

If the claim is still there, do not apply the 100Gi manifest over it. `python3 scripts/decide_registry_pvc.py` returns `create`, `reuse`, or `stop`:

- `create`: no claim. Apply the rendered manifest.
- `reuse`: the claim is `image-registry-storage` in `openshift-image-registry`, `ReadWriteOnce`, filesystem, the selected StorageClass, and at least 100Gi. Skip apply. Leave its data, requested capacity, StorageClass, and access modes as they are. A request larger than 100Gi is reusable; applying 100Gi would try to shrink it.
- `stop`: the claim exists but is smaller than 100Gi, is already being deleted, is a block volume, has another access mode, uses another class, or is in a bad phase. Exit. Do not apply and do not delete the claim.

```bash
python3 scripts/render_registry_pvc.py \
  --storage-class "<storage-class>" \
  --size 100Gi \
  --output /tmp/image-registry-storage.yaml

pvc_file=/tmp/image-registry-storage-existing.json
pvc_err=/tmp/image-registry-storage-existing.err
if oc --context="$target_context" -n openshift-image-registry get pvc image-registry-storage -o json >"$pvc_file" 2>"$pvc_err"; then
  if ! decision=$(python3 scripts/decide_registry_pvc.py --storage-class "<storage-class>" --input "$pvc_file"); then
    printf '%s\n' "$decision" >&2
    echo "existing image-registry-storage claim is incompatible; not applying and not deleting" >&2
    exit 1
  fi
elif grep -q 'NotFound' "$pvc_err"; then
  decision=$(python3 scripts/decide_registry_pvc.py --storage-class "<storage-class>" --missing)
else
  cat "$pvc_err" >&2
  echo "could not read image-registry-storage; not applying a claim" >&2
  exit 1
fi
action=$(printf '%s' "$decision" | python3 -c 'import json,sys; print(json.load(sys.stdin)["action"])')
case "$action" in
  create)
    oc --context="$target_context" apply -f /tmp/image-registry-storage.yaml
    ;;
  reuse)
    echo "keeping the existing image-registry-storage claim; not applying a new size"
    ;;
  *)
    printf '%s\n' "$decision" >&2
    echo "existing image-registry-storage claim is incompatible; not applying and not deleting" >&2
    exit 1
    ;;
esac
```

A `Pending` PVC here is expected when the class uses `WaitForFirstConsumer`. Pending is still reusable when the spec checks pass.

## Confirm the API is quiet

Do this immediately before the Managed patch. That patch rolls `openshift-apiserver` on a single node and can start a `kube-apiserver` revision. Do not patch while `kube-apiserver` is unavailable, degraded, or still progressing. The loop below polls for up to five minutes and exits nonzero when the gate does not pass.

```bash
ready=0
for _ in $(seq 1 60); do
  if oc --context="$target_context" get clusteroperator kube-apiserver -o json > /tmp/kube-apiserver.json \
    && python3 scripts/check_api_readiness.py --input /tmp/kube-apiserver.json; then
    ready=1
    break
  fi
  sleep 5
done
if [ "$ready" != 1 ]; then
  echo "kube-apiserver is not ready; not patching the registry" >&2
  oc --context="$target_context" get clusteroperator kube-apiserver || true
  exit 1
fi
```

## Patch the registry config

Render the Managed patch. Add `--clear-emptydir` only when `spec.storage.emptyDir` is already set. The patch sets `managementState: Managed`, `replicas: 1`, `rolloutStrategy: Recreate`, `spec.storage.managementState: Managed`, and `spec.storage.pvc.claim: image-registry-storage`. It does not set `defaultRoute`.

```bash
python3 scripts/render_registry_config.py \
  --management-state Managed \
  --output /tmp/registry-managed.json

oc --context="$target_context" patch configs.imageregistry.operator.openshift.io cluster \
  --type merge --patch-file /tmp/registry-managed.json
```

`spec.storage.managementState: Managed` is what makes a later `Removed` delete this PVC. The operator's own empty-claim path would set that field; an explicit claim leaves it Unmanaged unless this patch sets it.

Wait until the operator has observed the patch and created the deployment. `rollout status` returns NotFound until that deployment exists. After a `Removed` cycle, `status.observedGeneration` can stay behind `metadata.generation` while `kube-apiserver` is rolling and the operator cannot reach the API. Wait for the API before treating that lag as a failed deploy.

```bash
for _ in $(seq 1 60); do
  generation=$(oc --context="$target_context" get configs.imageregistry.operator.openshift.io cluster -o jsonpath='{.metadata.generation}')
  observed=$(oc --context="$target_context" get configs.imageregistry.operator.openshift.io cluster -o jsonpath='{.status.observedGeneration}')
  deploy_name=$(oc --context="$target_context" -n openshift-image-registry get deploy image-registry --ignore-not-found -o name || true)
  if [ "$generation" = "$observed" ] && [ -n "$deploy_name" ]; then
    break
  fi
  sleep 5
done
if [ "$generation" != "$observed" ] || [ -z "$deploy_name" ]; then
  echo "registry did not observe the Managed patch or the deployment was not created" >&2
  exit 1
fi
oc --context="$target_context" -n openshift-image-registry rollout status deploy/image-registry --timeout=10m
oc --context="$target_context" -n openshift-image-registry get pvc image-registry-storage
oc --context="$target_context" -n openshift-image-registry get pods -l docker-registry=default
```

The deployment must be `Recreate` with one ready replica. The PVC must be `Bound` to the selected class. One pod carries `docker-registry=default`.

On a redeploy, removal leaves the `registry` service account, the `registry-registry-role` ClusterRoleBinding, and the `image-registry-private-configuration` Secret in place. The operator logs `already exists` for those objects, retries, and then creates the deployment. Leave those objects alone. The first registry pod can be `Terminating` during that retry; wait for `readyReplicas` 1.

Moving the registry from `Removed` to `Managed` publishes the internal registry into the API servers. On a single node this rolls `openshift-apiserver`, and it can also start a new `kube-apiserver` revision. The replacement `openshift-apiserver` pod stays `Pending` on pod anti-affinity until the terminating pod stops serving. While that pod is absent, `route.openshift.io` and `image.openshift.io` return `ServiceUnavailable`. The registry deployment can already be ready. Wait until `openshift-apiserver` is `Available` and `kube-apiserver` is not `Progressing` before the smoke in `references/validation.md`.
