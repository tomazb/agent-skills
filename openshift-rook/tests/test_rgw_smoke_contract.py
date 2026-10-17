import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REFERENCE = Path(__file__).resolve().parents[1] / "references" / "rgw-object-store.md"


def test_rgw_smoke_puts_an_object_before_cleanup():
    text = REFERENCE.read_text()
    put_at = text.index("s3.put_object")
    get_at = text.index(
        's3.get_object(Bucket=b, Key="smoke-probe")["Body"].read() == b"rook-rgw-smoke-ok"'
    )
    marker_at = text.index("rook-rgw-smoke-ok")
    cleanup_at = text.index(
        "bash scripts/cleanup_smoke_namespace.sh --namespace rook-rgw-smoke --object"
    )
    assert put_at < get_at < cleanup_at
    assert marker_at < cleanup_at
    assert 'scheme = "https" if port in ("443", "8443") else "http"' in text
    assert 'ca = os.environ.get("RGW_TLS_CA", "")' in text
    assert 'ca == "service-ca"' in text
    assert 'ca == "public"' in text
    assert "verify=False" not in text
    assert "odf-object-smoke-ok" not in text
    assert "https://https://" not in text


def test_rgw_smoke_runs_a_pod_in_the_smoke_namespace_before_cleanup():
    text = REFERENCE.read_text()
    cleanup_at = text.index(
        "bash scripts/cleanup_smoke_namespace.sh --namespace rook-rgw-smoke --object"
    )
    pod_at = text.index("kind: Pod")
    assert pod_at < text.index("s3.put_object") < cleanup_at
    pod = text[pod_at:cleanup_at]
    assert "namespace: rook-rgw-smoke" in pod
    envfrom_at = pod.index("envFrom:")
    assert "name: rook-ceph-obc" in pod[envfrom_at:]
    assert "configMapRef:" in pod[envfrom_at:]
    assert "secretRef:" in pod[envfrom_at:]
    for setting in (
        "allowPrivilegeEscalation: false",
        "runAsNonRoot: true",
        'drop: ["ALL"]',
        "type: RuntimeDefault",
    ):
        assert setting in pod


@pytest.mark.parametrize(
    "claim_ref,missing,expected_status",
    [
        ("rook-rgw-smoke/rook-ceph-obc", "false", 0),
        ("", "false", 1),
        ("other-smoke/rook-ceph-obc", "false", 1),
        ("team-rook-rgw-smoke/rook-ceph-obc", "false", 1),
        ("rook-rgw-smoke/other-obc", "false", 1),
        ("", "true", 42),
    ],
)
def test_objectbucket_claim_ref_gates_the_rgw_check(
    tmp_path, claim_ref, missing, expected_status
):
    oc = tmp_path / "oc"
    oc.write_text(r"""#!/usr/bin/env python3
import json
import os
import sys
args = sys.argv[1:]
with open(os.environ["OC_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args == ["apply", "-f", "-"]:
    sys.stdin.read()
elif args == ["wait", "-n", "rook-rgw-smoke", "objectbucketclaim/rook-ceph-obc", "--for=jsonpath={.status.phase}=Bound", "--timeout=300s"]:
    pass
elif args[:2] == ["get", "objectbucket"]:
    if os.environ["OC_OBJECT_MISSING"] == "true":
        raise SystemExit(42)
    sys.stdout.write(os.environ["OC_CLAIM_REF"])
elif args[:2] == ["-n", "rook-rgw-smoke"] and args[2] == "get":
    pass
elif args[:4] == ["-n", "rook-ceph", "get", "route"]:
    sys.stdout.write("rgw.example.org")
else:
    raise SystemExit(99)
""")
    oc.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text('#!/bin/bash\nprintf "curl reached\\n" >> "$OC_LOG"\n')
    curl.chmod(0o755)
    log = tmp_path / "calls.log"
    script = next(
        block
        for block in re.findall(r"```bash\n(.*?)```", REFERENCE.read_text(), re.DOTALL)
        if "kind: ObjectBucketClaim" in block
    )
    env = dict(
        os.environ,
        PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
        OC_LOG=str(log),
        OC_CLAIM_REF=claim_ref,
        OC_OBJECT_MISSING=missing,
    )
    result = subprocess.run(
        ["bash"],
        input=script,
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert result.returncode == expected_status, result.stderr
    calls = log.read_text()
    if expected_status == 0:
        assert "curl reached" in calls
        query = [
            "get",
            "objectbucket",
            "obc-rook-rgw-smoke-rook-ceph-obc",
            "-o",
            "jsonpath={.spec.claimRef.namespace}/{.spec.claimRef.name}",
        ]
        assert json.dumps(query) in calls
        bound_wait = [
            "wait",
            "-n",
            "rook-rgw-smoke",
            "objectbucketclaim/rook-ceph-obc",
            "--for=jsonpath={.status.phase}=Bound",
            "--timeout=300s",
        ]
        assert calls.index(json.dumps(bound_wait)) < calls.index(json.dumps(query))
    else:
        assert "curl reached" not in calls
