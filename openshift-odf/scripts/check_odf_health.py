#!/usr/bin/env python3
"""Observe Ceph health and crash inventory without changing cluster state."""
import argparse
import json
import math
import re
import subprocess
import sys
import time


class Failure(Exception):
    pass


def observe(args, runner=subprocess.run, clock=time.monotonic, sleeper=time.sleep):
    started = clock()
    deadline = started + args.timeout_seconds
    baseline = None
    samples = 0

    def query(*command):
        remaining = deadline - clock()
        if remaining <= 0:
            raise Failure("health observation timed out")
        argv = ["oc", "--context", args.context, "--request-timeout=5s", "-n", args.namespace]
        if getattr(args, "client", "toolbox") == "operator":
            argv += ["exec", "deploy/rook-ceph-operator", "-c", "rook-ceph-operator", "--", "ceph",
                     "-c", "/var/lib/rook/" + args.namespace + "/" + args.namespace + ".config"]
        else:
            argv += ["exec", "deploy/" + args.toolbox, "--", "ceph"]
        argv += [*command, "--format=json"]
        try:
            result = runner(argv, capture_output=True, text=True, timeout=min(10, remaining), check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise Failure("health query unavailable or timed out") from None
        if result.returncode:
            raise Failure("health query failed; access or API result unverified")
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise Failure("malformed health query response") from None

    while True:
        try:
            status = query("status")
            if status["health"]["status"] != "HEALTH_OK":
                raise Failure("Ceph is not HEALTH_OK")
            osds = status["osdmap"]
            if not (osds["num_osds"] > 0 and osds["num_osds"] == osds["num_up_osds"] == osds["num_in_osds"]):
                raise Failure("OSDs are not all up and in")
            states = status["pgmap"]["pgs_by_state"]
            if not states or not all(x["state_name"] == "active+clean" and x["count"] > 0 for x in states):
                raise Failure("PGs are not all active+clean")
            crashes = query("crash", "ls")
            if not isinstance(crashes, list) or not all(isinstance(x.get("crash_id"), str) and x["crash_id"] for x in crashes):
                raise Failure("crash inventory unverified")
            identifiers = {x["crash_id"] for x in crashes}
        except (KeyError, TypeError, AttributeError):
            raise Failure("health/crash response missing required fields") from None
        if baseline is None:
            baseline = identifiers
        elif identifiers - baseline:
            raise Failure("new Ceph crash records observed, including archived records")
        samples += 1
        elapsed = clock() - started
        if elapsed >= args.observe_seconds:
            return {"status": "passed", "health": "HEALTH_OK", "samples": samples,
                    "observed_seconds": round(elapsed, 2), "new_crash_records": 0}
        remaining = deadline - clock()
        if remaining <= 0:
            raise Failure("health observation timed out")
        sleeper(min(args.interval_seconds, args.observe_seconds - elapsed, remaining))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", default="openshift-storage")
    parser.add_argument("--toolbox", default="rook-ceph-tools")
    parser.add_argument("--client", choices=("toolbox", "operator"), default="toolbox",
                        help="existing Ceph client; operator uses its read-only cluster config")
    parser.add_argument("--observe-seconds", type=float, default=120)
    parser.add_argument("--interval-seconds", type=float, default=15)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    args = parser.parse_args(argv)
    durations = (args.observe_seconds, args.interval_seconds, args.timeout_seconds)
    label = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    if (not args.context.strip() or not all(math.isfinite(x) and x > 0 for x in durations)
            or args.timeout_seconds <= args.observe_seconds
            or not re.fullmatch(label, args.namespace) or not re.fullmatch(label, args.toolbox)
            or args.namespace != "openshift-storage"):
        print("STOP: invalid target or observation durations; timeout must exceed observation", file=sys.stderr)
        return 2
    try:
        print(json.dumps(observe(args)))
        return 0
    except Failure as error:
        print("STOP: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
