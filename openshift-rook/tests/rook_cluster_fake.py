"""Fake `oc` and `jq` for the shell-script tests.

The fake cluster is a dict of objects per resource name and the API groups it
serves. Scripts run with PATH holding only the fakes, so they must not depend on
any other external command.
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

# A deletion this old is stuck; recent() is inside the scripts' 10-minute grace.
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


def run_script(name: str, bin_dir: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPTS / name), *args],
        check=False,
        capture_output=True,
        text=True,
        env={**(env or {}), "PATH": str(bin_dir)},
    )


# The only jsonpath a script may send (names and finalizers, so Secret data is never
# printed); anything else fails, so a malformed expression cannot pass unnoticed.
FINALIZER_JSONPATH = 'jsonpath={range .items[*]}{.metadata.name}{"\\t"}{.metadata.finalizers[*]}{"\\n"}{end}'

SHOW_SERVER = "https://api.cluster.example.com:6443"

# "groups" maps an API group to [resource, namespaced] pairs for api-resources;
# a `get` of a resource listed in "empty" succeeds and prints nothing;
# "errors" maps a resource (or "whoami", "show-server", or "api-resources:<group>") to the stderr
# of a real failure; a `get` of a resource that has no entry in "objects" and is
# not served by any group fails like an unknown type, unless it is a core kind;
# "noise" prints a client warning (or the given text) on every call, as
# client-side throttling does; "log" records every argv. Mutating verbs only record.
_CLUSTER_OC = """\
WORLD = json.loads(__WORLD__)
args = sys.argv[1:]
if WORLD["log"]:
    with open(WORLD["log"], "a") as fh:
        fh.write(json.dumps(args) + chr(10))
args = [a for a in args if not a.startswith(("--context=", "--kubeconfig="))]
if WORLD["noise"]:
    noise = WORLD["noise"] if isinstance(WORLD["noise"], str) else (
        "I1007 10:00:00.000000 request.go:700 Waited for 1.0s due to client-side throttling")
    sys.stderr.write(noise + chr(10))
ns = None
if "-n" in args:
    i = args.index("-n")
    ns = args[i + 1]
    del args[i:i + 2]
if args[:1] == ["whoami"]:
    key = "show-server" if "--show-server" in args else "whoami"
    for k in ("whoami", key):
        if k in WORLD["errors"]:
            print(WORLD["errors"][k], file=sys.stderr)
            raise SystemExit(1)
    print(WORLD["server"] if "--show-server" in args else "admin")
    raise SystemExit(0)
if args[:1] == ["delete"]:
    # A waiting delete of an object held by a finalizer never returns while no
    # controller removes the finalizer; with "blocking_deletes" the fake fails
    # such a delete instead of hanging.
    if WORLD["blocking_deletes"] and "--wait=false" not in args:
        res = args[1]
        names = [a for a in args[2:] if not a.startswith("-")]
        held = [
            item for item in WORLD["objects"].get(res, [])
            if item["metadata"].get("finalizers") and ("--all" in args or item["metadata"]["name"] in names)
        ]
        if held:
            print("error: would block waiting for finalizers on " + res, file=sys.stderr)
            raise SystemExit(1)
    raise SystemExit(0)
if args[:1] == ["api-resources"]:
    group = next((a.split("=", 1)[1] for a in args if a.startswith("--api-group=")), "")
    key = "api-resources:" + group
    if key in WORLD["errors"]:
        print(WORLD["errors"][key], file=sys.stderr)
        raise SystemExit(1)
    for name, namespaced in WORLD["groups"].get(group, []):
        if "--namespaced=true" in args and not namespaced:
            continue
        if "--namespaced=false" in args and namespaced:
            continue
        print(name)
    raise SystemExit(0)
if args[:1] == ["create"] and "--dry-run=client" in args:
    # Client-side parse of a manifest from stdin, as oc prints it with -o json:
    # one object as itself, several as a List. A YAML error fails like oc does.
    import yaml
    try:
        docs = [d for d in yaml.safe_load_all(sys.stdin.read()) if d is not None]
    except yaml.YAMLError as exc:
        print("error: error parsing STDIN: " + str(exc).replace(chr(10), " "), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(docs[0] if len(docs) == 1 else {"apiVersion": "v1", "kind": "List", "items": docs}))
    raise SystemExit(0)
