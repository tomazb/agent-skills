# OpenShift Longhorn

Current version: **1.1.0**

Lifecycle skill for planning, installing, migrating, upgrading, validating, hardening, backing up, restoring, maintaining, and uninstalling Longhorn on OpenShift/OKD.

The skill routes work through focused reference runbooks:

- OpenShift/OKD install and preflight
- V1 filesystem data disks
- V2 block data engine and SPDK prerequisites
- V1/V2 migration
- upgrades
- backup, restore, and DR
- maintenance and uninstall
- validation, hardening, and troubleshooting

The validated OpenShift 4.22 SNO / Longhorn v1.12.0 V2 journal is retained in `references/validated-v2-ocp422-sno.md` as observed evidence, not a universal default.

## Validation

The package self-check ships with the skill and runs anywhere it is extracted:

```bash
bash tools/validate_skill_package.sh
```

The full test suite runs from the repository checkout (the `tests/` directory is a
development dependency and is not included in the packaged `.skill` archive):

```bash
pytest -q
```
