# Validated SNO Internal Registry

Observed on OpenShift 4.18.56 with the image registry operator at 4.18.56 and LVM Storage operator 4.18.5. Topology was a single node. The only default StorageClass was `lvms-vg1` (`topolvm.io`, `xfs`, `Delete`, `WaitForFirstConsumer`). These are observed values, not defaults for every cluster.

## Deploy

The pre-created `image-registry-storage` PVC bound at 100Gi, `Filesystem`, `ReadWriteOnce`, on `lvms-vg1`. The registry deployment was `Recreate` with one ready replica. `default-route` was absent.

Setting `managementState: Managed` rolled `openshift-apiserver`. On the single node the replacement pod stayed `Pending` on pod anti-affinity until the terminating pod stopped serving. `kube-apiserver` also started a new static-pod revision. The registry pod stayed ready through that window. `image.openshift.io` and `route.openshift.io` returned `ServiceUnavailable` until `openshift-apiserver` was `Available` again.

`oc import-image --reference-policy=local` did not upload blobs. `du -sh /registry` stayed at 20K, and a pull of the imported tag still succeeded through pull-through. `skopeo copy` without `--remove-signatures` stored blobs and then failed while uploading signatures. The same copy with `--remove-signatures` logged `registry-push-ok`.

An `oc` 4.9 client rejects `oc wait --for=jsonpath`. Poll `.status.phase` instead. `oc get` prints `Completed` for a pod whose phase is `Succeeded`.

## Remove and redeploy

`managementState: Removed`, with storage management left `Managed`, deleted the registry deployment, the PVC, and its PV. The config kept `spec.storage.pvc.claim` and `spec.storage.managementState`. The config condition `Removed` became `True`. The image-registry cluster operator stayed `Available`.

`rollout status` immediately after the next `Managed` patch returned NotFound because the deployment did not exist yet. `status.observedGeneration` stayed one generation behind while the operator could not reach the API. It caught up on its own after `kube-apiserver` stopped progressing. The operator then logged `already exists` for `registry-registry-role`, the `registry` service account, and `image-registry-private-configuration`, and created the deployment on a later retry. The first registry pod was `Terminating` during that retry. The replacement became ready, and the new PVC bound.

Setting `Managed` again before the previous `kube-apiserver` revision finished started another revision. Wait for that operator to stop progressing between deploy, remove, and redeploy.

On the fresh PVC, `du -s /registry` was `0` before the push and `7092` after it. The pull pod used `image-registry.openshift-image-registry.svc:5000/<smoke-namespace>/pushed:9.5` and logged `registry-smoke-ok`.
