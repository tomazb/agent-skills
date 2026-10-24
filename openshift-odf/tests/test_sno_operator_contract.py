"""Execute both documented SNO procedures against a stateful mocked oc."""

import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "references/validated-odf-sno.md"
FLAG = {"name": "SINGLE_NODE", "value": "true"}

OC = r'''#!/usr/bin/env python3
import copy, json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] != ['-n', 'openshift-storage']:
    raise SystemExit(99)
args = args[2:]
path = Path(os.environ['OC_FIXTURE'])
state = json.loads(path.read_text())
def propagate():
    csv = next(i for i in state['items'] if i['kind'] == 'ClusterServiceVersion')
    dep = next(i for i in state['items'] if i['kind'] == 'Deployment')
    template = next(i for i in csv['spec']['install']['spec']['deployments'] if i['name'] == 'ocs-operator')
    source = next(i for i in template['spec']['template']['spec']['containers'] if i['name'] == 'ocs-operator')
    dest = next(i for i in dep['spec']['template']['spec']['containers'] if i['name'] == 'ocs-operator')
    dest['env'] = copy.deepcopy(source['env'])
with Path(os.environ['OC_LOG']).open('a') as log:
    log.write(json.dumps(args) + '\n')
if args[0] == state.get('fail'):
    raise SystemExit(42)
if args == ['get', 'infrastructure', 'cluster', '-o', 'json']:
    print(json.dumps({'status': {'controlPlaneTopology': state['topology']}}))
elif args == ['get', 'csv,deployment', '-o', 'json']:
    if state.get('_patched'):
        if state.get('fail') == 'poll':
            raise SystemExit(42)
        state['_polls'] = state.get('_polls', 0) + 1
        if state.get('propagate_after') and state['_polls'] >= state['propagate_after']:
            propagate()
        path.write_text(json.dumps(state))
    print(json.dumps({'items': state['items']}))
elif args == ['rollout', 'status', 'deploy/ocs-operator', '--timeout=3m']:
    pass  # Status may still be stale: the real helper must re-read it.
elif args[:2] == ['wait', 'deployment/ocs-operator']:
    if state.get('old_client'):
        sys.stderr.write('unrecognized condition: filtered jsonpath\n')
        raise SystemExit(42)
    raise SystemExit(99)
elif args == ['exec', 'deploy/ocs-operator', '-c', 'ocs-operator', '--', 'printenv', 'SINGLE_NODE']:
    sys.stdout.write(state['runtime'])
elif args[:2] == ['patch', 'csv'] and args[3:5] == ['--type=json', '-p']:
    patch = json.loads(args[5])
    csv = next(i for i in state['items'] if i['kind'] == 'ClusterServiceVersion' and i['metadata']['name'] == args[2])
    # Apply real JSON Patch operations, including the optimistic-lock test.
    updated = copy.deepcopy(csv)
    for operation in patch:
        keys = operation['path'].strip('/').split('/')
        parent = updated
        for key in keys[:-1]:
            parent = parent[int(key)] if isinstance(parent, list) else parent[key]
        last = keys[-1]
        target = int(last) if isinstance(parent, list) and last != '-' else last
        if operation['op'] == 'test':
            if parent[target] != operation['value']:
                raise SystemExit(43)
        elif operation['op'] == 'remove':
            del parent[target]
        elif operation['op'] == 'add' and last == '-':
            parent.append(operation['value'])
        elif operation['op'] in ('add', 'replace'):
            parent[target] = operation['value']
        else:
            raise SystemExit(99)
    csv.update(updated)
    state['_patched'] = True
    if state.get('propagate', True) and not state.get('propagate_after'):
        propagate()
    path.write_text(json.dumps(state))
else:
    raise SystemExit(99)
'''


def fixture(csv_env=None, deployment_env=None):
    def pod_spec(env):
        operator = {"name": "ocs-operator"}
        if env is not None:
            operator["env"] = copy.deepcopy(env)
        return {"template": {"spec": {"containers": [
            {"name": "sidecar", "env": [FLAG]}, operator]}}}

    csv = {"kind": "ClusterServiceVersion", "metadata": {
        "name": "ocs-operator.v4.20.19-rhodf", "uid": "csv-uid", "resourceVersion": "11"},
        "spec": {"install": {"spec": {"deployments": [
            {"name": "other-deployment", "spec": pod_spec([FLAG])},
            {"name": "ocs-operator", "spec": pod_spec(csv_env)}]}}}}
    dep = {"kind": "Deployment", "metadata": {"name": "ocs-operator", "generation": 7},
           "spec": {**pod_spec(deployment_env), "replicas": 1},
           "status": {"observedGeneration": 7, "replicas": 1, "updatedReplicas": 1,
                      "readyReplicas": 1, "availableReplicas": 1}}
    return {"items": [csv, dep], "topology": "SingleReplica", "runtime": "true\n"}


