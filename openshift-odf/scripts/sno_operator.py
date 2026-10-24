#!/usr/bin/env python3
"""Check or configure the OCS operator SNO flag through its installed CSV."""

import argparse
import json
import subprocess
import sys
import time

NAMESPACE = "openshift-storage"
OPERATOR = "ocs-operator"
FLAG = {"name": "SINGLE_NODE", "value": "true"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def oc(*args, timeout=200):
    return subprocess.run(["oc", "-n", NAMESPACE, *args], check=True,
                          capture_output=True, text=True, timeout=timeout).stdout


def named(items, name, description):
    require(isinstance(items, list), "Invalid " + description + " list")
    matches = [(i, item) for i, item in enumerate(items) if item.get("name") == name]
    require(len(matches) == 1, "Expected exactly one named " + description)
    return matches[0]


def operator_container(spec):
    return named(spec["template"]["spec"]["containers"], OPERATOR, "operator container")


def environment(container):
    env = container.get("env", [])
    require(isinstance(env, list) and all(isinstance(e, dict) for e in env), "Invalid operator env array")
    return env


def correct(container):
    return [e for e in environment(container) if e.get("name") == "SINGLE_NODE"] == [FLAG]


def load(timeout=200):
    items = json.loads(oc("get", "csv,deployment", "-o", "json", timeout=timeout))["items"]
    csvs = [x for x in items if x.get("kind") == "ClusterServiceVersion"
            and x["metadata"]["name"].startswith("ocs-operator.")]
    deployments = [x for x in items if x.get("kind") == "Deployment" and x["metadata"]["name"] == OPERATOR]
    require(len(csvs) == 1 and len(deployments) == 1, "Expected exactly one OCS CSV and Deployment")
    csv = csvs[0]
    di, template = named(csv["spec"]["install"]["spec"]["deployments"], OPERATOR, "operator deployment template")
    ci, container = operator_container(template["spec"])
    operator_container(deployments[0]["spec"])
    return csv, deployments[0], di, ci, container


def check_topology():
    topology = json.loads(oc("get", "infrastructure", "cluster", "-o", "json"))["status"].get("controlPlaneTopology")
    require(topology == "SingleReplica", "SNO operator procedure requires confirmed SingleReplica topology")


def desired_configuration():
    csv, deployment, _, _, container = load()
    require(correct(container), "CSV SINGLE_NODE is missing or invalid")
    require(correct(operator_container(deployment["spec"])[1]), "Deployment SINGLE_NODE is missing or invalid")
    return csv, deployment


def verify():
    csv, _ = desired_configuration()
    oc("rollout", "status", "deploy/ocs-operator", "--timeout=3m")
    # Re-read after the watch; rollout success must describe the current generation.
    latest_csv, deployment, _, _, latest_container = load()
    require(latest_csv["metadata"]["uid"] == csv["metadata"]["uid"] and correct(latest_container),
            "OCS CSV changed during verification")
    require(correct(operator_container(deployment["spec"])[1]), "Deployment flag changed during verification")
    desired = deployment["spec"].get("replicas", 1)
    status = deployment.get("status", {})
    require(type(desired) is int and desired > 0, "Operator has no desired replicas")
    require(status.get("observedGeneration") == deployment["metadata"]["generation"], "Operator generation not observed")
    require(all(status.get(k) == desired for k in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"))
            and status.get("unavailableReplicas", 0) == 0, "Operator rollout is incomplete")
    runtime = oc("exec", "deploy/ocs-operator", "-c", OPERATOR, "--", "printenv", "SINGLE_NODE")
    require(runtime in ("true", "true\n"), "Running operator SINGLE_NODE is not literal true")
    print("SNO operator configuration verified in CSV, current Deployment, and running operator container")
    print("Check StorageCluster reconciliation conditions separately")


def wait_for_propagation(csv_uid, timeout):
    """Poll named templates without requiring filtered oc-wait support."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = max(0, deadline - time.monotonic())
        csv, deployment, _, _, container = load(timeout=max(1, min(30, remaining)))
        require(csv["metadata"]["uid"] == csv_uid and correct(container), "OCS CSV changed during propagation")
        if correct(operator_container(deployment["spec"])[1]):
            return
        remaining = deadline - time.monotonic()
        require(remaining > 0, "OLM did not propagate SINGLE_NODE to the Deployment before timeout")
        time.sleep(min(5, remaining))


def configure(configuration_only=False, propagation_timeout=180):
    csv, _, di, ci, container = load()
    env = environment(container)
    if not correct(container):
        path = "/spec/install/spec/deployments/" + str(di) + "/spec/template/spec/containers/" + str(ci) + "/env"
        patch = [{"op": "test", "path": "/metadata/resourceVersion", "value": csv["metadata"]["resourceVersion"]}]
        indices = [i for i, entry in enumerate(env) if entry.get("name") == "SINGLE_NODE"]
        if "env" not in container:
            patch.append({"op": "add", "path": path, "value": [FLAG]})
        elif not indices:
            patch.append({"op": "add", "path": path + "/-", "value": FLAG})
        else:
            for index in reversed(indices[1:]):
                patch.append({"op": "remove", "path": path + "/" + str(index)})
            patch.append({"op": "replace", "path": path + "/" + str(indices[0]), "value": FLAG})
        oc("patch", "csv", csv["metadata"]["name"], "--type=json", "-p", json.dumps(patch))
    # CSV reconciliation is asynchronous; wait for OLM to update the desired Pod
    # template before checking its rollout. A healthy old Deployment is insufficient.
    wait_for_propagation(csv["metadata"]["uid"], propagation_timeout)
    if configuration_only:
        desired_configuration()
        print("Desired CSV/Deployment configuration verified; run check after the operator starts")
    else:
        verify()  # No-op and patched paths both require rollout and runtime verification.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "configure"))
    parser.add_argument("--configuration-only", action="store_true",
                        help="Configure desired templates before a StorageCluster exists; does not verify runtime")
    parser.add_argument("--propagation-timeout", type=int, default=180,
                        help="Seconds to poll OLM template propagation (default: 180; 0 checks once)")
    args = parser.parse_args()
    if args.configuration_only and args.action != "configure":
        parser.error("--configuration-only requires configure")
    if args.propagation_timeout < 0:
        parser.error("--propagation-timeout must be nonnegative")
    try:
        check_topology()
        if args.action == "configure":
            configure(args.configuration_only, args.propagation_timeout)
        else:
            verify()
    except subprocess.CalledProcessError as error:
        print("STOP: oc command failed (exit " + str(error.returncode) + ")", file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.TimeoutExpired) as error:
        # CLI output can carry endpoint identities; report only our structural errors.
        message = str(error) if isinstance(error, ValueError) else "invalid or unavailable operator state"
        print("STOP: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
