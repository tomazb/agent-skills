---
name: openshift-sno-registry
description: Use when installing, configuring, validating, redeploying, removing, or troubleshooting the OpenShift/OKD internal image registry on Single Node OpenShift, including persistent storage selection and an LVM Storage fallback when no filesystem StorageClass is available.
---

# OpenShift SNO Internal Registry

Use this skill to run one replica of the OpenShift internal image registry on a single-node cluster. Drive `configs.imageregistry.operator.openshift.io/cluster`. Do not deploy a second registry.

## Routing

- **Discovery or deploy**: `references/deploy.md`.
- **Smoke test or post-deploy checks**: `references/validation.md`. Observed SNO evidence is in `references/validated-sno.md`.
- **Remove the registry instance and the PVC it mounts**: `references/undeploy.md`.
- **No filesystem StorageClass**: follow `openshift-lvm-storage`, then return here. Do not copy LVMS disk steps into this skill.

## Core Safety Rules

- Confirm the `oc` context before creating the PVC or patching the registry config.
- Apply this single-replica ReadWriteOnce layout only after confirming the cluster has one node, unless the user explicitly asks for that layout on a larger cluster.
- Pre-create `image-registry-storage` as a filesystem ReadWriteOnce PVC of at least 100Gi. On OpenShift 4.18 a blank `spec.storage.pvc.claim` makes the operator create a ReadWriteMany 100Gi claim, which does not bind on LVM Storage. When a compatible claim already exists, keep it, including one larger than 100Gi. Do not apply a smaller request over it.
- Require `kube-apiserver` to be Available, not Progressing, and not Degraded before a `Managed` or `Removed` patch. Do not patch when that check fails.
- Set `rolloutStrategy: Recreate` and `replicas: 1` in the same change that points the registry at that PVC. ReadWriteOnce with `RollingUpdate` fails operator validation.
- Set `spec.storage.managementState: Managed` so a later `Removed` deletes the PVC. Undeploy changes only `spec.managementState`. Clearing storage in that patch skips PVC deletion.
- `Removed` deletes registry contents when storage is Managed and the StorageClass reclaim policy is Delete. Require explicit confirmation before undeploy.
- Leave `defaultRoute` unchanged unless the user asks to expose the registry. Do not use `emptyDir` for this skill. When `emptyDir` is already set, clear it in the Managed patch.
- Stop when more than one StorageClass is marked default, or the default class cannot provide a filesystem, unless the user names a class. Do not change which StorageClass is the cluster default.
- A `Pending` PVC is expected with `WaitForFirstConsumer` until the registry pod exists. The image-registry cluster operator can stay `Available` while the registry is `Removed`; judge the deployment and PVC.

## Required Source Checks

For deploy and undeploy, verify the internal image registry storage docs for the installed OpenShift version when network access is available. On 4.18 the operator creates a ReadWriteMany claim when `spec.storage.pvc.claim` is empty; confirm that behavior before using a blank claim on another version.

For OpenShift channel, patch, or one-hop upgrade-path questions, use `openshift-versions`. Release availability is not cluster upgrade readiness and is not registry storage readiness.

## Inputs To Collect

- `oc` context, node count, OpenShift version, and the current registry config: management state, rollout strategy, replica count, storage spec, and whether `defaultRoute` is set.
- StorageClasses, which class is default, reclaim policy, volume binding mode, and whether a filesystem class exists.
- Any existing `image-registry-storage` PVC, plus the `image-registry` deployment and pods in `openshift-image-registry`.

## Output Expectations

- Start with discovered facts, the decision from `scripts/select_registry_storage.py`, and the safety gates that still apply.
- Name the reference runbook used.
- Keep read-only discovery separate from the PVC create and the config patch.
- Pass the same explicit context to every `oc` command.
- After deploy, run the validation smoke. After undeploy, show that the registry pod and PVC are gone before any redeploy.