def execute(tmp_path, state, *, configure=False, configuration_only=False, script_override=None, propagation_timeout=None):
    source = tmp_path / "fixture.json"
    source.write_text(json.dumps(state))
    log = tmp_path / "oc.jsonl"
    oc = tmp_path / "oc"
    oc.write_text(OC)
    oc.chmod(0o755)
    blocks = re.findall(r"```bash\n(.*?)```", REFERENCE.read_text(), re.DOTALL)
    marker = "# Configure SNO operator through its CSV" if configure else "# Read-only SNO operator gate"
    if configuration_only:
        marker = "# Pre-install SNO desired configuration only"
    script = script_override or next(b for b in blocks if marker in b)
    if propagation_timeout is not None:
        script = script.rstrip() + " --propagation-timeout " + str(propagation_timeout) + "\n"
    run = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", script], cwd=ROOT,
                         env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                              "OC_FIXTURE": str(source), "OC_LOG": str(log)}, capture_output=True, text=True)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return run, json.loads(source.read_text()), calls


@pytest.mark.parametrize("csv_env,dep_env", [([], []), ([FLAG], []), ([], [FLAG]),
    ([{"name": "SINGLE_NODE", "value": "false"}], [FLAG]),
    ([{"name": "SINGLE_NODE", "valueFrom": {}}], [FLAG]), ([FLAG, FLAG], [FLAG])])
def test_missing_or_invalid_desired_flag_rejected(tmp_path, csv_env, dep_env):
    run, _, calls = execute(tmp_path, fixture(csv_env, dep_env))
    assert run.returncode != 0
    assert not any(c[0] == "exec" for c in calls)


def test_complete_rollout_and_runtime_verified(tmp_path):
    run, _, calls = execute(tmp_path, fixture([FLAG], [FLAG]))
    assert run.returncode == 0, run.stderr
    assert "SNO operator configuration verified" in run.stdout
    watch = next(i for i, c in enumerate(calls) if c[0] == "rollout")
    runtime = next(i for i, c in enumerate(calls) if c[0] == "exec")
    assert watch < runtime
    assert calls[runtime][2:4] == ["-c", "ocs-operator"]
    assert any(c == ["get", "csv,deployment", "-o", "json"] for c in calls[watch + 1:runtime])


@pytest.mark.parametrize("field,value", [("observedGeneration", 6), ("updatedReplicas", 0),
    ("readyReplicas", 0), ("availableReplicas", 0), ("replicas", 2), ("unavailableReplicas", 1)])
def test_incomplete_rollout_rejected_even_if_watch_succeeds(tmp_path, field, value):
    state = fixture([FLAG], [FLAG])
    state["items"][1]["status"][field] = value
    run, _, calls = execute(tmp_path, state)
    assert run.returncode != 0
    assert not any(c[0] == "exec" for c in calls)


@pytest.mark.parametrize("runtime", ["false\n", "", " true\n", "true \n", "true\n\n"])
def test_runtime_mismatch_rejected(tmp_path, runtime):
    state = fixture([FLAG], [FLAG]); state["runtime"] = runtime
    assert execute(tmp_path, state)[0].returncode != 0


@pytest.mark.parametrize("action", ["get", "rollout", "exec"])
def test_query_watch_and_exec_failures_rejected(tmp_path, action):
    state = fixture([FLAG], [FLAG]); state["fail"] = action
    assert execute(tmp_path, state)[0].returncode != 0


@pytest.mark.parametrize("topology", ["HighlyAvailable", "", None])
def test_non_sno_or_unknown_topology_never_patched(tmp_path, topology):
    state = fixture([], []); state["topology"] = topology
    run, _, calls = execute(tmp_path, state, configure=True)
    assert run.returncode != 0
    assert not any(c[0] == "patch" for c in calls)


@pytest.mark.parametrize("env", [None, [], [{"name": "OTHER", "value": "keep"}],
    [{"name": "SINGLE_NODE", "value": "false"}],
    [{"name": "SINGLE_NODE", "valueFrom": {"secretKeyRef": {"name": "example", "key": "flag"}}}],
    [FLAG, FLAG], [{"name": "BEFORE", "value": "keep"}, {"name": "SINGLE_NODE", "value": "false"},
                   {"name": "AFTER", "value": "keep"}]])
