from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import validate_skill_package as vsp


@pytest.fixture
def validator():
    return vsp


REFERENCE_TEXT = """\
# Sample Reference

Require explicit confirmation before mutating the named oc context.

Do not patch IngressController or APIServer until Certificate Ready=True from
the production issuer. Never use staging certificates as platform certs.

Keep router-certs-default for rollback. After API swap, fix
certificate-authority-data in kubeconfig.

Use ClusterIssuer and Certificate for letsencrypt HTTP-01 and DNS-01.
Install openshift-cert-manager-operator via OLM Subscription and CSV.

Patch defaultCertificate and namedCertificates only after Ready.

HTTP-01 needs public port 80 on A and AAAA. Run
python3 scripts/check_http01_reachability.py before Challenges.

DNS-01 uses dns01 cloudflare for wildcards when unsupported path is accepted.
Prefer route53 azureDNS cloudDNS when Red Hat support is required.

On SNO, a bad API patch can lock out oc.

Record PRIOR_DEFAULT_CERT and PRIOR_SERVING_CERTS before patching.
Restore the recorded prior default certificate and exact prior servingCerts.

Use python3 scripts/discover_tls.py --context "<oc-context>" --execute for discovery.
"""

SKILL_TEMPLATE = """\
---
name: openshift-cert-manager
description: Use when installing or troubleshooting cert-manager on OpenShift.
---

# OpenShift cert-manager Lifecycle

Use this skill as a lifecycle router.

## Routing

Routing guidance.

## Core Safety Rules

Safety guidance.

## Required Source Checks

Source guidance. For OpenShift channel or upgrade-path questions, use
`openshift-versions`. Release availability is not cluster upgrade readiness.

## Inputs To Collect

Input guidance.

## Output Expectations

Output guidance.
"""

DEFAULT_SKILL_DESCRIPTION = (
    "Use when installing or troubleshooting cert-manager on OpenShift."
)


def _make_skill_text(
    name: str = vsp.EXPECTED_NAME,
    description: str | None = DEFAULT_SKILL_DESCRIPTION,
    missing_sections: list[str] | None = None,
) -> str:
    text = SKILL_TEMPLATE
    if name != vsp.EXPECTED_NAME:
        text = text.replace("name: openshift-cert-manager", f"name: {name}")
    if description is None:
        text = text.replace(
            "description: Use when installing or troubleshooting cert-manager on OpenShift.\n",
            "",
        )
    else:
        text = text.replace(
            "description: Use when installing or troubleshooting cert-manager on OpenShift.",
            f"description: {description}",
        )
    if missing_sections:
        for section in missing_sections:
            text = text.replace(f"## {section.lstrip('# ').strip()}", "")
    return text


@pytest.fixture
def make_skill_text():
    return _make_skill_text


@pytest.fixture
def reference_text():
    return lambda: REFERENCE_TEXT


@pytest.fixture
def package_factory(tmp_path, make_skill_text, reference_text):
    def _factory(
        skill_text: str | None = None,
        reference_content: str | None = None,
    ) -> Path:
        root = tmp_path / "openshift-cert-manager"
        root.mkdir()

        refs = root / "references"
        refs.mkdir()

        (root / "SKILL.md").write_text(
            skill_text or make_skill_text(), encoding="utf-8"
        )
        (root / "README.md").write_text(
            "# OpenShift cert-manager\n\nCurrent version: **1.0.0**\n",
            encoding="utf-8",
        )
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 1.0.0\n\n- Initial.\n", encoding="utf-8"
        )
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "openshift-cert-manager",
                    "version": "1.0.0",
                    "description": "cert-manager lifecycle",
                }
            ),
            encoding="utf-8",
        )
        (root / "scripts").mkdir()
        (root / "scripts" / "discover_tls.py").write_text("", encoding="utf-8")
        (root / "scripts" / "check_http01_reachability.py").write_text(
            "", encoding="utf-8"
        )
        (root / "tools").mkdir()
        (root / "tools" / "validate_skill_package.py").write_text("", encoding="utf-8")
        (root / "tools" / "validate_skill_package.sh").write_text("", encoding="utf-8")

        ref_content = reference_content or REFERENCE_TEXT
        for ref in vsp.EXPECTED_REFERENCES:
            (root / ref).write_text(ref_content + "\n", encoding="utf-8")

        return root

    return _factory
