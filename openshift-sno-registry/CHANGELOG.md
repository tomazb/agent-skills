# Changelog

## 0.2.0

- Record the validated OpenShift 5.0.1 SNO deployment with an LVMS 5.0.0 filesystem claim and API readiness checks.
- Refresh the smoke runbook with a public Skopeo image and separate upstream image failures from internal registry failures.
- Allow SHA-256 digests for source and tool images, keep credentialed destinations restricted to internal registry tags in the smoke namespace, and resolve the pushed tag with `imagePullPolicy: Always`.

## 0.1.1

- Send registry push credentials only to the internal image-registry service in the smoke namespace. Take the source and skopeo images as arguments, and keep tokens out of manifests and validator errors.
- Keep an existing compatible registry PVC, including one larger than 100Gi, and refuse to apply a smaller claim over it.
- Judge the smoke by `registry-push-ok` and the pull-back marker. Filesystem growth is a diagnostic, so a repeated push of the same blob can pass.
- Wait until `kube-apiserver` is available and not progressing before setting the registry to `Managed` or `Removed`.
- Match leftover registry PVs on both claim name and claim namespace.
- Parse skill frontmatter with YAML, and ignore Markdown headings inside fences indented by up to three spaces.
- Stop when the registry claim is already being deleted.
- Treat an empty or malformed PVC document as a refusal. Create a claim only after an explicit NotFound.
- Leave the smoke namespace in place when the push or pull check fails.

## 0.1.0

- Add a Single Node OpenShift skill for one replica of the internal image registry on a pre-created 100Gi ReadWriteOnce filesystem PVC.
- Keep the operator from generating a ReadWriteMany claim, and delete that PVC only by setting the registry management state to Removed while storage management stays Managed.
- Prove the PVC with an in-cluster `skopeo copy --remove-signatures`. An image import does not upload blobs.
- Wait out the single-node API rollout that follows `Managed`, and wait for the deployment to exist before `rollout status`. On redeploy, `already exists` for the registry service account and role binding clears on retry.
