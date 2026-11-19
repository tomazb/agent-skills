from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_uninstall_audit.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_jq_proxy(bin_dir: Path) -> None:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required for post_uninstall_audit.sh tests")
    _write_executable(
        bin_dir / "jq",
        f"""\
        #!/bin/sh
        exec {jq} "$@"
        """,
    )


def _write_oc(bin_dir: Path, body: str) -> None:
    _write_executable(
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


def _run_audit(bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir)},
    )


def test_audit_fails_when_oc_is_missing(tmp_path):
    _write_jq_proxy(tmp_path)

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: oc CLI is required" in result.stdout
    assert "OK: no topolvm.io API resources found" not in result.stdout


def test_audit_reports_api_resource_query_failures(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args[:1] == ["api-resources"]:
            print("forbidden", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: topolvm.io API resource discovery failed" in result.stdout
    assert "OK: no topolvm.io API resources found" not in result.stdout


def test_audit_checks_lvms_api_group(tmp_path):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args[:1] == ["api-resources"]:
            group = next((arg.split("=", 1)[1] for arg in args if arg.startswith("--api-group=")), "")
            if group == "lvm.topolvm.io":
                print("lvmclusters.lvm.topolvm.io")
            raise SystemExit(0)
        if args[:2] == ["get", "csidriver"] or args[:2] == ["get", "namespace"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:1] == ["get"] and "-o" in args and "json" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 0
    assert "WARN: lvm.topolvm.io API resources still exist:" in result.stdout
    assert "lvmclusters.lvm.topolvm.io" in result.stdout


@pytest.mark.parametrize(
    ("args", "namespace"),
    [((), "openshift-lvm-storage"), (("--namespace", "custom-lvms"), "custom-lvms")],
)
def test_audit_checks_workloads_in_lvms_namespace(tmp_path, args, namespace):
    _write_jq_proxy(tmp_path)
    _write_oc(
        tmp_path,
        f"""\
        args = sys.argv[1:]
        if args == ["get", "namespace", {namespace!r}]:
            print({namespace!r})
        elif args[:2] in (["get", "csidriver"], ["get", "namespace"]):
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        elif args == ["-n", {namespace!r}, "get", "all"]:
            print("daemonset.apps/vg-manager")
        elif args[:1] == ["get"] and "json" in args:
            print(json.dumps({{"items": []}}))
        """,
    )

    result = _run_audit(tmp_path, *args)

    assert result.returncode == 0
    assert f"WARN: {namespace} namespace still exists" in result.stdout
    assert "daemonset.apps/vg-manager" in result.stdout


def test_audit_reports_jq_failures_without_false_ok(tmp_path):
    _write_executable(
        tmp_path / "jq",
        """\
        #!/bin/sh
        echo "jq failed" >&2
        exit 2
        """,
    )
    _write_oc(
        tmp_path,
        """\
        args = sys.argv[1:]
        if args == ["whoami"]:
            print("admin")
            raise SystemExit(0)
        if args[:1] == ["api-resources"]:
            raise SystemExit(0)
        if args[:2] == ["get", "csidriver"] or args[:2] == ["get", "namespace"]:
            print("NotFound", file=sys.stderr)
            raise SystemExit(1)
        if args[:1] == ["get"] and "-o" in args and "json" in args:
            print(json.dumps({"items": []}))
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )

    result = _run_audit(tmp_path)

    assert result.returncode == 1
    assert "FAIL: TopoLVM StorageClasses jq filter failed" in result.stdout
    assert "OK: no TopoLVM StorageClasses found" not in result.stdout
