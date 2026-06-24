# OpenShift LVM Storage Lifecycle

Current version: **1.0.1**

Lifecycle skill for planning, installing, configuring, validating, upgrading, expanding, shrinking, backing up, restoring, maintaining, and uninstalling LVM Storage (LVMS) on OpenShift/OKD.

The skill routes work through focused reference runbooks:

- OpenShift/OKD install and preflight
- Volume group provisioning and thin pool configuration
- Filesystem volumes (ext4/xfs) via TopoLVM CSI
- Raw block volumes via TopoLVM CSI
- Volume group expansion and shrink
- upgrades
- backup, restore, and DR (local storage considerations)
- maintenance and uninstall
- validation, hardening, and troubleshooting

The validated OpenShift SNO / LVMS journal is retained in `references/validated-lvms-ocp-sno.md` as observed evidence, not a universal default.

The package also ships helpers for YAML-aware manifest patching, restricted smoke manifest rendering (filesystem and block modes), and read-only post-uninstall audits.

## Validation

The package self-check ships with the skill and runs anywhere it is extracted:

```bash
bash tools/validate_skill_package.sh
```

The full test suite runs from the repository checkout (the `tests/` directory is a development dependency and is not included in the packaged `.skill` archive):

```bash
pytest -q
```
