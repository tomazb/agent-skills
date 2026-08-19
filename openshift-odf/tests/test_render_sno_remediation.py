from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "render_sno_remediation.py"
sys.path.insert(0, str(SCRIPTS_DIR))

from render_sno_remediation import RELEASES, render_sno_remediation


def _executable_lines(script: str) -> str:
    """Everything the operator's shell would actually run (comments stripped)."""
    return "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )


def _extract_patch_payloads(script: str) -> list[str]:
    # Grab the single-quoted payloads after "-p " (both --type merge and --type json).
    return re.findall(r"-p '(.*?)'", script, flags=re.DOTALL)


def _step_labels(script: str) -> list[str]:
    return re.findall(r"^# (\d+[a-z]?)\.", script, re.MULTILINE)


@pytest.mark.parametrize("release", RELEASES)
def test_emits_release_independent_blocks(release):
    out = render_sno_remediation(release, "ocs-storagecluster", "openshift-storage")
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
    # Driver CSI replicas x2
    assert "openshift-storage.rbd.csi.ceph.com" in out
    assert "openshift-storage.cephfs.csi.ceph.com" in out
    assert "controllerPlugin" in out and "replicas" in out
    # the banner names the release it was rendered for
    assert f"ODF {release} SNO deterministic remediation" in out


def test_release_is_required_and_validated():
    with pytest.raises(TypeError):
        render_sno_remediation()  # release has no default: pick a version explicitly
    for bad in ("4.22.0", "4.19", "latest", ""):
        with pytest.raises(ValueError, match="not a validated ODF SNO release"):
            render_sno_remediation(bad)


def test_420_emits_blockpool_fix_and_no_422_only_blocks():
    out = render_sno_remediation("4.20")
    # 4.20-only: CephBlockPool failure-domain fix, with size persisted in the CR
    assert "cephblockpool ocs-storagecluster-cephblockpool" in out
    assert '"value":"host"' in out
    assert '"path":"/spec/replicated/replicasPerFailureDomain"' in out
    assert '"path":"/spec/replicated/size","value":1' in out
    assert '"path":"/spec/replicated/requireSafeReplicaSize","value":false' in out
    # 4.22-only blocks must not leak into the 4.20 script: the `remove` ops would
    # abort the run under `set -e` on a cluster that never had the field.
    assert "/spec/dataPools/0/replicated/replicasPerFailureDomain" not in out
    assert "noobaa-endpoint" not in out


def test_422_emits_pool_and_resource_blocks_and_no_420_only_blocks():
    out = render_sno_remediation("4.22")
    assert "/spec/metadataPool/replicated/replicasPerFailureDomain" in out
    assert "/spec/dataPool/replicated/replicasPerFailureDomain" in out
    assert "/spec/dataPools/0/replicated/replicasPerFailureDomain" in out
    # 4.20-only CephBlockPool failure-domain rewrite must not appear
    assert "cephblockpool" not in out


def test_422_guards_single_cephfilesystem_data_pool():
    out = render_sno_remediation("4.22")
    runnable = _executable_lines(out)
    # the guard must be executable, not advisory, and must fail closed
    assert "DATA_POOLS=$(oc -n openshift-storage get cephfilesystem" in runnable
    assert "-ne 1" in runnable
    assert "exit 1" in runnable


def test_banner_states_boundary_and_excludes_stateful_steps():
    for release in RELEASES:
        out = render_sno_remediation(release, "ocs-storagecluster", "openshift-storage")
        assert "CephCluster" in out and "Ready" in out  # prerequisite banner
        assert "validated-odf-sno.md" in out  # pointer for pool sizing
        assert "validation-hardening.md" in out  # pointer for onboarding recovery
        # stateful steps must NOT be emitted as commands
        runnable = _executable_lines(out)
        assert "onboarding-private-key" not in runnable
        assert "onboarding-token" not in runnable
        assert "osd pool ls" not in runnable
        # the mute is guidance only: it must never run before pool sizing
        assert "POOL_NO_REDUNDANCY" in out
        assert "POOL_NO_REDUNDANCY" not in runnable
        assert "health mute" not in runnable


def test_respects_name_and_namespace():
    out = render_sno_remediation("4.22", "my-sc", "my-ns")
    assert "cephfilesystem my-sc-cephfilesystem" in out
    assert "my-ns.rbd.csi.ceph.com" in out
    assert "-n my-ns" in out


