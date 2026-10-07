"""Fake `oc` and `jq` for the shell-script tests.

The fake cluster is a dict of objects per resource name, the API groups it
serves, and the namespaces that exist. Scripts run with PATH holding only the
fakes, so they must not depend on any other external command.
"""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

# A deletion this old is stuck; RECENT is inside the scripts' 10-minute grace.
OLD = "2026-08-20T10:00:00Z"


def recent() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def write_jq_proxy(bin_dir: Path) -> None:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required for the shell-script tests")
    write_executable(
        bin_dir / "jq",
        f"""\
        #!/bin/sh
        exec {jq} "$@"
        """,
    )


def write_oc(bin_dir: Path, body: str) -> None:
    write_executable(
        bin_dir / "oc",
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json",
                "import sys",
                "",
                textwrap.dedent(body).strip(),
                "",
            ]
        ),
    )


def run_script(name: str, bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPTS / name), *args],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir)},
    )


# "unserved" resources fail like an unknown type; "errors" maps a resource to the
# stderr of a real failure; "noise" prints a client warning on every call, as
# client-side throttling does; "log" records every argv.
_CLUSTER_OC = """\
WORLD = json.loads(__WORLD__)
args = sys.argv[1:]
if WORLD["log"]:
    with open(WORLD["log"], "a") as fh:
        fh.write(json.dumps(args) + chr(10))
args = [a for a in args if not a.startswith(("--context=", "--kubeconfig="))]
if WORLD["noise"]:
    print("I1007 10:00:00.000000 request.go:700 Waited for 1.0s due to client-side throttling", file=sys.stderr)
if args == ["whoami"]:
    print("admin")
    raise SystemExit(0)
if args[:1] == ["api-resources"]:
    group = next((a.split("=", 1)[1] for a in args if a.startswith("--api-group=")), "")
    for name, namespaced in WORLD["groups"].get(group, []):
        if "--namespaced=true" in args and not namespaced:
            continue
        print(name)
    raise SystemExit(0)
if args[:2] == ["get", "namespace"] and len(args) == 3:
    if args[2] in WORLD["namespaces"]:
        print(args[2])
        raise SystemExit(0)
    print("NotFound", file=sys.stderr)
    raise SystemExit(1)
if args[:1] == ["get"]:
    res = args[1]
    if res in WORLD["errors"]:
        print(WORLD["errors"][res], file=sys.stderr)
        raise SystemExit(1)
    if res in WORLD["unserved"]:
        print('error: the server doesn\\'t have a resource type "%s"' % res, file=sys.stderr)
        raise SystemExit(1)
    if args[1:3] == ["console.operator.openshift.io", "cluster"]:
        print(json.dumps({"spec": {"plugins": WORLD["console_plugins"]}}))
        raise SystemExit(0)
    if args[1:3] == ["featuregate", "cluster"]:
        print(json.dumps(WORLD["featuregate"]))
        raise SystemExit(0)
    ns = args[args.index("-n") + 1] if "-n" in args else None
    items = [
        item
        for item in WORLD["objects"].get(res, [])
        if ns is None or item["metadata"].get("namespace") == ns
    ]
    if any(a.startswith("jsonpath=") for a in args):
        for item in items:
            print(item["metadata"]["name"] + chr(9) + " ".join(item["metadata"].get("finalizers", [])))
        raise SystemExit(0)
    if "-o" in args:
        print(json.dumps({"items": items}))
        raise SystemExit(0)
raise SystemExit(0)
"""

DEFAULT_SC = {
    "metadata": {
        "name": "platform-default",
        "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
    },
    "provisioner": "topolvm.io",
}


def write_cluster_oc(
    bin_dir: Path,
    objects: dict | None = None,
    groups: dict | None = None,
    namespaces: tuple = (),
    unserved: tuple = (),
    errors: dict | None = None,
    featuregate: dict | None = None,
    noise: bool = False,
    log: Path | None = None,
    console_plugins: tuple = (),
) -> None:
    world_objects = {"sc": [DEFAULT_SC]}
    for res, items in (objects or {}).items():
        world_objects[res] = world_objects.get(res, []) + items
    world = {
        "objects": world_objects,
        "groups": groups or {},
        "namespaces": list(namespaces),
        "unserved": list(unserved),
        "errors": errors or {},
        "featuregate": featuregate or {},
        "noise": noise,
        "log": str(log) if log else "",
        "console_plugins": list(console_plugins),
    }
    write_oc(bin_dir, _CLUSTER_OC.replace("__WORLD__", repr(json.dumps(world))))


def meta(name: str, namespace: str | None = None, **extra) -> dict:
    data = {"name": name, **extra}
    if namespace is not None:
        data["namespace"] = namespace
    return data


def merge(*parts: dict) -> dict:
    merged: dict = {}
    for part in parts:
        for res, items in part.items():
            merged[res] = merged.get(res, []) + items
    return merged


def rook_operator(namespace: str = "rook-ceph", labels: dict | None = None, **extra) -> dict:
    return {
        "kind": "Deployment",
        "metadata": meta("rook-ceph-operator", namespace, labels=labels or {}, **extra),
    }


def ceph_cluster(name: str, namespace: str, **extra) -> dict:
    return {"kind": "CephCluster", "metadata": meta(name, namespace, **extra)}
