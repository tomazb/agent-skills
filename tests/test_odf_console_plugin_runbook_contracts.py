"""Contract tests for the ODF console-plugin runbook.

CLI OLM install creates ConsolePlugin CRs and odf-console pods but does not
add them to console.operator.openshift.io/cluster spec.plugins. Official ODF
troubleshooting docs then show a JSON Patch that *replaces* spec.plugins with
["odf-console"], which disables every other enabled plugin (monitoring,
networking, ...). The runbook exists so agents discover, append, and verify
instead of following that replace-all example.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "openshift-odf" / "SKILL.md"
RUNBOOK = REPO_ROOT / "openshift-odf" / "references" / "console-plugin.md"


def _runbook() -> str:
    assert RUNBOOK.exists(), (
        "missing references/console-plugin.md — console plugin enablement "
        "must be a dedicated runbook, not a validation footnote"
    )
    return RUNBOOK.read_text(encoding="utf-8")


def test_skill_routes_console_plugin_work_to_the_runbook():
    skill = SKILL.read_text(encoding="utf-8")
    routing = skill[skill.index("## Routing") : skill.index("## Core Safety Rules")]
    assert "references/console-plugin.md" in routing
    assert re.search(r"console plugin|Data Foundation", routing, re.IGNORECASE)


def test_runbook_discovers_crs_and_enabled_list_separately():
    text = _runbook()
    assert "oc get consoleplugin" in text
    assert "console.operator.openshift.io" in text
    assert "{.spec.plugins}" in text
    assert "odf-console" in text
    assert "odf-client-console" in text


def test_runbook_forbids_replacing_the_plugins_array_with_only_odf_console():
    """The Red Hat 4.20 troubleshooting patch is the failure this runbook exists to stop."""
    import sys

    tools = REPO_ROOT / "openshift-odf" / "tools"
    sys.path.insert(0, str(tools))
    from validate_skill_package import (  # noqa: E402
        _DESTRUCTIVE_PLUGINS_REPLACE,
        plugins_replace_marked_forbidden,
    )

    text = _runbook()
    assert "/spec/plugins/-" in text, (
        "append with JSON Pointer /spec/plugins/- so existing plugins stay enabled"
    )
    matches = list(_DESTRUCTIVE_PLUGINS_REPLACE.finditer(text))
    assert matches, "runbook must show the forbidden replace-all example"
    for match in matches:
        assert plugins_replace_marked_forbidden(text, match), (
            "a patch that sets spec.plugins to only odf-console must be marked "
            f"forbidden on the command line or the preceding line: {match.group(0)[:160]!r}"
        )


def test_runbook_keeps_the_console_resource_cluster_scoped():
    text = _runbook()
    # -n openshift-storage on a cluster-scoped Console is ignored and misleads.
    for line in text.splitlines():
        if "patch" in line and "console.operator" in line and "-n openshift-storage" in line:
            assert re.search(r"\b(not|never|do not|don't|misleading)\b", line, re.IGNORECASE), (
                "do not patch the cluster-scoped Console as if it lived in "
                f"openshift-storage: {line.strip()}"
            )


def test_runbook_is_idempotent_when_plugins_are_already_enabled():
    text = _runbook()
    assert re.search(r"already|skip|nothing to (patch|add)", text, re.IGNORECASE)
    assert "python3 scripts/render_console_plugin_patch.py" in text


def test_runbook_adds_odf_client_console_only_when_cr_exists():
    text = _runbook()
    assert "oc get consoleplugin odf-client-console" in text
    assert 'ADD+=(odf-client-console)' in text or "ADD+=(odf-client-console)" in text


def test_runbook_validates_data_foundation_nav_and_console_rollout():
    text = _runbook()
    assert "Storage" in text and "Data Foundation" in text
    assert "Refresh web console" in text or "refresh" in text.lower()
    assert "odf-console" in text