@pytest.mark.parametrize(
    "name,namespace",
    [
        ("my-ns; rm -rf /", "openshift-storage"),
        ("ocs-storagecluster", "ns' ; touch /tmp/pwn ; '"),
        ("-leading-dash", "openshift-storage"),
        ("ocs-storagecluster", "Upper-Case"),
        # 64 chars: valid syntax, but past the RFC 1123 label limit, so every
        # emitted `oc -n` command would be rejected by the API server.
        ("ocs-storagecluster", "n" * 64),
        # Trailing newline: `$` matches before it, so a plain re.match would
        # accept this and split every emitted `oc` command in two.
        ("ocs-storagecluster", "openshift-storage\n"),
        ("my-sc\n", "openshift-storage"),
    ],
)
def test_rejects_names_that_would_inject_shell_syntax(name, namespace):
    # Operands are interpolated into executable shell and single-quoted JSON.
    # Quoting them in place would corrupt the payloads, so invalid names are
    # rejected outright instead.
    with pytest.raises(ValueError, match="RFC 1123"):
        render_sno_remediation("4.22", name, namespace)


def test_output_file_written(tmp_path):
    dest = tmp_path / "remediation.sh"
    render_sno_remediation("4.22", "ocs-storagecluster", "openshift-storage", str(dest))
    text = dest.read_text(encoding="utf-8")
    assert "POOL_NO_REDUNDANCY" in text
    assert text.startswith("#!/usr/bin/env bash")


def test_emitted_patch_payloads_are_valid_json():
    for release in RELEASES:
        out = render_sno_remediation(release, "ocs-storagecluster", "openshift-storage")
        payloads = _extract_patch_payloads(out)
        assert len(payloads) >= 4  # reconcile-ignore, 2x topology, 2x csi
        for payload in payloads:
            json.loads(payload)  # raises if any embedded patch is malformed


@pytest.mark.parametrize("release", RELEASES)
def test_emitted_script_is_valid_bash(release):
    bash_path = shutil.which("bash")
    if bash_path is None:
        pytest.skip("bash not available")
    out = render_sno_remediation(release, "ocs-storagecluster", "openshift-storage")
    result = subprocess.run(
        [bash_path, "-n"], input=out, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_emits_minimal_resource_requests_with_expected_values():
    out = render_sno_remediation("4.22")
    runnable = _executable_lines(out)
    payloads = [json.loads(p) for p in _extract_patch_payloads(runnable)]
    merges = [p for p in payloads if isinstance(p, dict)]

    resources = next(
        p["spec"]["resources"] for p in merges if "resources" in p.get("spec", {})
    )
    assert resources["mon"]["requests"] == {"cpu": "100m", "memory": "1Gi"}
    assert resources["mgr"]["requests"] == {"cpu": "100m", "memory": "1Gi"}
    assert resources["noobaa-core"]["requests"] == {"cpu": "100m", "memory": "1Gi"}
    assert resources["noobaa-db"]["requests"] == {"cpu": "100m", "memory": "512Mi"}
    assert resources["noobaa-endpoint"]["requests"] == {"cpu": "100m", "memory": "512Mi"}

    device_set = next(
        op
        for p in payloads
        if isinstance(p, list)
        for op in p
        if op.get("path") == "/spec/storageDeviceSets/0/resources"
    )
    assert device_set["value"]["requests"] == {"cpu": "100m", "memory": "2Gi"}
    assert device_set["value"]["limits"] == {"cpu": "2", "memory": "5Gi"}

    for key, section in (("metadataServer", "metadataServer"), ("gateway", "gateway")):
        spec = next(p["spec"][section] for p in merges if section in p.get("spec", {}))
        assert spec["resources"]["requests"] == {"cpu": "100m", "memory": "1Gi"}
        assert spec["resources"]["limits"] == {"cpu": "2", "memory": "4Gi"}

    # resourceProfile: lean is warned about in prose and never configured
    assert "resourceProfile" in out and "lean" in out
    assert "resourceProfile" not in runnable


def test_step_labels_form_the_expected_sequence_per_release():
    # The generated review script must present contiguous, ordered steps so a
    # human reviewer reads them top to bottom (regression: resource block was 6
    # before mute's 5). Numbers are assigned at render time, so a gated-out
    # block must not leave a gap or a duplicate.
    assert _step_labels(render_sno_remediation("4.20")) == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    ]
    assert _step_labels(render_sno_remediation("4.22")) == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
    ]


