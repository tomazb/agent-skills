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


LVMCLUSTER_TEMPLATE_FILES = (
    "install-and-preflight.md",
    "expand-shrink.md",
    "validated-lvms-ocp-sno.md",
)


def test_default_deviceclass_templates_warn_about_an_existing_default_sc():
    """`default: true` mints a default StorageClass.

    The skill's own safety rule is "keep exactly one default StorageClass", and
    validation-hardening asserts it — so a template that sets `default: true`
    without telling the reader to check for an existing default produces a
    second one on any cluster that already has ODF or another default.
    """
    for name in LVMCLUSTER_TEMPLATE_FILES:
        text = _reference_text(name)
        if "default: true" not in text:
            continue
        assert re.search(r"is-default-class|existing default|already has a default", text), (
            f"{name}: sets 'default: true' in an LVMCluster template without "
            "telling the reader to check for an existing default StorageClass first"
        )


def test_non_default_deviceclass_consequence_is_documented():
    """`default: false` is the safe choice, but it has a failure mode.

    With no default StorageClass on the cluster, a PVC that omits
    storageClassName never binds. The operator warns about this at apply time;
    the runbook must too, or the reader picks the safe option and then cannot
    explain a Pending PVC.
    """
    text = _reference_text("install-and-preflight.md")
    assert "storageClassName" in text and re.search(
        r"default:\s*false|no default StorageClass", text
    ), (
        "install runbook must document that with default: false (or no cluster "
        "default) PVCs must name the StorageClass explicitly or stay Pending"
    )


def test_disk_discovery_handles_missing_by_id_entry():
    """Not every disk has a /dev/disk/by-id/ entry.

    virtio disks without a serial expose only /dev/disk/by-path/, so a
    discovery step that hardcodes a by-id path leaves the reader with no
    documented way forward.
    """
    text = _reference_text("install-and-preflight.md")
    assert "by-path" in text, "discovery must mention the by-path fallback"
    assert re.search(r"virtio|no by-id|without a serial|lacks? a by-id", text, re.I), (
        "discovery must state that some disks (virtio without a serial) have no "
        "/dev/disk/by-id/ entry and that by-path is the correct selector there"
    )
    assert "ls -l /dev/disk/by-id" in text or "ls /dev/disk/by-id" in text, (
        "discovery must show how to check whether a by-id entry exists at all"
    )
