# Changelog

## 0.1.0

- Add a Single Node OpenShift skill for one replica of the internal image registry on a pre-created 100Gi ReadWriteOnce filesystem PVC.
- Keep the operator from generating a ReadWriteMany claim, and delete that PVC only by setting the registry management state to Removed while storage management stays Managed.
- Prove the PVC with an in-cluster `skopeo copy --remove-signatures`. An image import does not upload blobs.
- Wait out the single-node API rollout that follows `Managed`, and wait for the deployment to exist before `rollout status`. On redeploy, `already exists` for the registry service account and role binding clears on retry.
