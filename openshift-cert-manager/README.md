# OpenShift cert-manager Lifecycle

Current version: **1.0.0**

Lifecycle skill for planning, installing, configuring, validating, and uninstalling the Red Hat cert-manager Operator on OpenShift/OKD, including Let's Encrypt ACME and optional replacement of the default `*.apps` ingress certificate and public API serving certificate.

The skill routes work through focused reference runbooks:

- Operator install and preflight
- HTTP-01 ACME proof (staging then production)
- DNS-01 issuers (Red Hat-supported Route 53 / Azure / GCP; Cloudflare as unsupported path)
- Platform ingress and API certificate replacement
- validation and troubleshooting
- maintenance and uninstall

The package ships read-only helpers for TLS discovery and HTTP-01 port-80 dual-stack reachability. Helpers never apply cluster changes.

## Validation

The package self-check ships with the skill and runs anywhere it is extracted:

```bash
bash tools/validate_skill_package.sh
```

The full test suite runs from the repository checkout (the `tests/` directory is a development dependency and is not included in the packaged `.skill` archive):

```bash
pytest -q
```
