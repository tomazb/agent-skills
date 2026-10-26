import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_odf_health.py"


def load():
    spec = importlib.util.spec_from_file_location("rook_health_38", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status(health="HEALTH_OK"):
    return {"health": {"status": health},
            "osdmap": {"num_osds": 1, "num_up_osds": 1, "num_in_osds": 1},
            "pgmap": {"pgs_by_state": [{"state_name": "active+clean", "count": 1}]}}


def exercise(module, failure=None):
    now = [0.0]
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        assert command[:3] == ["oc", "--context", "target"]
        assert not any(x in command for x in ["archive", "patch", "delete", "set"])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if failure == "access":
            return SimpleNamespace(returncode=1, stdout="", stderr="private endpoint")
        if failure == "malformed":
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")
        if "status" in command:
            value = status("HEALTH_WARN" if failure == "health" and now[0] >= 5 else "HEALTH_OK")
        else:
            value = [{"crash_id": "existing", "archived": "earlier"}]
            if failure == "crash" and now[0] >= 5:
                value.append({"crash_id": "new", "archived": "already archived"})
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")
    def sleep(seconds):
        now[0] += seconds
    args = SimpleNamespace(context="target", namespace="openshift-storage", toolbox="rook-ceph-tools",
                           observe_seconds=10, interval_seconds=5, timeout_seconds=20)
    return module.observe(args, runner=runner, clock=lambda: now[0], sleeper=sleep), calls


def test_observes_health_over_the_entire_interval():
    result, calls = exercise(load())
    assert result["samples"] == 3
    assert result["observed_seconds"] >= 10
    assert len(calls) == 6


@pytest.mark.parametrize("failure", ["health", "crash", "malformed", "access", "timeout"])
def test_failures_never_pass_or_leak_command_output(failure):
    module = load()
    with pytest.raises(module.Failure) as error:
        exercise(module, failure)
    assert "private endpoint" not in str(error.value)


@pytest.mark.parametrize("option,value", [("--observe-seconds", "0"), ("--interval-seconds", "nan"),
                                          ("--timeout-seconds", "1")])
def test_invalid_observation_configuration_is_rejected(option, value):
    module = load()
    assert module.main(["--context", "target", option, value]) == 2


def test_operator_client_does_not_require_a_toolbox_deployment():
    module = load()
    now = [0.0]
    a = SimpleNamespace(context="target", namespace="openshift-storage", toolbox="rook-ceph-tools",
                        client="operator", observe_seconds=1, interval_seconds=1, timeout_seconds=10)
    def runner(command, **kwargs):
        assert command[:3] == ["oc", "--context", "target"]
        assert command[6:13] == ["exec", "deploy/rook-ceph-operator", "-c", "rook-ceph-operator", "--", "ceph", "-c"]
        assert command[13] == "/var/lib/rook/openshift-storage/openshift-storage.config"
        assert "deploy/rook-ceph-tools" not in command
        return SimpleNamespace(returncode=0, stdout=json.dumps(status() if "status" in command else []))
    def sleeper(seconds):
        now[0] += seconds
    assert module.observe(a, runner=runner, clock=lambda: now[0], sleeper=sleeper)["status"] == "passed"
