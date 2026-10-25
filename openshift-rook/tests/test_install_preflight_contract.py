"""Protect OpenShift SCC and full CephX audit runbook safety gates."""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "references" / "install-and-preflight.md"
HARDENING = ROOT / "references" / "validation-hardening.md"


def test_installer_keeps_full_existing_cluster_key_audit():
    """Reject admin-key-only authentication guidance in the install runbook."""
    install = INSTALL.read_text(encoding="utf-8")
    hardening = HARDENING.read_text(encoding="utf-8")
    assert "ceph auth dump-keys" in install
    assert "scripts/check_cephx_key_types.py" in install
    assert "pending, expiring, and rotating" in install
    assert "# Audit all CephX key types" in hardening
    assert "ceph auth dump-keys --format=json" in hardening
    assert "python3 scripts/check_cephx_key_types.py" in hardening
    bash_blocks = re.findall(r"```bash\n(.*?)```", install, re.DOTALL)
    assert not any(
        "ceph auth ls" in block or "ceph auth get-key client.admin" in block
        for block in bash_blocks
    )


def test_host_network_scc_permissions_are_conditional_and_verified():
    """Require direct and RBAC grant audits before shared SCC escalation."""
    install = INSTALL.read_text(encoding="utf-8")
    gate = install.split("### Host-Network SCC Gate (Only When Selected)\n", 1)[1].split("\n## ", 1)[0]
    assert "Product Ownership Gate" in gate
    assert "oc get scc rook-ceph -o jsonpath='{range .users[*]}" in gate
    assert "oc get scc rook-ceph -o jsonpath='{range .groups[*]}" in gate
    assert 'oc -n "$namespace" adm policy who-can use scc rook-ceph' in gate
    assert 'oc get namespaces -o jsonpath=' in gate
    assert "every namespace" in gate
    assert "RBAC" in gate and "direct" in gate
    assert "group membership" in gate and "STOP without patching" in gate
    blocks = re.findall(r"```bash\n(.*?)```", gate, re.DOTALL)
    assert len(blocks) == 2
    assert "set -euo pipefail" in blocks[0]
    assert 'oc -n "$namespace" adm policy who-can use scc rook-ceph' in blocks[0]
    assert 'oc get namespaces -o jsonpath=' in blocks[0]
    assert 'STOP: SCC RBAC audit failed in namespace' in blocks[0]
    assert 'incomplete SCC RBAC authorization evaluation' in blocks[0]
    assert 'missing SCC RBAC authorization results' in blocks[0]
    assert 'error during evaluation|evaluationerror|evalutionerror' in blocks[0]
    assert '2>&1' in blocks[0]
    assert "oc patch scc rook-ceph" not in blocks[0]
    assert "oc patch scc rook-ceph" in blocks[1]
    assert "spec.network.provider: host" in gate
    assert "For pod networking" in gate
    assert "oc patch scc rook-ceph --type=merge" in gate
    assert '"allowHostNetwork":true,"allowHostPorts":true' in gate
    assert "oc get scc rook-ceph -o jsonpath=" in gate
    assert "unmodified upstream OpenShift manifest" in gate
    assert "does not normally require" in gate


@pytest.mark.parametrize(
    ("scenario", "expect_success"),
    [("ok", True), ("remote_denied", False), ("list_denied", False),
     ("empty_list", False), ("local_denied", False),
     ("local_eval_error_stdout", False), ("remote_eval_error_stdout", False),
     ("remote_eval_error_stderr", False), ("remote_eval_field", False),
     ("remote_eval_typo", False), ("remote_empty_response", False),
     ("remote_malformed_response", False), ("local_empty_response", False)],
)
def test_scc_read_only_audit_all_namespaces_and_fails_closed(tmp_path, scenario, expect_success):
    """Discover local/remote SCC use and reject incomplete cluster-wide audits."""
    install = INSTALL.read_text(encoding="utf-8")
    gate = install.split("### Host-Network SCC Gate (Only When Selected)\n", 1)[1].split("\n## ", 1)[0]
    audit = re.findall(r"```bash\n(.*?)```", gate, re.DOTALL)[0]
    fake_oc = tmp_path / "oc"
    fake_oc.write_text("""#!/bin/sh
printf '%s\n' "$*" >> "$OC_CALL_LOG"
if [ "$1" = get ] && [ "$2" = namespaces ]; then
  [ "$OC_TEST_SCENARIO" = list_denied ] && exit 51
  [ "$OC_TEST_SCENARIO" = empty_list ] && exit 0
  printf 'rook-ceph\nremote-storage\n'
  exit 0
fi
if [ "$1" = '-n' ] && [ "$3 $4 $5 $6 $7 $8" = 'adm policy who-can use scc rook-ceph' ]; then
  [ "$OC_TEST_SCENARIO" = remote_denied ] && [ "$2" = remote-storage ] && exit 52
  [ "$OC_TEST_SCENARIO" = local_denied ] && [ "$2" = rook-ceph ] && exit 53
  case "$OC_TEST_SCENARIO/$2" in
    local_empty_response/rook-ceph|remote_empty_response/remote-storage)
      exit 0 ;;
    remote_malformed_response/remote-storage)
      printf 'Users:  service-account\n'; exit 0 ;;
    local_eval_error_stdout/rook-ceph|remote_eval_error_stdout/remote-storage)
      printf 'Users:  service-account\nGroups: none\nError during evaluation, results may not be complete: missing bound role\n'; exit 0 ;;
    remote_eval_error_stderr/remote-storage)
      printf 'Users:  service-account\nGroups: none\n'
      printf 'Error during evaluation, results may not be complete: missing bound role\n' >&2
      exit 0 ;;
    remote_eval_field/remote-storage)
      printf 'Users:  service-account\nGroups: none\nevaluationError: missing bound role\n'; exit 0 ;;
    remote_eval_typo/remote-storage)
      printf 'Users:  service-account\nGroups: none\nevalutionError: missing bound role\n'; exit 0 ;;
  esac
  printf 'Users:  system:serviceaccount:rook-ceph:rook-ceph-default\nGroups: none\n'
  exit 0
fi
exit 0
""", encoding="utf-8")
    fake_oc.chmod(0o755)
    log = tmp_path / "oc-log"
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", audit],
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
             "OC_CALL_LOG": str(log), "OC_TEST_SCENARIO": scenario},
        capture_output=True, text=True,
    )
    assert (result.returncode == 0) is expect_success, result.stderr
    commands = log.read_text(encoding="utf-8")
    assert commands.count("get scc rook-ceph") == 3
    assert "get namespaces -o jsonpath=" in commands
    assert "patch" not in commands
    if scenario not in ("list_denied", "empty_list"):
        assert "-n rook-ceph adm policy who-can use scc rook-ceph" in commands
    if scenario not in ("list_denied", "empty_list", "local_denied",
                        "local_eval_error_stdout", "local_empty_response"):
        # Regression: the current-namespace query alone would miss this grant.
        assert "-n remote-storage adm policy who-can use scc rook-ceph" in commands
    if expect_success:
        assert "== SCC RBAC use grants in namespace remote-storage ==" in result.stdout
        assert "Users:" in result.stdout and "Groups:" in result.stdout
    else:
        assert "STOP:" in result.stderr
    if "eval_error" in scenario or "eval_field" in scenario or "eval_typo" in scenario:
        assert "incomplete SCC RBAC authorization evaluation" in result.stderr
        assert "Error during evaluation, results may not be complete" not in result.stdout
    if "empty_response" in scenario or "malformed_response" in scenario:
        assert "missing SCC RBAC authorization results" in result.stderr
