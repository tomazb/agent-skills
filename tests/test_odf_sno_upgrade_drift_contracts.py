"""Contract tests for ODF SNO z-stream upgrade drift, observed on 4.20.16 -> 4.20.17.

An automatic z-stream upgrade on a live SNO cluster produced three effects the
runbooks did not cover:

- The CSI ctrlplugin rolling update deadlocked. At `replicas: 1` a
  RollingUpdate with `maxUnavailable: 25%` rounds down to 0, so the old pod is
  never removed, while `maxSurge` allows a new pod that hard pod anti-affinity
  forbids scheduling on the single node. The new pod stayed Pending for 13h.
- `Not enough nodes found: Expected 3, found 1` failed the StorageCluster
  reconcile *despite* `flexibleScaling: true`, leaving `phase: Error` while the
  cluster served traffic normally.
- The upgrade restarted the mgr, so `.mgr` returned to `size 3` (undersized
  PGs) and the POOL_NO_REDUNDANCY health mute lapsed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = REPO_ROOT / "openshift-odf" / "references"


def _text(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def test_ctrlplugin_rollout_deadlock_is_documented():
    """The single-replica fix does not survive the next image change.

    The runbooks already say to set the Driver CRs to `replicas: 1`. That is
    necessary but not sufficient: every later CSI image update deadlocks the
    rollout on a single node, so the fix needs its own follow-up.
    """
    text = _text("validated-odf-sno.md") + _text("upgrade.md")
    assert re.search(r"maxUnavailable", text), (
        "explain the rollout arithmetic: maxUnavailable 25% of 1 replica "
        "rounds down to 0, so the outgoing pod is never removed"
    )
    assert re.search(r"anti-affinity", text, re.I), (
        "name pod anti-affinity as the reason the surge pod cannot schedule"
    )
    assert re.search(r"Pending", text), (
        "state the observable symptom: the new ctrlplugin pod stays Pending"
    )


def test_upgrade_runbook_covers_sno_post_upgrade_drift():
    """A z-stream upgrade restarts the mgr and clears health mutes."""
    text = _text("upgrade.md")
    assert ".mgr" in text, (
        "the upgrade runbook must tell SNO operators to re-check the .mgr pool "
        "size, since the upgrade restarts the mgr"
    )
    assert re.search(r"POOL_NO_REDUNDANCY", text), (
        "the health mute does not survive the upgrade and must be re-applied"
    )


def test_flexible_scaling_claim_is_qualified():
    """flexibleScaling: true did not prevent the node-count reconcile error.

    The runbook stated it does. On 4.20.17 the StorageCluster carries
    phase: Error with that message while Available/Degraded stay healthy, so a
    reader gating on phase alone concludes the cluster is broken.
    """
    text = _text("validated-odf-sno.md")
    idx = text.find("Not enough nodes found")
    assert idx != -1, "the node-count error message must appear in the runbook"
    context = text[max(0, idx - 600) : idx + 900]
    assert re.search(r"4\.20\.17|z-stream|still|despite|even with", context), (
        "qualify the flexibleScaling claim: on 4.20.17 the reconcile still "
        "fails with this message even when flexibleScaling is set"
    )
    assert re.search(r"Available|Degraded|phase", context), (
        "tell the reader which conditions to trust when phase reads Error"
    )
