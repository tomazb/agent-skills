# OpenShift SNO Internal Registry

Current version: **0.1.1**

Lifecycle skill for the OpenShift/OKD internal image registry on Single Node OpenShift. It selects a filesystem StorageClass, pre-creates a 100Gi ReadWriteOnce PVC, and runs one `Recreate` replica. When no filesystem class exists, it hands off to `openshift-lvm-storage`.

The skill routes work through focused reference runbooks:

- Deploy, including the LVM Storage fallback
- Push and pull validation
- Undeploy and the PVC deletion rules for a later redeploy

## Validation

The package self-check ships with the skill. It uses PyYAML from the repository `requirements-dev.txt`.

```bash
bash tools/validate_skill_package.sh
```

Run this skill's tests from the repository root:

```bash
python3 -m pytest -q openshift-sno-registry/tests
```

Run the full repository suite in isolated processes. A single `pytest -q` from the repository root collects every skill into one process, and those packages reuse module names.

```bash
python3 scripts/run_test_suite.py
```
