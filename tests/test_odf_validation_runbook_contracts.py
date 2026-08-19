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
    # Ordering matters: the toolbox is opt-in and absent by default, so a
    # reader working top-to-bottom must not hit four failing commands before
    # being told an alternative exists.
    # Only executable toolbox commands count: prose that warns the toolbox may
    # be absent is exactly what we want to appear early.
    first_toolbox_cmd = section.find("exec deploy/rook-ceph-tools")
    first_operator_route = section.find("app=rook-ceph-operator")
    assert first_toolbox_cmd == -1 or first_operator_route < first_toolbox_cmd, (
        "the read-only route must appear before any toolbox-dependent `ceph` "
        "command, since the toolbox is not deployed by default and a reader "
        "working top-to-bottom would otherwise hit failures first"
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


def _object_section(text: str) -> str:
    start = text.index("### Object storage")
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    return rest if nxt == -1 else rest[:nxt]


def test_object_smoke_uses_a_dedicated_disposable_namespace():
    """Cleanup deletes a namespace, so the runbook must name a throwaway one.

    A `<obc-namespace>` placeholder invites running the claim in an existing
    application namespace, and the cleanup step then deletes that namespace
    along with everything unrelated in it.
    """
    section = _object_section(_validation_text())
    assert "odf-object-smoke" in section, (
        "name a dedicated smoke namespace, matching the odf-rbd-smoke / "
        "odf-cephfs-smoke convention used above"
    )
    assert "<obc-namespace>" not in section, (
        "a placeholder namespace plus a namespace delete is a footgun: the "
        "reader can point it at a live application namespace"
    )
    delete_lines = [
        line for line in section.splitlines() if "delete namespace" in line
    ]
    assert delete_lines, "the object smoke flow must clean up after itself"
    for line in delete_lines:
        assert "odf-object-smoke" in line, (
            f"cleanup must delete only the dedicated smoke namespace: {line.strip()}"
        )


def test_object_smoke_exercises_the_s3_data_path():
    """Provisioning metadata is not evidence the object path works.

    An OBC can reach Bound with its ConfigMap and Secret created while the
    endpoint or credentials are unusable. Without a PUT/GET the validation
    reports a healthy object service on a broken data plane.
    """
    section = _object_section(_validation_text())
    assert re.search(r"put_object|PUT", section), (
        "object validation must write an object, not just check the OBC status"
    )
    assert re.search(r"get_object|GET", section), (
        "object validation must read the object back"
    )
    assert re.search(r"delete_object|DELETE", section), (
        "object validation must remove the probe object it wrote"
    )
    for field in (
        "BUCKET_HOST",
        "BUCKET_PORT",
        "BUCKET_NAME",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        assert field in section, (
            f"wire {field} into the data-path check; the snippet consumes every "
            "generated field and dropping one breaks it silently"
        )
    # A bare https:// prefix breaks when BUCKET_HOST already carries a scheme,
    # which the MCG StorageClass can produce.
    assert '"https://%s:%s"' not in section, (
        "normalize BUCKET_HOST instead of unconditionally prefixing https://, "
        "or a host that already has a scheme yields https://https://..."
    )


def test_object_cleanup_check_can_actually_fail():
    """`... | grep X || echo ok` reports success whether or not X is found.

    grep exits 0 when it finds a leftover, so the leftover path and the clean
    path both look like success, and a failing `oc get` is masked by the pipe.
    A verification step that cannot fail is not a verification step.
    """
    section = _object_section(_validation_text())
    for line in section.splitlines():
        if "objectbucket" in line and "grep" in line:
            assert "||" not in line or "true" in line, (
                "this cleanup check succeeds even when leftovers are found: "
                + line.strip()
            )
    assert re.search(r"exit 1", section), (
        "the cleanup verification must exit non-zero when ObjectBuckets survive "
        "the claim or when the query itself fails"
    )