if args[:1] == ["debug"]:
    if WORLD["node"]:
        # Run the node-side script for real, with only the mocked node tools on
        # PATH: a check the mocks do not answer fails instead of reaching the host.
        import subprocess
        i = args.index("-c")
        done = subprocess.run([WORLD["node"]["bash"], *args[i:]], env={"PATH": WORLD["node"]["bin"]})
        raise SystemExit(done.returncode)
    # Otherwise "debug" is the canned stdout of every `oc debug`.
    sys.stdout.write(WORLD["debug"])
    raise SystemExit(0)
if args[:1] != ["get"]:
    raise SystemExit(0)
res = args[1]
if res in WORLD["errors"]:
    print(WORLD["errors"][res], file=sys.stderr)
    raise SystemExit(1)
if res in WORLD["empty"]:
    raise SystemExit(0)
served = {name for kinds in WORLD["groups"].values() for name, _ in kinds}
if res not in WORLD["objects"] and res not in served and res not in WORLD["core"]:
    print('error: the server doesn\\'t have a resource type "%s"' % res, file=sys.stderr)
    raise SystemExit(1)
output = None
selector = ""
labels = {}
names = []
rest = args[2:]
i = 0
while i < len(rest):
    a = rest[i]
    if a == "-o":
        output = rest[i + 1]
        i += 2
        continue
    if a.startswith("-o"):
        output = a[2:]
    elif a == "--field-selector":
        selector = rest[i + 1]
        i += 2
        continue
    elif a.startswith("--field-selector="):
        selector = a.split("=", 1)[1]
    elif a in ("-l", "--selector"):
        labels = dict(pair.split("=", 1) for pair in rest[i + 1].split(","))
        i += 2
        continue
    elif not a.startswith("-"):
        names.append(a)
    i += 1
if output and output.startswith("jsonpath="):
    if output != WORLD["finalizer_jsonpath"]:
        print("error: unexpected " + output, file=sys.stderr)
        raise SystemExit(1)
# Like oc: -A reads every namespace; without -n a namespaced get reads the
# current namespace ("default" here); a cluster-scoped object has no namespace.
scope = None if "-A" in args else (ns or "default")
items = [
    item
    for item in WORLD["objects"].get(res, [])
    if (scope is None or item["metadata"].get("namespace", scope) == scope)
    and (not selector.startswith("metadata.name=") or item["metadata"]["name"] == selector.split("=", 1)[1])
    and (not names or item["metadata"]["name"] in names)
    and all((item["metadata"].get("labels") or {}).get(k) == v for k, v in labels.items())
]
if names and not items:
    if "--ignore-not-found" in args:
        raise SystemExit(0)
    print('Error from server (NotFound): %s "%s" not found' % (res, names[0]), file=sys.stderr)
    raise SystemExit(1)
if output is None:
    for item in items:
        print(item["metadata"]["name"])
elif output == "name":
    for item in items:
        print(res + "/" + item["metadata"]["name"])
elif output.startswith("jsonpath="):
    for item in items:
        print(item["metadata"]["name"] + chr(9) + " ".join(item["metadata"].get("finalizers", [])))
elif names and len(names) == 1:
    print(json.dumps(items[0]))
else:
    print(json.dumps({"items": items}))
raise SystemExit(0)
"""

DEFAULT_SC = {
    "metadata": {
        "name": "platform-default",
        "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
    },
    "provisioner": "topolvm.io",
}

# Kinds every OpenShift cluster serves; a get of one of them with no objects
# returns an empty list instead of failing like an unknown type.
CORE_KINDS = (
    "namespaces", "pods", "pvc", "pv", "sc", "csidrivers", "csinodes", "volumeattachments",
    "deployments", "daemonsets", "statefulsets", "services", "serviceaccounts", "configmaps",
    "secrets", "roles", "rolebindings", "clusterroles", "clusterrolebindings",
    "poddisruptionbudgets", "jobs", "cronjobs", "priorityclasses", "scc", "machineconfigs",
    "subscriptions.operators.coreos.com", "clusterserviceversions.operators.coreos.com", "crd",
    "validatingwebhookconfigurations", "mutatingwebhookconfigurations", "apiservices",
)

# Core kinds that live in a namespace. A fixture of one of them without a namespace
# would leak into every scope, so write_cluster_oc rejects it.
NAMESPACED_CORE_KINDS = (
    "pods", "pvc", "deployments", "daemonsets", "statefulsets", "services", "serviceaccounts",
    "configmaps", "secrets", "roles", "rolebindings", "poddisruptionbudgets", "jobs", "cronjobs",
    "subscriptions.operators.coreos.com", "clusterserviceversions.operators.coreos.com",
)


def write_cluster_oc(
    bin_dir: Path,
    objects: dict | None = None,
    groups: dict | None = None,
    errors: dict | None = None,
    noise: bool | str = False,
    log: Path | None = None,
    blocking_deletes: bool = False,
    core: tuple = CORE_KINDS,
    empty: tuple = (),
    debug: str = "",
    default_sc: bool = True,
    node: dict | None = None,
) -> None:
    namespaced = set(NAMESPACED_CORE_KINDS) | {
        name for kinds in (groups or {}).values() for name, is_namespaced in kinds if is_namespaced
    }
    for res, items in (objects or {}).items():
        for item in items:
            if res in namespaced and "namespace" not in item["metadata"]:
                raise ValueError(f"fixture {res}/{item['metadata']['name']} needs a namespace")
    world_objects = dict(objects or {})
    world_objects["sc"] = ([DEFAULT_SC] if default_sc else []) + world_objects.get("sc", [])
    world = {
        "objects": world_objects,
        "groups": groups or {},
        "errors": errors or {},
        "noise": noise,
        "log": str(log) if log else "",
        "finalizer_jsonpath": FINALIZER_JSONPATH,
        "server": SHOW_SERVER,
        "blocking_deletes": blocking_deletes,
        "core": list(core),
        "empty": list(empty),
        "debug": debug,
        "node": write_node_tools(bin_dir / "node-bin", node) if node is not None else None,
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


# Node tools for `oc debug node/... -- chroot /host bash -c SCRIPT`. Every call is
# appended to <dir>/calls.log as a JSON argv. "fail" maps a tool to the exit status
# it fails with; "absent" lists tools that are not installed.
NODE_FACTS = {
    "device": "/dev/sdb",
    "type": "disk",
    "majmin": " 8:16",
    "names": "sdb",
    "holders": "",
    "signatures": "",
    "mounts": "8:0\n259:1",
    "swaps": "",
    "pvs": "  /dev/sda3",
    # blkid -p -o export output; blkid exits 2 when it prints nothing, unless
    # "blkid_rc" says otherwise.
    "blkid": "",
    "blkid_rc": None,
    # blockdev --getsize64 output, in bytes.
    "size": "1000204886016",
    "fail": {},
    "absent": [],
}

_NODE_TOOL = """#!__PYTHON__
import json, os, sys
F = json.loads(__FACTS__)
cmd = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(F["log"], "a") as fh:
    fh.write(json.dumps([cmd, *args]) + chr(10))
# "wipefs -af" fails only the destructive wipefs, not its read-only probe.
key = "wipefs -af" if cmd == "wipefs" and "-af" in args and "wipefs -af" in F["fail"] else cmd
if key in F["fail"]:
    print(cmd + ": simulated failure", file=sys.stderr)
    raise SystemExit(F["fail"][key])
def out(value):
    if value:
        print(value)
if cmd == "readlink":
    out(F["device"])
elif cmd == "lsblk":
    if "-f" in args:
        out("NAME FSTYPE")
    elif "-nro" in args:
        out(F["names"])
    else:
        out({"TYPE": F["type"], "MAJ:MIN": F["majmin"]}[args[args.index("-dno") + 1]])
elif cmd == "ls":
    out(F["holders"])
elif cmd == "wipefs":
    if "-af" not in args:
        out(F["signatures"])
elif cmd == "findmnt":
    out(F["mounts"])
elif cmd == "swapon":
    out(F["swaps"])
elif cmd == "pvs":
    out(F["pvs"])
elif cmd == "blkid":
    out(F["blkid"])
    rc = F["blkid_rc"]
    raise SystemExit((0 if F["blkid"] else 2) if rc is None else rc)
elif cmd == "blockdev":
    out(F["size"])
"""

NODE_TOOLS = ("readlink", "blockdev", "dd", "lsblk", "ls", "wipefs", "blkid", "findmnt", "swapon", "pvs", "sgdisk")


def write_node_tools(directory: Path, overrides: dict) -> dict:
    import shutil

    directory.mkdir()
    facts = {**NODE_FACTS, **overrides, "log": str(directory / "calls.log")}
    body = _NODE_TOOL.replace("__PYTHON__", sys.executable).replace("__FACTS__", repr(json.dumps(facts)))
    for tool in NODE_TOOLS:
        if tool in facts["absent"]:
            continue
        path = directory / tool
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    return {"bin": str(directory), "bash": shutil.which("bash") or "/bin/bash"}


def node_calls(bin_dir: Path) -> list:
    log = bin_dir / "node-bin" / "calls.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
