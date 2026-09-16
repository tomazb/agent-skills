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


def test_420_emits_blockpool_fix_and_object_file_pool_fix():
    out = render_sno_remediation("4.20")
    # CephBlockPool failure-domain fix, with size persisted in the CR
    assert "cephblockpool ocs-storagecluster-cephblockpool" in out
    assert '"value":"host"' in out
    # Dropped via merge patch, not a JSON-patch "remove" - see
    # test_422_emits_the_cephblockpool_fix for why.
    assert '"replicasPerFailureDomain":null' in out
    assert '"path":"/spec/replicated/size","value":1' in out
    assert '"path":"/spec/replicated/requireSafeReplicaSize","value":false' in out
    # Also required on 4.20.18: object/file pools reject size=1 + replicasPerFailureDomain=1
    assert "/spec/dataPools/0/replicated/replicasPerFailureDomain" in out
    assert "/spec/metadataPool/replicated/replicasPerFailureDomain" in out
    assert "/spec/dataPool/replicated/replicasPerFailureDomain" in out
    # The resource floor is opt-in on 4.20 (--lab-resources); by default it must
    # not leak into the 4.20 script
    assert "noobaa-endpoint" not in out


def test_422_emits_pool_and_resource_blocks():
    out = render_sno_remediation("4.22")
    assert "/spec/metadataPool/replicated/replicasPerFailureDomain" in out
    assert "/spec/dataPool/replicated/replicasPerFailureDomain" in out
    assert "/spec/dataPools/0/replicated/replicasPerFailureDomain" in out


def test_422_emits_the_cephblockpool_fix():
    # Regression, observed on ODF 4.22.3 (htz2, 2026-09-16): the CephBlockPool CR
    # ships failureDomain=osd with size=3 and replicasPerFailureDomain=1, so Rook
    # reverts a live `ceph osd pool set ... size 1` and the cluster sits at
    # "32 pgs inactive / undersized" forever. This block used to be 4.20-only.
    out = render_sno_remediation("4.22")
    assert "cephblockpool ocs-storagecluster-cephblockpool" in out
    assert '"/spec/failureDomain","value":"host"' in out
    # replicasPerFailureDomain is dropped with a merge patch, not a JSON-patch
    # "remove": verified on a live OCP 4.22.12 apiserver that removing an absent
    # member is rejected, which under `set -e` would abort the script after the
    # reconcile freeze and topologyKey patches had already been applied.
    assert '"replicasPerFailureDomain":null' in out
    assert '"op":"remove","path":"/spec/replicated/replicasPerFailureDomain"' not in out


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


@pytest.mark.parametrize(
    "release,lab_resources", [("4.22", False), ("4.22", True), ("4.20", True)]
)
def test_emits_minimal_resource_requests_with_expected_values(release, lab_resources):
    out = render_sno_remediation(release, lab_resources=lab_resources)
    runnable = _executable_lines(out)
    payloads = [json.loads(p) for p in _extract_patch_payloads(runnable)]
    merges = [p for p in payloads if isinstance(p, dict)]

    resources = next(
        p["spec"]["resources"] for p in merges if "resources" in p.get("spec", {})
    )
    assert resources["mon"]["requests"] == {"cpu": "100m", "memory": "1Gi"}
    assert resources["mgr"]["requests"] == {"cpu": "100m", "memory": "1Gi"}
    assert resources["noobaa-core"]["requests"] == {"cpu": "100m", "memory": "1Gi"}
    assert resources["noobaa-endpoint"]["requests"] == {"cpu": "100m", "memory": "512Mi"}
    # noobaa-db must NOT be constrained here. Lowering its request makes NooBaa
    # recompute the CNPG postgres spec, and NooBaa refuses to apply a CNPG spec
    # change while its own phase is Creating - which it can never leave, because
    # that same reconcile errors. Observed as a permanent deadlock on ODF 4.22.3
    # (htz2, 2026-09-16): CNPG Ready 2/2, zero noobaa-core pods, StorageCluster
    # stuck Progressing, and a noobaa-operator restart did not clear it.
    assert "noobaa-db" not in resources

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
        "7",
    ]
    assert _step_labels(render_sno_remediation("4.22")) == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
    ]


def test_lab_resources_adds_the_floor_to_420_before_the_mute():
    # Low-vCPU lab SNO on 4.20: nothing is Pending, but ODF's balanced requests
    # (~17.8 cores observed on 4.20.18 with block, file and object) leave little
    # schedulable CPU for workloads. The floor is opt-in there.
    out = render_sno_remediation("4.20", lab_resources=True)
    assert _step_labels(out) == ["1", "2", "3", "4", "5", "6", "7", "8"]
    runnable = _executable_lines(out)
    assert '"noobaa-endpoint"' in runnable
    assert "noobaa-db" not in runnable
    floor_at = out.index("# 7.")
    assert "resources" in out[floor_at : out.index("# 8.")]
    assert "POOL_NO_REDUNDANCY" in out[out.index("# 8.") :]


def test_lab_resources_does_not_change_422():
    # 4.22 always needs the floor (pods are Pending without it), so the flag is a
    # documented no-op there rather than a second code path.
    assert render_sno_remediation("4.22", lab_resources=True) == render_sno_remediation(
        "4.22"
    )


def test_resource_floor_warns_it_is_lab_only_and_about_mgr_pool_revert():
    for release in RELEASES:
        out = render_sno_remediation(release, lab_resources=True)
        floor = out[out.index('"resources"') - 2500 : out.index('"resources"')]
        # Requests this low give Ceph no guaranteed CPU under contention.
        assert "lab" in floor.lower()
        # The patch restarts mgr, which re-applies .mgr size=3 on both releases.
        assert ".mgr" in floor


