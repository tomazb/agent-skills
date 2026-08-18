from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from render_sno_remediation import render_sno_remediation


def test_emits_all_deterministic_blocks():
    out = render_sno_remediation("ocs-storagecluster", "openshift-storage")
    # reconcileStrategy: ignore for all three managed resource classes
    assert "cephBlockPools" in out
    assert "cephObjectStores" in out
    assert "cephFilesystems" in out
    assert "reconcileStrategy" in out and "ignore" in out
    # topologyKey x2 -> hostname + ScheduleAnyway
    assert "cephfilesystem ocs-storagecluster-cephfilesystem" in out
    assert "cephobjectstore ocs-storagecluster-cephobjectstore" in out
    assert out.count("kubernetes.io/hostname") >= 2
    assert out.count("ScheduleAnyway") >= 2
    # CephBlockPool failureDomain fix
    assert "cephblockpool ocs-storagecluster-cephblockpool" in out
    assert '"host"' in out
    assert "replicasPerFailureDomain" in out
    # Driver CSI replicas x2
    assert "openshift-storage.rbd.csi.ceph.com" in out
    assert "openshift-storage.cephfs.csi.ceph.com" in out
    assert "controllerPlugin" in out and "replicas" in out
    # mute
    assert "POOL_NO_REDUNDANCY" in out


def test_banner_states_boundary_and_excludes_stateful_steps():
    out = render_sno_remediation("ocs-storagecluster", "openshift-storage")
    assert "CephCluster" in out and "Ready" in out  # prerequisite banner
    assert "validated-odf-sno.md" in out  # pointer for pool sizing
    assert "validation-hardening.md" in out  # pointer for onboarding recovery
    # stateful steps must NOT be emitted
    assert "onboarding-private-key" not in out
    assert "onboarding-token" not in out
    assert "osd pool ls" not in out


def test_respects_name_and_namespace():
    out = render_sno_remediation("my-sc", "my-ns")
    assert "cephfilesystem my-sc-cephfilesystem" in out
    assert "my-ns.rbd.csi.ceph.com" in out
    assert "-n my-ns" in out


def test_output_file_written(tmp_path):
    dest = tmp_path / "remediation.sh"
    render_sno_remediation("ocs-storagecluster", "openshift-storage", str(dest))
    text = dest.read_text(encoding="utf-8")
    assert "POOL_NO_REDUNDANCY" in text
    assert text.startswith("#!/usr/bin/env bash")


def _extract_patch_payloads(script: str) -> list[str]:
    # Grab the single-quoted payloads after "-p " (both --type merge and --type json).
    return re.findall(r"-p '(.*?)'", script, flags=re.DOTALL)


def test_emitted_patch_payloads_are_valid_json():
    out = render_sno_remediation("ocs-storagecluster", "openshift-storage")
    payloads = _extract_patch_payloads(out)
    assert len(payloads) >= 4  # reconcile-ignore, 2x topology, blockpool, 2x csi
    for payload in payloads:
        json.loads(payload)  # raises if any embedded patch is malformed


def test_emitted_script_is_valid_bash():
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    out = render_sno_remediation("ocs-storagecluster", "openshift-storage")
    result = subprocess.run(
        ["bash", "-n"], input=out, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_emits_object_file_pool_failuredomain_removal():
    text = render_sno_remediation()
    # Object store metadata + data pools must drop replicasPerFailureDomain
    assert "cephobjectstore ocs-storagecluster-cephobjectstore" in text
    assert "/spec/metadataPool/replicated/replicasPerFailureDomain" in text
    assert "/spec/dataPool/replicated/replicasPerFailureDomain" in text
    # Filesystem metadata AND data pools (plural indexed path) must drop it too
    assert "cephfilesystem ocs-storagecluster-cephfilesystem" in text
    assert "/spec/dataPools/0/replicated/replicasPerFailureDomain" in text


def test_emits_minimal_resource_requests():
    text = render_sno_remediation()
    # StorageCluster spec.resources minimal requests to avoid SNO CPU starvation
    assert '"mon"' in text and '"mgr"' in text and '"noobaa-core"' in text
    # frozen MDS/RGW resources patched directly on the CRs
    assert "metadataServer" in text and "gateway" in text
    # resourceProfile lean must be explicitly warned against, not used
    assert "resourceProfile" in text and "lean" in text


def test_step_numbers_are_ascending():
    # The generated review script must present its numbered steps in order so a
    # human reviewer reads them top to bottom (regression: resource block was 6
    # before mute's 5). Extract leading "# N." markers and assert ascending.
    text = render_sno_remediation()
    nums = [int(m) for m in re.findall(r"^# (\d+)\.", text, re.MULTILINE)]
    assert nums == sorted(nums), f"step numbers not ascending: {nums}"
