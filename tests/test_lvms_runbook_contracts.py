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
    warning = re.compile(
        r"existing default|already has a default|already the cluster default"
        r"|default already exists"
    )
    for name in LVMCLUSTER_TEMPLATE_FILES:
        lines = _reference_text(name).splitlines()
        template_lines = [i for i, l in enumerate(lines) if l.strip() == "default: true"]
        if not template_lines:
            continue
        warned_at = [i for i, l in enumerate(lines) if warning.search(l)]
        assert warned_at, (
            f"{name}: sets 'default: true' in an LVMCluster template without "
            "telling the reader to check for an existing default StorageClass first"
        )
        # The warning has to come before the template a reader would copy,
        # otherwise they have already pasted `default: true` by the time they
        # reach it. A bare token match anywhere in the file is not enough:
        # `is-default-class` also appears in unrelated annotation examples.
        first_template = min(template_lines)
        assert min(warned_at) < first_template, (
            f"{name}: the existing-default warning appears after the first "
            f"'default: true' template (line {first_template + 1})"
        )


def test_default_sc_discovery_covers_the_legacy_beta_annotation():
    """Upgraded clusters can carry only the beta annotation.

    A discovery command that reads the stable annotation alone reports "no
    default" on such a cluster, which is exactly the case this guidance exists
    to catch. The repo's own post_uninstall_audit.sh already treats either as a
    default.
    """
    text = _reference_text("install-and-preflight.md")
    assert "storageclass.beta.kubernetes.io/is-default-class" in text, (
        "default-StorageClass discovery must also inspect the legacy beta "
        "annotation, or an upgraded cluster's existing default is missed"
    )


def test_multiple_default_storageclass_behaviour_is_stated_correctly():
    """Multiple defaults resolve deterministically, not arbitrarily.

    The DefaultStorageClass admission plugin picks the most recently created
    default. Describing it as arbitrary or API-server-order dependent sends an
    operator looking for a race that does not exist, when the real explanation
    is that the newly created class silently won.
    """
    for name in ("install-and-preflight.md", "expand-shrink.md"):
        text = _reference_text(name)
        if "two defaults" not in text and "multiple default" not in text.lower():
            continue
        assert re.search(r"most recently created|newest", text), (
            f"{name}: must state that the most recently created default wins"
        )
        for wrong in ("happens to return first", "resolves unpredictably", "does not pick a winner"):
            assert wrong not in text, (
                f"{name}: multiple-default behaviour is deterministic, not "
                f"arbitrary; remove {wrong!r}"
            )


def test_non_default_deviceclass_consequence_is_documented():
    """`default: false` is the safe choice, but it has a failure mode.

    With no default StorageClass on the cluster, a PVC that omits
    storageClassName never binds. The operator warns about this at apply time;
    the runbook must too, or the reader picks the safe option and then cannot
    explain a Pending PVC.
    """
    text = _reference_text("install-and-preflight.md")
    assert "no default deviceClass was specified" in text, (
        "quote the operator's apply-time warning so the reader recognises it"
    )
    assert "storageClassName" in text, (
        "state that PVCs must name the StorageClass explicitly"
    )
    assert "Pending" in text, (
        "state the consequence: with no cluster default, a PVC omitting "
        "storageClassName stays Pending"
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
    assert re.search(r"only under `?/dev/disk/by-path|only.{0,30}by-path", text), (
        "discovery must state the fallback explicitly: when the disk has no "
        "by-id entry, by-path is the selector to use"
    )
    # The evidence snippet must not force a by-id path on readers whose disk
    # only has a by-path identity.
    for line in text.splitlines():
        if line.startswith("DISK="):
            assert "by-id" not in line or "by-path" in line, (
                "the DISK placeholder hardcodes a by-id path even though the "
                f"section supports by-path-only disks: {line.strip()}"
            )
