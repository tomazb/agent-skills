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

These assert the remediation content and its ordering, not merely that the
keywords appear somewhere in the file.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = REPO_ROOT / "openshift-odf" / "references"


def _text(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body of a section, up to the next heading of the same or higher level.

    Fence-aware: a shell comment like `# 1. ...` inside a ```bash block is not
    a heading, and treating it as one silently truncates the section under
    test to almost nothing.
    """
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == heading.strip())
    level = len(heading) - len(heading.lstrip("#"))
    body: list[str] = []
    in_fence = False
    for line in lines[start + 1 :]:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            if hashes <= level and line[hashes : hashes + 1] == " ":
                break
        body.append(line)
    return "\n".join(body)


def test_ctrlplugin_rollout_deadlock_is_documented():
    """The single-replica fix does not survive the next image change.

    The runbooks already say to set the Driver CRs to `replicas: 1`. That is
    necessary but not sufficient: every later CSI image update deadlocks the
    rollout on a single node, so the fix needs its own follow-up.
    """
    section = _section(
        _text("validated-odf-sno.md"),
        "### The single-replica fix does not survive the next image change",
    )
    assert "maxUnavailable" in section and "maxSurge" in section, (
        "explain the rollout arithmetic on both sides: maxUnavailable 25% of 1 "
        "replica rounds down to 0, maxSurge rounds up to 1"
    )
    assert re.search(r"anti-affinity", section, re.I), (
        "name pod anti-affinity as the reason the surge pod cannot schedule"
    )
    assert "Pending" in section, "state the observable symptom"
    assert re.search(r"get rs", section), (
        "give the two-live-ReplicaSets check, since the Deployment still reads 1/1"
    )
    assert re.search(r"delete pod .*old|old.*ctrlplugin-pod", section), (
        "the remedy is deleting the OLD pod so the new one can take the node"
    )
    assert re.search(r"one driver at a time|repeat for cephfs", section), (
        "recover one driver at a time to bound the provisioning gap"
    )


def test_upgrade_runbook_covers_sno_post_upgrade_drift():
    """A z-stream upgrade restarts the mgr and clears health mutes."""
    section = _section(
        _text("upgrade.md"), "## Post-Upgrade Drift On Single-Replica SNO"
    )
    assert "osd pool set .mgr size 1" in section, (
        "give the .mgr size remediation, not just the symptom"
    )
    assert "osd pool set .mgr min_size 1" in section, "min_size must be reduced too"
    assert "POOL_NO_REDUNDANCY" in section, (
        "the health mute does not survive the upgrade and must be re-applied"
    )

    # Ordering: reduce the pool, prove the PGs recovered, then re-mute. The
    # PG check has to be explicit — POOL_NO_REDUNDANCY is a different health
    # check from PG_DEGRADED, so the mute never hides undersized PGs and
    # ordering alone guarantees nothing.
    fix_at = section.index("osd pool set .mgr size 1")
    mute_at = section.index("health mute POOL_NO_REDUNDANCY")
    pg_check = re.search(r"pg stat|active\+clean|undersized", section[fix_at:mute_at])
    assert pg_check, (
        "between reducing .mgr and re-muting, require an explicit check that no "
        "PGs remain undersized or degraded"
    )
    assert fix_at < mute_at, "reduce the pool before re-muting"


def test_flexible_scaling_claim_is_qualified():
    """flexibleScaling: true did not prevent the node-count reconcile error.

    The runbook stated it does. On 4.20.17 the StorageCluster carries
    phase: Error with that message while Available/Degraded stay healthy, so a
    reader gating on phase alone concludes the cluster is broken.
    """
    text = _text("validated-odf-sno.md")
    anchor = "It does not silence that message on every z-stream."
    assert anchor in text, (
        "qualify the flexibleScaling claim where it is made, not elsewhere"
    )
    block = text[text.index(anchor) :][:1500]
    assert "4.20.17" in block, "name the release the behaviour was observed on"
    assert "Not enough nodes found: Expected 3, found 1" in block, (
        "quote the exact reconcile error so it is greppable"
    )
    assert re.search(r"phase.{0,3}:? Error|\.status\.phase", block), (
        "state that phase reads Error"
    )
    for condition in ("Available=True", "Degraded=False"):
        assert condition in block, (
            f"name {condition} so the reader knows which conditions to trust "
            "instead of gating on phase"
        )
