"""Contract tests for LVMS runbook fixes validated on a live 4.22 SNO install.

Guards the regressions fixed after a real deployment:
- `oc wait --for=condition=Ready` hangs on LVMCluster (no such condition).
- A bare `channel: stable` Subscription never produces a CSV.
- The devices-file message must not be presented as proof a disk is unclaimed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = REPO_ROOT / "openshift-lvm-storage" / "references"

LVMCLUSTER_WAIT_FILES = (
    "install-and-preflight.md",
    "expand-shrink.md",
    "upgrade.md",
)


def _reference_text(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def test_lvmcluster_waits_use_status_state_not_ready_condition():
    for name in LVMCLUSTER_WAIT_FILES:
        text = _reference_text(name)
        wait_lines = [
            line
            for line in text.splitlines()
            if "wait" in line and "lvmcluster/" in line
        ]
        assert wait_lines, f"{name}: expected an LVMCluster wait command"
        for line in wait_lines:
            assert "--for=condition=Ready" not in line, (
                f"{name}: LVMCluster has no 'Ready' condition; "
                f"wait on .status.state instead: {line.strip()}"
            )
            assert "--for=jsonpath='{.status.state}'=Ready" in line or "--for=delete" in line, (
                f"{name}: unexpected LVMCluster wait form: {line.strip()}"
            )


def test_subscription_channel_is_discovered_not_hardcoded_stable():
    text = _reference_text("install-and-preflight.md")
    assert not re.search(r"channel:\s*stable\s*$", text, re.M), (
        "Subscription examples must not hardcode a bare 'stable' channel; "
        "the catalog serves only version-pinned channels"
    )
    assert "packagemanifest lvms-operator" in text, (
        "install runbook must discover the served channel from the packagemanifest"
    )
    assert "{.status.defaultChannel}" in text
    assert "{.status.catalogSource}" in text and "{.status.catalogSourceNamespace}" in text, (
        "channel discovery must also surface the catalog source for spec.source/sourceNamespace"
    )


def test_devices_file_message_is_not_treated_as_unclaimed_evidence():
    text = _reference_text("install-and-preflight.md")
    assert "device is not in devices file" in text, (
        "install runbook must explain the RHEL 9 devices-file message"
    )
    note = text[text.index("device is not in devices file") :]
    note = note[: note.find("\n\n")]
    assert "evidence the disk is unclaimed" not in note.replace(
        "nor evidence that the disk is unclaimed", ""
    ), "devices-file message must stay inconclusive, not proof of an unclaimed disk"
    assert "pvs --devices" in text, (
        "safety-gate evidence must read on-disk metadata via pvs --devices, "
        "which bypasses the devices-file allowlist"
    )


def test_install_validation_scopes_pending_pvc_to_wait_for_first_consumer():
    text = _reference_text("install-and-preflight.md")
    assert "WaitForFirstConsumer" in text
    assert "validation-hardening.md" in text, (
        "install validation must end with the functional smoke test runbook"
    )
    assert "Immediate" in text, (
        "Pending-PVC-is-expected guidance must be scoped to WaitForFirstConsumer only"
    )


def test_expand_wait_warns_about_stale_ready_status():
    text = _reference_text("expand-shrink.md")
    assert "stale status" in text, (
        "expansion runbook must warn that an already-Ready LVMCluster can pass "
        "the state wait before the controller observes the spec change"
    )
