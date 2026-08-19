"""Contract tests for the ODF validation runbook, from a live 4.20.16 SNO validation.

Guards three things the run surfaced:
- Core Validation reached the cluster only through `deploy/rook-ceph-tools`, so
  validating a cluster without the toolbox required patching OCSInitialization
  to create it. Validation must not have to mutate the cluster it validates.
- "Exactly one default StorageClass" was asserted unscoped, which reports a
  failure on a cluster that deliberately has none.
- The smoke section covered rbd and cephfs only, with no pointer to the
  ObjectBucketClaim flow that already exists in object-mcg-rgw.md.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = REPO_ROOT / "openshift-odf" / "references"
VALIDATION = REFERENCES / "validation-hardening.md"


def _validation_text() -> str:
    return VALIDATION.read_text(encoding="utf-8")


def _core_validation_section(text: str) -> str:
    start = text.index("## Core Validation")
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    return rest if nxt == -1 else rest[:nxt]


def test_core_validation_offers_a_read_only_route_to_ceph():
    """Validation must not require mutating the cluster under validation.

    The toolbox is a Deployment that has to be created via OCSInitialization
    when absent. The rook-operator pod answers the same read-only `ceph`
    queries and is already the pattern used by the .mgr drift check below and
    by validated-odf-sno.md.
    """
    section = _core_validation_section(_validation_text())
    assert "app=rook-ceph-operator" in section, (
        "Core Validation must document the read-only rook-operator route for "
        "clusters without the toolbox, instead of only offering to create it"
    )
    assert "/var/lib/rook/" in section, (
        "the operator route needs the ceph config path (-c) to work"
    )


def test_default_storageclass_assertions_are_scoped():
    """A cluster may legitimately have zero default StorageClasses.

    ODF does not claim a default on install, so "exactly one" is only correct
    when defaulting is expected. Stated flatly it turns a deliberate policy
    into a reported validation failure.
    """
    text = _validation_text()
    for i, line in enumerate(text.splitlines(), start=1):
        if "one default StorageClass" not in line:
            continue
        assert re.search(
            r"when defaulting is expected|if defaulting is expected|expected to default"
            r"|deliberately|intended|policy",
            line,
        ), (
            f"line {i}: scope the default-StorageClass assertion — a cluster "
            f"with no default is a valid policy, not a failure: {line.strip()}"
        )


def test_smoke_section_covers_object_storage():
    """Object storage is a first-class ODF service and needs exercising.

    The OBC flow already exists in object-mcg-rgw.md; the validation runbook
    just never sends the reader there, so a validation run silently skips it.
    """
    text = _validation_text()
    smoke_start = text.index("## Smoke Test")
    smoke = text[smoke_start:]
    nxt = smoke.find("\n## ", 1)
    smoke = smoke if nxt == -1 else smoke[:nxt]
    assert "object-mcg-rgw.md" in smoke, (
        "the smoke section must point at the ObjectBucketClaim flow when object "
        "storage is enabled, not stop at rbd and cephfs"
    )
    assert re.search(r"ObjectBucketClaim|OBC", smoke), (
        "name the object smoke artifact so the reader knows what to exercise"
    )