@pytest.mark.parametrize("release", RELEASES)
def test_release_preflight_precedes_every_mutating_command(release):
    # --release only selects templates. Without a preflight the wrong-release
    # script mutates resources and only then fails on an inapplicable patch;
    # `set -e` stops the run but does not undo those writes.
    out = render_sno_remediation(release)
    runnable = _executable_lines(out)
    assert f"ocs-operator.v{release}." in runnable
    assert "no ocs-operator CSV found" in runnable

    guard_at = runnable.index("INSTALLED_CSV=")
    first_mutation = min(
        runnable.index(token)
        for token in ("oc -n openshift-storage patch", "oc -n openshift-storage exec")
        if token in runnable
    )
    assert guard_at < first_mutation, "preflight must precede the first mutation"


def _run_preflight(rendered: str, csv_lines: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute the emitted script with `oc` stubbed out.

    Reads are answered from csv_lines; every other `oc` call reports itself as
    MUTATION instead of touching a cluster, so a test can assert that nothing
    was mutated before the preflight rejected the run.
    """
    bash_path = shutil.which("bash")
    if bash_path is None:
        pytest.skip("bash not available")
    stub = (
        "oc() {\n"
        '  case "$*" in\n'
        "    *'get csv'*) printf '%s\\n' "
        + " ".join(f"'{line}'" for line in csv_lines)
        + " ;;\n"
        '    *) echo "MUTATION: $*" ;;\n'
        "  esac\n"
        "}\n"
    )
    body = rendered.split("\n", 1)[1]  # drop the shebang
    return subprocess.run(
        [bash_path, "-c", stub + body], capture_output=True, text=True, check=False
    )


def test_preflight_refuses_ambiguous_csv_discovery():
    # A glob matches across newlines, so a newline-separated list starting with
    # the right release would otherwise pass the release check.
    result = _run_preflight(
        render_sno_remediation("4.22"),
        ["ocs-operator.v4.22.1-rhodf", "ocs-operator.v4.20.16-rhodf"],
    )
    assert result.returncode == 1
    assert "multiple ocs-operator CSVs" in result.stderr
    assert "MUTATION" not in result.stdout


def test_preflight_refuses_wrong_release_and_missing_csv():
    wrong = _run_preflight(render_sno_remediation("4.22"), ["ocs-operator.v4.20.16-rhodf"])
    assert wrong.returncode == 1
    assert "is not 4.22" in wrong.stderr
    assert "MUTATION" not in wrong.stdout

    missing = _run_preflight(render_sno_remediation("4.20"), [])
    assert missing.returncode == 1
    assert "no ocs-operator CSV found" in missing.stderr
    assert "MUTATION" not in missing.stdout


def test_preflight_allows_the_matching_release():
    result = _run_preflight(render_sno_remediation("4.22"), ["ocs-operator.v4.22.1-rhodf"])
    assert "MUTATION: -n openshift-storage patch storagecluster" in result.stdout


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_writes_output_file_and_reports_path(tmp_path):
    dest = tmp_path / "remediation.sh"
    result = _run_cli(
        "--release", "4.22",
        "--name", "my-sc",
        "--namespace", "my-ns",
        "--output", str(dest),
    )
    assert result.returncode == 0, result.stderr
    assert f"SNO remediation script written to {dest}" in result.stdout
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "cephfilesystem my-sc-cephfilesystem" in text
    assert "-n my-ns" in text


def test_cli_prints_to_stdout_without_output_flag():
    result = _run_cli("--release", "4.20")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("#!/usr/bin/env bash")
    assert "ODF 4.20 SNO deterministic remediation" in result.stdout
    assert "cephblockpool ocs-storagecluster-cephblockpool" in result.stdout


def test_cli_requires_release():
    result = _run_cli("--name", "ocs-storagecluster")
    assert result.returncode != 0
    assert "--release" in result.stderr


def test_cli_rejects_unvalidated_release_and_invalid_names():
    unvalidated = _run_cli("--release", "4.22.0")
    assert unvalidated.returncode != 0
    assert "invalid choice" in unvalidated.stderr

    injected = _run_cli("--release", "4.22", "--namespace", "my-ns; id")
    assert injected.returncode != 0
    assert "RFC 1123" in injected.stderr
