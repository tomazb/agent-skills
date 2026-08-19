"""Contract tests for ODF uninstall runbook fixes validated on a live 4.22.1 SNO undeploy.

Guards the regressions found during a real `htz2` uninstall:
- `delete subscription --all` / `delete namespace openshift-storage` destroys LVMS and
  LSO, which install into `openshift-storage` by default.
- The CSV label selector `operators.coreos.com/odf-operator.openshift-storage` matches
  only 1 of 12 installed CSVs; CSVs must be resolved via `.status.installedCSV`.
- The ODF 4.22 SNO `reconcileStrategy: ignore` workaround blocks graceful uninstall:
  ocs-operator skips ignored pools and rook refuses to delete the CephCluster while
  CephBlockPool dependents remain.
- LSO objects backing ODF can live in `openshift-storage`, not `openshift-local-storage`.
- Keeping the namespace leaves ODF residue the operator teardown never garbage-collects
  (Driver CRs, console Service whose cert secret service-ca keeps recreating, a
  configmap pinned by an orphaned finalizer, SCCs, a mutating webhook, consoleplugins).
- ODF 4.22 adds the `postgresql.cnpg.noobaa.io` CRD group (NooBaa embedded CNPG).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = REPO_ROOT / "openshift-odf" / "references"


def _uninstall_text() -> str:
    return (REFERENCES / "maintenance-uninstall.md").read_text(encoding="utf-8")


def _sno_text() -> str:
    return (REFERENCES / "validated-odf-sno.md").read_text(encoding="utf-8")


def test_no_blanket_subscription_or_namespace_deletion():
    text = _uninstall_text()
    assert "delete subscription --all" not in text, (
        "LVMS and LSO install into openshift-storage by default; "
        "'delete subscription --all' destroys them. Delete ODF subscriptions by name."
    )
    assert re.search(r"lvms", text, re.I), (
        "uninstall runbook must warn that LVMS shares openshift-storage by default"
    )


def _fenced_blocks(text: str) -> list[str]:
    # Match any language tag (or none). Restricting this to bash/shell/sh
    # mispairs the fences: a ```text block's closing fence then gets read as the
    # closer for a later block and the extraction silently returns nothing.
    return re.findall(r"```[A-Za-z0-9_+-]*\n(.*?)```", text, flags=re.DOTALL)


def test_namespace_deletion_is_gated_and_fails_closed():
    """A failed subscription lookup must keep the namespace, not delete it.

    `[ -z "$(oc get subscription 2>/dev/null)" ]` cannot tell "no subscriptions"
    from "the lookup failed" (RBAC, API outage, CRD already removed) — both give
    an empty string, and the fallback is deleting a namespace that may still host
    LVMS and LSO.
    """
    text = _uninstall_text()
    blocks = [b for b in _fenced_blocks(text) if "delete namespace openshift-storage" in b]
    assert blocks, "expected a fenced block containing the namespace deletion"

    for block in blocks:
        # Only the executable lines are under test: the block deliberately names the
        # broken `2>/dev/null` form in a comment to explain why it is wrong.
        runnable = "\n".join(
            line for line in block.splitlines() if not line.lstrip().startswith("#")
        )
        assert "subscription" in runnable, (
            "namespace deletion must be gated on a subscription inventory: " + block
        )
        assert "2>/dev/null" not in runnable, (
            "discarding stderr on the gating lookup makes a failed query look like "
            "an empty one, which then deletes a shared namespace: " + block
        )
        assert re.search(r"if\s+\w+=\$\(oc[^)]*get subscription", runnable), (
            "gate on the exit status of the subscription lookup, not just on its "
            "output being empty: " + block
        )
        assert re.search(r"failed", runnable, re.I), (
            "the gate needs an explicit failure branch that keeps the namespace: "
            + block
        )


def test_csvs_resolved_from_installed_csv_not_label_selector():
    text = _uninstall_text()
    assert "operators.coreos.com/odf-operator.openshift-storage" not in text, (
        "the odf-operator CSV label selector matches 1 of 12 ODF CSVs; "
        "resolve CSVs per subscription via .status.installedCSV"
    )
    assert ".status.installedCSV" in text


def test_reconcile_strategy_ignore_uninstall_blocker_documented():
    text = _uninstall_text()
    assert "reconcileStrategy" in text and "ignore" in text, (
        "runbook must document that reconcileStrategy: ignore (4.22 SNO workaround) "
        "blocks graceful uninstall"
    )
    assert "will not be deleted until all dependents are removed" in text, (
        "runbook must quote the rook cluster-controller dependent-blocked error"
    )
    assert "builtin-mgr" in text, (
        "runbook must name the builtin-mgr pool that survives an ignored reconcile"
    )
    assert "validated-odf-sno.md" in text


def test_lso_objects_discovered_in_both_namespaces():
    text = _uninstall_text()
    assert "storage.openshift.com/owner-namespace" in text, (
        "LSO objects backing ODF can live in openshift-storage; discover the owning "
        "namespace from the local PV labels instead of assuming openshift-local-storage"
    )


def test_namespace_kept_residue_sweep_documented():
    text = _uninstall_text()
    for marker in (
        "drivers.csi.ceph.io",
        "ocs-client-operator-console",
        "ocs-client-operator.ocs.openshift.io/storageused",
        "csv.odf.openshift.io",
        "consoleplugin",
        "rook-ceph-pdbstatemap",
    ):
        assert marker in text, (
            f"namespace-kept residue sweep must cover {marker!r}; the operator "
            "teardown does not garbage-collect it when the namespace survives"
        )


def test_crd_sweep_deletes_instances_before_crds():
    """A CRD whose instances still hold finalizers sticks in Terminating.

    The runbook states this ordering requirement, so the commands must actually
    implement it rather than jumping straight to `oc delete crd`.
    """
    text = _uninstall_text()
    blocks = [b for b in _fenced_blocks(text) if "oc delete $crds" in b or "delete crd" in b]
    assert blocks, "expected a fenced block performing the CRD sweep"
    sweep = blocks[-1]
    assert "api-resources" in sweep, (
        "the sweep must enumerate the group's kinds so their CR instances can be "
        "deleted before the CRDs: " + sweep
    )
    instance_delete = sweep.find("--all")
    crd_delete = sweep.find("$crds")
    assert instance_delete != -1, "no CR-instance deletion found in the sweep"
    assert instance_delete < crd_delete, (
        "CR instances must be deleted before the CRDs they belong to: " + sweep
    )

    runnable = "\n".join(
        line for line in sweep.splitlines() if not line.lstrip().startswith("#")
    )
    assert "2>/dev/null" not in runnable, (
        "suppressing stderr on kind discovery turns a failed lookup into an empty "
        "kind list, so instance deletion is skipped and the CRDs are removed with "
        "instances still live: " + sweep
    )
    assert runnable.count("continue") >= 2, (
        "discovery and instance-deletion failures must skip the group's CRD "
        "deletion rather than falling through to it: " + sweep
    )


def test_crd_sweep_covers_cnpg_group():
    text = _uninstall_text()
    assert "postgresql.cnpg.noobaa.io" in text, (
        "ODF 4.22 NooBaa ships embedded CloudNativePG CRDs under "
        "postgresql.cnpg.noobaa.io; the CRD sweep must include the group"
    )


def test_validated_sno_notes_uninstall_implication():
    text = _sno_text()
    assert re.search(r"uninstall", text, re.I), (
        "validated-odf-sno.md must warn that the reconcileStrategy: ignore workaround "
        "blocks graceful uninstall until the ignored pool CRs are deleted directly"
    )
    assert "CephBlockPool" in text