def test_configure_targets_named_operator_and_preserves_other_entries(tmp_path, env):
    state = fixture(env, [])
    original = copy.deepcopy(state["items"][0])
    run, final, calls = execute(tmp_path, state, configure=True)
    assert run.returncode == 0, run.stderr
    patch_calls = [c for c in calls if c[0] == "patch"]
    assert len(patch_calls) == 1
    patch = json.loads(patch_calls[0][-1])
    assert patch[0] == {"op": "test", "path": "/metadata/resourceVersion", "value": "11"}
    assert all(op["path"].startswith("/spec/install/spec/deployments/1/spec/template/spec/containers/1/env") for op in patch[1:])
    expected = copy.deepcopy(original)
    target = expected["spec"]["install"]["spec"]["deployments"][1]["spec"]["template"]["spec"]["containers"][1]
    target["env"] = []
    added = False
    for entry in env or []:
        if entry["name"] != "SINGLE_NODE":
            target["env"].append(entry)
        elif not added:
            target["env"].append(FLAG); added = True
    if not added:
        target["env"].append(FLAG)
    assert final["items"][0] == expected
    patched = next(i for i, c in enumerate(calls) if c[0] == "patch")
    assert calls[patched + 1] == ["get", "csv,deployment", "-o", "json"]
    assert not any(c[0] == "wait" for c in calls)


def test_correct_csv_is_noop_but_still_checks_runtime(tmp_path):
    state = fixture([FLAG], [FLAG]); state["runtime"] = "false\n"
    run, _, calls = execute(tmp_path, state, configure=True)
    assert run.returncode != 0
    assert not any(c[0] == "patch" for c in calls)
    assert any(c[0] == "exec" for c in calls)


@pytest.mark.parametrize("failure", ["patch", "poll", "rollout", "exec"])
def test_failed_remediation_never_reports_success(tmp_path, failure):
    state = fixture([], []); state["fail"] = failure
    run, _, _ = execute(tmp_path, state, configure=True)
    assert run.returncode != 0
    assert "SNO operator configuration verified" not in run.stdout


def test_unpropagated_patch_rejected(tmp_path):
    state = fixture([], []); state["propagate"] = False
    run, _, calls = execute(tmp_path, state, configure=True, propagation_timeout=0)
    assert run.returncode != 0
    assert "before timeout" in run.stderr
    assert not any(c[0] in ("rollout", "exec") for c in calls)


def test_ambiguous_csv_cannot_patch(tmp_path):
    state = fixture([], []); state["items"].append(copy.deepcopy(state["items"][0]))
    run, _, calls = execute(tmp_path, state, configure=True)
    assert run.returncode != 0
    assert not any(c[0] == "patch" for c in calls)


def test_correct_configuration_noop_still_verifies_runtime(tmp_path):
    run, _, calls = execute(tmp_path, fixture([FLAG], [FLAG]), configure=True)
    assert run.returncode == 0, run.stderr
    assert not any(c[0] == "patch" for c in calls)
    assert any(c[0] == "rollout" for c in calls)
    assert any(c[0] == "exec" for c in calls)


def test_preinstall_configures_only_desired_state_without_runtime_claim(tmp_path):
    state = fixture([], [])
    state["items"][1]["spec"]["replicas"] = 0
    state["items"][1]["status"] = {"replicas": 0, "observedGeneration": 7}
    run, _, calls = execute(tmp_path, state, configuration_only=True)
    assert run.returncode == 0, run.stderr
    assert "Desired CSV/Deployment configuration verified" in run.stdout
    assert "SNO operator configuration verified" not in run.stdout
    assert not any(c[0] in ("rollout", "exec") for c in calls)


def test_default_runtime_check_rejects_zero_replica_operator(tmp_path):
    state = fixture([FLAG], [FLAG]); state["items"][1]["spec"]["replicas"] = 0
    assert execute(tmp_path, state)[0].returncode != 0


@pytest.mark.parametrize("configuration_only", [False, True])
def test_old_client_can_configure_without_filtered_wait(tmp_path, configuration_only):
    state = fixture([], []); state["old_client"] = True
    run, _, calls = execute(tmp_path, state, configure=not configuration_only,
                            configuration_only=configuration_only)
    assert run.returncode == 0, run.stderr
    assert not any(c[0] == "wait" for c in calls)


@pytest.mark.parametrize("configuration_only", [False, True])
def test_delayed_olm_propagation_is_polled_before_verification(tmp_path, configuration_only):
    state = fixture([], []); state["propagate_after"] = 2; state["old_client"] = True
    run, final, calls = execute(tmp_path, state, configure=not configuration_only,
                               configuration_only=configuration_only)
    assert run.returncode == 0, run.stderr
    assert final['_polls'] >= 2
    assert not any(c[0] == "wait" for c in calls)
    if not configuration_only:
        patched = next(i for i, c in enumerate(calls) if c[0] == "patch")
        watched = next(i for i, c in enumerate(calls) if c[0] == "rollout")
        assert calls[patched + 1:watched].count(["get", "csv,deployment", "-o", "json"]) >= 2
