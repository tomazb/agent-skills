# Remove The SNO Internal Registry

Use this runbook only after the user explicitly confirms undeploy on the named `oc` context. `spec.managementState: Removed` deletes the registry deployment. When `spec.storage.managementState` is `Managed`, the operator also deletes the claim recorded in `status.storage`. With `reclaimPolicy: Delete`, that deletion removes the volume and every image stored in it.

Wait until `kube-apiserver` is not `Progressing` before this patch. Setting `Managed` rolls that operator on a single node, and removing the registry again before the rollout finishes queues another revision. After this runbook finishes, wait for `kube-apiserver` to stop progressing before the next deploy.

## Patch

Change only the registry management state. Leave `spec.storage` in place for this patch. Clearing the claim or storage management state in the same patch makes `RemoveStorage` return without deleting the PVC. The operator reads the claim name from `status.storage` and deletes it only while `spec.storage.managementState` is still `Managed`.

```bash
target_context="<target-context>"

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
  echo "kube-apiserver is not ready; not removing the registry" >&2
  oc --context="$target_context" get clusteroperator kube-apiserver || true
  exit 1
fi

python3 scripts/render_registry_config.py \
  --management-state Removed \
  --output /tmp/registry-removed.json

oc --context="$target_context" patch configs.imageregistry.operator.openshift.io cluster \
  --type merge --patch-file /tmp/registry-removed.json
```

## Wait

```bash
for _ in $(seq 1 60); do
  if [ -z "$(oc --context="$target_context" -n openshift-image-registry get deploy image-registry --ignore-not-found -o name)" ]; then
    break
  fi
  sleep 5
done
oc --context="$target_context" -n openshift-image-registry get deploy image-registry --ignore-not-found
oc --context="$target_context" -n openshift-image-registry get pods -l docker-registry=default
if oc --context="$target_context" -n openshift-image-registry get pvc image-registry-storage --ignore-not-found -o name | grep -q .; then
  oc --context="$target_context" -n openshift-image-registry wait pvc/image-registry-storage --for=delete --timeout=10m
fi
oc --context="$target_context" get pv -o json | python3 scripts/registry_pv_audit.py
```

Done means all of the following:

- `configs.imageregistry.operator.openshift.io/cluster` has `spec.managementState: Removed`.
- No pod with label `docker-registry=default`.
- PVC `image-registry-storage` is gone.
- No PV whose `claimRef.name` is `image-registry-storage` and whose `claimRef.namespace` is `openshift-image-registry`. `python3 scripts/registry_pv_audit.py` exits nonzero when one remains. The same claim name in another namespace is not this registry's volume.

The image-registry cluster operator can remain `Available` after a successful removal. `status.conditions` type `Removed` is the config-level signal. The operator, `node-ca` daemon, and image pruner stay in `openshift-image-registry`.

If the PVC remains, `spec.storage.managementState` was not `Managed` or the delete is stuck. Report the PVC and its finalizers. Do not delete it by hand without a separate confirmation.

A later deploy follows `references/deploy.md` from the start, including a new PVC. The operator does not recreate an explicitly named ReadWriteOnce claim.
