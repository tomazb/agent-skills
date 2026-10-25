"""Protect OpenShift SCC and full CephX audit runbook safety gates."""

import os
import re
import subprocess
from pathlib import Path

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
    assert "oc adm policy who-can use scc rook-ceph" in gate
    assert "RBAC" in gate and "direct" in gate
    assert "group membership" in gate and "STOP without patching" in gate
    blocks = re.findall(r"```bash\n(.*?)```", gate, re.DOTALL)
    assert len(blocks) == 2
    assert "set -euo pipefail" in blocks[0]
    assert "oc adm policy who-can use scc rook-ceph" in blocks[0]
    assert "oc patch scc rook-ceph" not in blocks[0]
    assert "oc patch scc rook-ceph" in blocks[1]
    assert "spec.network.provider: host" in gate
    assert "For pod networking" in gate
    assert "oc patch scc rook-ceph --type=merge" in gate
    assert '"allowHostNetwork":true,"allowHostPorts":true' in gate
    assert "oc get scc rook-ceph -o jsonpath=" in gate
    assert "unmodified upstream OpenShift manifest" in gate
    assert "does not normally require" in gate


def test_scc_read_only_audit_fails_closed_on_rbac_query_error(tmp_path):
    """A failed RBAC lookup must stop the audit before SCC mutation advice."""
    install = INSTALL.read_text(encoding="utf-8")
    gate = install.split("### Host-Network SCC Gate (Only When Selected)\n", 1)[1].split("\n## ", 1)[0]
    audit = re.findall(r"```bash\n(.*?)```", gate, re.DOTALL)[0]
    fake_oc = tmp_path / "oc"
    fake_oc.write_text("""#!/bin/sh
printf '%s\n' "$*" >> "$OC_CALL_LOG"
if [ "$1 $2 $3 $4 $5 $6" = 'adm policy who-can use scc rook-ceph' ]; then
  exit 42
fi
exit 0
""", encoding="utf-8")
    fake_oc.chmod(0o755)
    log = tmp_path / "oc-log"
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", audit],
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
             "OC_CALL_LOG": str(log)},
        capture_output=True, text=True,
    )
    assert result.returncode == 42, result.stderr
    commands = log.read_text(encoding="utf-8")
    assert "who-can use scc rook-ceph" in commands
    assert "patch" not in commands
    assert commands.count("get scc rook-ceph") == 3
