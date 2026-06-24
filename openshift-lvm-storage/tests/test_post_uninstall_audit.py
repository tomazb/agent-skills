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


def _run_audit(bin_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)],
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
