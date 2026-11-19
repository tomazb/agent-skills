# Validated SNO Internal Registry

## OpenShift 5.0.1 with LVMS 5.0.0

- The registry started in `Removed` with no registry PVC. A pre-created 100Gi `Filesystem`, `ReadWriteOnce` claim bound on `lvms-vg1` (`topolvm.io`, `xfs`, `Delete`, `WaitForFirstConsumer`).
- The explicit claim and `Recreate` rollout produced one ready registry replica. The deployment used the claim, and the default route was absent.
- `openshift-apiserver` and `kube-apiserver` rolled after the `Managed` patch. The registry replica became ready before the API servers settled. The push and pull ran after both API operators recovered.
- The upstream registry rejected the previous UBI and Skopeo example image requests. Using `quay.io/skopeo/stable:latest` as both source and tool produced `registry-push-ok`. The pull resolved the pushed tag from the internal registry, ran with `imagePullPolicy: Always`, and logged `registry-smoke-ok`.
- Registry disk usage grew from 0 to 90,636 KiB after the push. The smoke namespace was deleted and the registry remained ready.

## OpenShift 4.18.56 with LVMS 4.18.5

Observed on OpenShift 4.18.56 with the image registry operator at 4.18.56 and LVM Storage operator 4.18.5. Topology was a single node. The only default StorageClass was `lvms-vg1` (`topolvm.io`, `xfs`, `Delete`, `WaitForFirstConsumer`). These are observed values, not defaults for every cluster.

### Deploy

The pre-created `image-registry-storage` PVC bound at 100Gi, `Filesystem`, `ReadWriteOnce`, on `lvms-vg1`. The registry deployment was `Recreate` with one ready replica. `default-route` was absent.

Setting `managementState: Managed` rolled `openshift-apiserver`. On the single node the replacement pod stayed `Pending` on pod anti-affinity until the terminating pod stopped serving. `kube-apiserver` also started a new static-pod revision. The registry pod stayed ready through that window. `image.openshift.io` and `route.openshift.io` returned `ServiceUnavailable` until `openshift-apiserver` was `Available` again.

`oc import-image --reference-policy=local` did not upload blobs. `du -sh /registry` stayed at 20K, and a pull of the imported tag still succeeded through pull-through. `skopeo copy` without `--remove-signatures` stored blobs and then failed while uploading signatures. The same copy with `--remove-signatures` logged `registry-push-ok`.

An `oc` 4.9 client rejects `oc wait --for=jsonpath`. Poll `.status.phase` instead. `oc get` prints `Completed` for a pod whose phase is `Succeeded`.

### Remove and redeploy

`managementState: Removed`, with storage management left `Managed`, deleted the registry deployment, the PVC, and its PV. The config kept `spec.storage.pvc.claim` and `spec.storage.managementState`. The config condition `Removed` became `True`. The image-registry cluster operator stayed `Available`.

`rollout status` immediately after the next `Managed` patch returned NotFound because the deployment did not exist yet. `status.observedGeneration` stayed one generation behind while the operator could not reach the API. It caught up on its own after `kube-apiserver` stopped progressing. The operator then logged `already exists` for `registry-registry-role`, the `registry` service account, and `image-registry-private-configuration`, and created the deployment on a later retry. The first registry pod was `Terminating` during that retry. The replacement became ready, and the new PVC bound.

Setting `Managed` again before the previous `kube-apiserver` revision finished started another revision. Wait for that operator to stop progressing between deploy, remove, and redeploy.

On the fresh PVC, `du -s /registry` was `0` before the push and `7092` after it. Those numbers are diagnostics from an empty volume. A later push of the same blob does not have to grow the filesystem; the smoke passes on `registry-push-ok` and a pull of the pushed tag. The pull pod used `image-registry.openshift-image-registry.svc:5000/<smoke-namespace>/pushed:9.5` and logged `registry-smoke-ok`.
