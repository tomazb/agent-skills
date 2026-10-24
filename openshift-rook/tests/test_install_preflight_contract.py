"""Protect OpenShift SCC and full CephX audit runbook safety gates."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "references" / "install-and-preflight.md"
HARDENING = ROOT / "references" / "validation-hardening.md"


def test_installer_keeps_full_existing_cluster_key_audit():
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
    install = INSTALL.read_text(encoding="utf-8")
    gate = install.split("### Host-Network SCC Gate (Only When Selected)\n", 1)[1].split("\n## ", 1)[0]
    assert "Product Ownership Gate" in gate
    assert "spec.network.provider: host" in gate
    assert "For pod networking" in gate
    assert "oc patch scc rook-ceph --type=merge" in gate
    assert '"allowHostNetwork":true,"allowHostPorts":true' in gate
    assert "oc get scc rook-ceph -o jsonpath=" in gate
    assert "unmodified upstream OpenShift manifest" in gate
    assert "does not normally require" in gate