@pytest.mark.parametrize("lab_resources", [False, True])
@pytest.mark.parametrize("release", RELEASES)
def test_emitted_script_with_lab_resources_is_valid(release, lab_resources):
    out = render_sno_remediation(release, lab_resources=lab_resources)
    for payload in _extract_patch_payloads(out):
        json.loads(payload)
    bash_path = shutil.which("bash")
    if bash_path is None:
        pytest.skip("bash not available")
    result = subprocess.run([bash_path, "-n"], input=out, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_module_docstring_matches_release_block_scope():
    """Keep the generator docstring aligned with `_BLOCKS` (not the old 4.22-only claim)."""
    import render_sno_remediation as mod

    doc = mod.__doc__ or ""
    assert "CephBlockPool" in doc
    assert "resource-request" in doc.lower() or "resource request" in doc.lower()
    # 4.20 must document object/file (or CephObjectStore/CephFilesystem) on the
    # same line as the release — not via a DOTALL match to a later paragraph.
    assert re.search(
        r"^.*\b4\.20\b.*(object/file|CephObjectStore|CephFilesystem).*$",
        doc,
        re.IGNORECASE | re.MULTILINE,
    ), "4.20 block scope must mention object/file CR-spec fixes on the same line"
    assert re.search(
        r"^.*\b4\.20\b.*CephBlockPool.*$",
        doc,
        re.IGNORECASE | re.MULTILINE,
    ), "4.20 block scope must mention the CephBlockPool failure-domain fix"
    assert "4.22 only" not in doc


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


def test_cli_lab_resources_flag_emits_the_420_floor():
    plain = _run_cli("--release", "4.20")
    lab = _run_cli("--release", "4.20", "--lab-resources")
    assert plain.returncode == 0 and lab.returncode == 0, lab.stderr
    assert '"noobaa-endpoint"' not in plain.stdout
    assert '"noobaa-endpoint"' in lab.stdout


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


def test_context_pin_wraps_every_oc_call():
    """--context must pin the whole script, not just document an intent.

    The rendered script uses bare `oc`, so without a pin it mutates whatever
    kubeconfig context happens to be current. A shell function is used because it
    is inherited by the command substitutions the script relies on.
    """
    out = render_sno_remediation("4.22", context="htz2")
    assert 'oc() { command oc --context=htz2 "$@"; }' in out


def test_context_pin_absent_by_default():
    assert "command oc --context=" not in render_sno_remediation("4.22")


def test_preflight_always_announces_the_target_cluster():
    # The release preflight answers "is this the right software?" but never
    # "is this the right cluster?" - print it, and let ODF_EXPECT_CONTEXT make a
    # mismatch fatal.
    out = render_sno_remediation("4.22")
    assert "target cluster:" in out
    assert "ODF_EXPECT_CONTEXT" in out


def test_pinned_context_is_used_for_label_and_expectation_check():
    """`oc config current-context` ignores the --context override.

    Verified against a live cluster: with the kubeconfig on `prod1`,
    `oc --context=htz2 config current-context` still prints `prod1`, while
    `oc --context=htz2 whoami --show-server` correctly resolves htz2. Deriving
    the label from `config current-context` therefore mislabels the target, and
    comparing it against ODF_EXPECT_CONTEXT false-fatals on exactly the runs the
    pin was added to protect.
    """
    out = render_sno_remediation("4.22", context="htz2")
    assert "ODF_TARGET_CONTEXT=htz2" in out
    # The label and the expectation check both go through TARGET_CONTEXT, which
    # prefers the pin and only falls back to current-context when unpinned.
    assert 'TARGET_CONTEXT="${ODF_TARGET_CONTEXT:-' in out
    assert '[ "$TARGET_CONTEXT" != "$ODF_EXPECT_CONTEXT" ]' in out
    # The pinned value must not be re-derived from current-context anywhere.
    assert '[ "$(oc config current-context 2>/dev/null)" != "$ODF_EXPECT_CONTEXT" ]' not in out


def test_unpinned_preflight_falls_back_to_current_context():
    out = render_sno_remediation("4.22")
    assert "ODF_TARGET_CONTEXT=" not in out
    assert 'TARGET_CONTEXT="${ODF_TARGET_CONTEXT:-$(oc config current-context' in out


@pytest.mark.parametrize(
    "bad",
    ["a; rm -rf /", "a b", "a$(id)", "a`id`", "a\nb", "a'b", 'a"b'],
)
def test_context_rejects_shell_injection(bad):
    """The context is interpolated into an unquoted shell word in the wrapper."""
    with pytest.raises(ValueError):
        render_sno_remediation("4.22", context=bad)


def test_docs_route_low_vcpu_clusters_to_the_lab_floor():
    """The flag is only useful if a reader with too few vCPUs can find it."""
    root = SCRIPTS_DIR.parent
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    preflight = (root / "references" / "install-and-preflight.md").read_text(encoding="utf-8")
    validated = (root / "references" / "validated-odf-sno.md").read_text(encoding="utf-8")

    assert "--lab-resources" in skill and "Insufficient cpu" in skill
    # The exception that permits editing frozen Rook CRs must cover resources,
    # or the floor would violate the skill's own safety rule.
    assert "MDS/RGW resource requests" in skill

    assert "CPU Request Budget" in preflight
    assert "--lab-resources" in preflight
    assert "lean" in preflight and "production" in preflight

    section = validated[validated.index("## ODF 4.20 SNO: Optional CPU-Request Floor") :]
    section = section[: section.index("\n---\n")]
    assert "--release 4.20 --lab-resources" in section
    assert "not yet applied on a live 4.20 cluster" in section
    assert "Lab only" in section and ".mgr" in section
