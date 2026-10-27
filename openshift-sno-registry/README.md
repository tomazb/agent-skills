# OpenShift SNO Internal Registry

Current version: **0.1.0**

Lifecycle skill for the OpenShift/OKD internal image registry on Single Node OpenShift. It selects a filesystem StorageClass, pre-creates a 100Gi ReadWriteOnce PVC, and runs one `Recreate` replica. When no filesystem class exists, it hands off to `openshift-lvm-storage`.

The skill routes work through focused reference runbooks:

- Deploy, including the LVM Storage fallback
- Push and pull validation
- Undeploy and the PVC deletion rules for a later redeploy

## Validation

The package self-check ships with the skill:

```bash
bash tools/validate_skill_package.sh
```

The test suite runs from the repository checkout:

```bash
pytest -q
```
