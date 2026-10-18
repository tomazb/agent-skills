"""Execute the runbook's read-only SNO operator gate against a mocked oc."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REFERENCE = Path(__file__).resolve().parents[1] / "references/validated-odf-sno.md"


@pytest.mark.parametrize(
    "csv_env,deployment_env,expected",
    [
        ([], [], 1),
        ([{"name": "SINGLE_NODE", "value": "true"}], [], 1),
        ([], [{"name": "SINGLE_NODE", "value": "true"}], 1),
        ([{"name": "SINGLE_NODE", "value": "false"}], [{"name": "SINGLE_NODE", "value": "true"}], 1),
        ([{"name": "SINGLE_NODE", "valueFrom": {}}], [{"name": "SINGLE_NODE", "value": "true"}], 1),
        ([{"name": "SINGLE_NODE", "value": "true"}] * 2, [{"name": "SINGLE_NODE", "value": "true"}], 1),
        ([{"name": "SINGLE_NODE", "value": "true"}], [{"name": "SINGLE_NODE", "value": "true"}], 0),
    ],
)
def test_sno_gate(tmp_path, csv_env, deployment_env, expected):
    run = execute(tmp_path, csv_env, deployment_env)
    assert run.returncode == expected, run.stderr
    assert ("SNO operator configuration verified" in run.stdout) == (expected == 0)


def execute(tmp_path, csv_env, deployment_env, *, fail=False, extra_csv=False):
    def pod_spec(env):
        # A sidecar comes first; the gate must inspect the named operator.
        return {"template": {"spec": {"containers": [
            {"name": "sidecar", "env": [{"name": "SINGLE_NODE", "value": "true"}]},
            {"name": "ocs-operator", "env": env},
        ]}}}

    csv = {"kind": "ClusterServiceVersion", "metadata": {"name": "ocs-operator.v4.20.19-rhodf"},
           "spec": {"install": {"spec": {"deployments": [
               {"name": "ocs-operator", "spec": pod_spec(csv_env)}]}}}}
    deployment = {"kind": "Deployment", "metadata": {"name": "ocs-operator"}, "spec": pod_spec(deployment_env)}
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"items": [csv, deployment] + ([csv] if extra_csv else [])}))
    oc = tmp_path / "oc"
    oc.write_text("""#!/usr/bin/python3
import os, sys
from pathlib import Path
assert sys.argv[1:] == ['-n', 'openshift-storage', 'get', 'csv,deployment', '-o', 'json']
if os.environ['OC_FAIL'] == 'true':
    raise SystemExit(42)
print(Path(os.environ['OC_FIXTURE']).read_text())
""")
    oc.chmod(0o755)
    blocks = re.findall(r"```bash\n(.*?)```", REFERENCE.read_text(), re.DOTALL)
    script = next(b for b in blocks if "# Read-only SNO operator gate" in b)
    return subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", script],
                          env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                               "OC_FIXTURE": str(fixture), "OC_FAIL": str(fail).lower()},
                          capture_output=True, text=True)


def test_query_failure_cannot_verify(tmp_path):
    assert execute(tmp_path, [], [], fail=True).returncode != 0


def test_ambiguous_csv_cannot_verify(tmp_path):
    env = [{"name": "SINGLE_NODE", "value": "true"}]
    assert execute(tmp_path, env, env, extra_csv=True).returncode != 0
