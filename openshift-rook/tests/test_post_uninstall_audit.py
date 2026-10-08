from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_uninstall_audit.sh"


def _run(bin_dir: Path, *, namespaces: tuple[str, ...] = (), rbac: str = "", defaults: tuple[str, ...] = (), extra_env: dict | None = None):
    oc = bin_dir / "oc"
    oc.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json, sys
            args = sys.argv[1:]
            namespaces = {list(namespaces)!r}
            rbac = {rbac!r}
            defaults = {list(defaults)!r}
            if args[:2] == ["get", "namespace"] and len(args) == 3:
                if args[2] in namespaces:
                    print(args[2])
                    raise SystemExit(0)
                print("NotFound", file=sys.stderr)
                raise SystemExit(1)
            if args[:2] == ["get", "clusterrole,clusterrolebinding"]:
                if rbac:
                    print(rbac)
                    raise SystemExit(0)
                print("No resources found")
                raise SystemExit(0)
            if args[:1] == ["api-resources"]:
                raise SystemExit(0)
            if args[:2] == ["get", "sc"] and any(a.startswith("jsonpath=") for a in args):
                for name in defaults:
                    print(name)
                raise SystemExit(0)
            if args[:2] == ["get", "sc"]:
                if any(name.startswith("rook-ceph") for name in defaults):
                    print("rook-ceph-block")
                raise SystemExit(0)
            if args[:2] == ["get", "pv,pvc"]:
                raise SystemExit(0)
            if args[:2] == ["get", "csidriver"]:
                raise SystemExit(0)
            if args[:2] == ["get", "priorityclass"]:
                print("NotFound", file=sys.stderr)
                raise SystemExit(1)
            raise SystemExit(0)
            """
        ),
        encoding="utf-8",
    )
    oc.chmod(0o755)
    env = {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_audit_flags_rook_ceph_rbac_when_neither_operator_namespace_remains(tmp_path):
    result = _run(
        tmp_path,
        rbac="rook-ceph-metrics   ClusterRole/rook-ceph-metrics",
    )

    assert result.returncode == 1
    assert "WARN: rook-ceph RBAC still exists after both Rook and ODF are gone:" in result.stdout
    assert "rook-ceph-metrics" in result.stdout


def test_audit_keeps_rook_ceph_rbac_while_odf_namespace_remains(tmp_path):
    result = _run(
        tmp_path,
        namespaces=("openshift-storage",),
        rbac="rook-ceph-metrics   ClusterRole/rook-ceph-metrics",
    )

    assert result.returncode == 0, result.stdout
    assert "OK: rook-ceph RBAC retained: a Ceph operator namespace is still present" in result.stdout


def test_audit_accepts_no_default_when_that_was_the_prior_policy(tmp_path):
    result = _run(tmp_path, extra_env={"PRIOR_DEFAULT_STORAGE_CLASS": ""})

    assert result.returncode == 0, result.stdout
    assert "OK: no default StorageClass, matching the pre-install policy" in result.stdout


def test_audit_warns_when_the_prior_default_storageclass_changed(tmp_path):
    result = _run(
        tmp_path,
        defaults=("platform-default",),
        extra_env={"PRIOR_DEFAULT_STORAGE_CLASS": "other-class"},
    )

    assert result.returncode == 1
    assert "WARN: default StorageClass is 'platform-default', pre-install policy was other-class" in result.stdout
