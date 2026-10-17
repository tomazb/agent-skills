import json
import os
import re
import subprocess
import sys
from io import BytesIO
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml

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


@pytest.mark.parametrize(
    "selected_ca,port,expected_verify",
    [
        ("", "443", None),
        ("service-ca", "8443", "/etc/rgw-ca/service-ca.crt"),
        ("/etc/rgw-ca/ca-bundle.crt", "8443", "/etc/rgw-ca/ca-bundle.crt"),
        ("", "8080", None),
    ],
)
def test_smoke_pod_passes_selected_tls_trust_to_s3(
    tmp_path, monkeypatch, selected_ca, port, expected_verify
):
    manifest = tmp_path / "pod.yaml"
    oc = tmp_path / "oc"
    oc.write_text(r"""#!/usr/bin/env python3
import os
import sys
from pathlib import Path
args = sys.argv[1:]
if args == ["apply", "-f", "-"]:
    Path(os.environ["POD_MANIFEST"]).write_text(sys.stdin.read())
elif args == ["-n", "rook-rgw-smoke", "wait", "pod/rgw-smoke", "--for=condition=Ready", "--timeout=5m"]:
    pass
elif args == ["-n", "rook-rgw-smoke", "exec", "rgw-smoke", "--", "pip", "install", "--user", "boto3"]:
    pass
else:
    raise SystemExit(99)
""")
    oc.chmod(0o755)
    text = REFERENCE.read_text()
    pod_script = next(
        block
        for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
        if "kind: Pod" in block
    )
    env = dict(
        os.environ,
        PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
        POD_MANIFEST=str(manifest),
    )
    env.pop("RGW_TLS_CA", None)
    if selected_ca:
        env["RGW_TLS_CA"] = selected_ca
    result = subprocess.run(
        ["bash"],
        input=pod_script,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    pod = yaml.safe_load(manifest.read_text())
    container = pod["spec"]["containers"][0]
    pod_env = {entry["name"]: entry["value"] for entry in container["env"]}
    monkeypatch.delenv("RGW_TLS_CA", raising=False)
    if "RGW_TLS_CA" in pod_env:
        monkeypatch.setenv("RGW_TLS_CA", pod_env["RGW_TLS_CA"])
    for name, value in {
        "BUCKET_HOST": "rgw.example.org",
        "BUCKET_PORT": port,
        "BUCKET_NAME": "test-bucket",
        "AWS_ACCESS_KEY_ID": "FAKE_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY": "FAKE_SECRET_KEY",
    }.items():
        monkeypatch.setenv(name, value)
    requests = []
    client_args = []
    client = SimpleNamespace(
        put_object=lambda **kw: requests.append(("put", kw)),
        get_object=lambda **kw: {"Body": BytesIO(b"rook-rgw-smoke-ok")},
        delete_object=lambda **kw: requests.append(("delete", kw)),
    )

    def make_client(service, **kwargs):
        assert service == "s3"
        client_args.append(kwargs)
        return client

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=make_client))
    smoke = next(
        block
        for block in re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        if "boto3.client" in block
    )
    exec(compile(smoke, str(REFERENCE), "exec"), {})
    assert len(client_args) == 1
    kwargs = client_args[0]
    if expected_verify is None:
        assert "verify" not in kwargs
    else:
        assert kwargs["verify"] == expected_verify
        mount = next(
            m for m in container["volumeMounts"] if m["mountPath"] == "/etc/rgw-ca"
        )
        assert mount["readOnly"] is True
        volume = next(v for v in pod["spec"]["volumes"] if v["name"] == mount["name"])
        assert volume["configMap"]["name"] == "rgw-smoke-ca"
    scheme = "http" if port == "8080" else "https"
    assert kwargs["endpoint_url"] == f"{scheme}://rgw.example.org:{port}"
    assert requests[0][0] == "put" and requests[-1][0] == "delete"


@pytest.mark.parametrize("fail_wait", [False, True])
def test_service_ca_preparation_waits_for_injection(tmp_path, fail_wait):
    oc = tmp_path / "oc"
    oc.write_text(r"""#!/usr/bin/env python3
import os
import sys
from pathlib import Path
args = sys.argv[1:]
if args == ["apply", "-n", "rook-rgw-smoke", "-f", "-"]:
    Path(os.environ["CA_MANIFEST"]).write_text(sys.stdin.read())
elif args == ["wait", "-n", "rook-rgw-smoke", "configmap/rgw-smoke-ca", "--for=jsonpath={.data.service-ca\\.crt}", "--timeout=120s"]:
    Path(os.environ["WAIT_REACHED"]).touch()
    if os.environ["FAIL_WAIT"] == "true":
        raise SystemExit(42)
else:
    raise SystemExit(99)
""")
    oc.chmod(0o755)
    manifest = tmp_path / "ca.yaml"
    reached = tmp_path / "wait-reached"
    script = next(
        block
        for block in re.findall(r"```bash\n(.*?)```", REFERENCE.read_text(), re.DOTALL)
        if "export RGW_TLS_CA=service-ca" in block
    )
    env = dict(
        os.environ,
        PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
        CA_MANIFEST=str(manifest),
        WAIT_REACHED=str(reached),
        FAIL_WAIT=str(fail_wait).lower(),
    )
    result = subprocess.run(
        ["bash"],
        input=script,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == (42 if fail_wait else 0), result.stderr
    configmap = yaml.safe_load(manifest.read_text())
    assert configmap["kind"] == "ConfigMap"
    assert configmap["metadata"]["name"] == "rgw-smoke-ca"
    assert configmap["metadata"]["annotations"] == {
        "service.beta.openshift.io/inject-cabundle": "true"
    }
    assert reached.exists()
