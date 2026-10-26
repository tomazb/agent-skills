import datetime
import hashlib
import hmac
import importlib.util
import io
from pathlib import Path
import urllib.error

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rgw_s3_roundtrip.py"


def load():
    spec = importlib.util.spec_from_file_location("rgw_client_38", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENV = {"BUCKET_HOST": "rgw.example.test", "BUCKET_PORT": "8080", "BUCKET_NAME": "fake-smoke",
       "AWS_ACCESS_KEY_ID": "FAKE_ACCESS_FOR_TEST", "AWS_SECRET_ACCESS_KEY": "FAKE_SECRET_FOR_TEST",
       "RGW_ALLOW_HTTP": "true"}


class Gateway:
    def __init__(self, corrupt=False):
        self.objects = {}
        self.methods = []
        self.corrupt = corrupt

    def open(self, request, timeout):
        self.methods.append(request.method)
        headers = {k.lower(): v for k, v in request.header_items()}
        auth = headers["authorization"]
        signed = auth.split("SignedHeaders=", 1)[1].split(",", 1)[0]
        assert "content-type" in signed.split(";")
        assert {"host", "x-amz-date", "x-amz-content-sha256"} <= set(signed.split(";"))
        canonical = request.method + "\n" + request.selector + "\n\n"
        canonical += "".join(k + ":" + headers[k] + "\n" for k in signed.split(";"))
        canonical += "\n" + signed + "\n" + hashlib.sha256(request.data or b"").hexdigest()
        date = headers["x-amz-date"]
        scope = date[:8] + "/us-east-1/s3/aws4_request"
        to_sign = "AWS4-HMAC-SHA256\n" + date + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()
        key = ("AWS4" + ENV["AWS_SECRET_ACCESS_KEY"]).encode()
        for part in [date[:8], "us-east-1", "s3", "aws4_request"]:
            key = hmac.new(key, part.encode(), hashlib.sha256).digest()
        assert auth.endswith(hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest())
        if request.method == "PUT":
            self.objects[request.selector] = request.data
        elif request.method == "DELETE":
            self.objects.pop(request.selector, None)
        elif request.method == "GET":
            if request.selector not in self.objects:
                raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)
            return io.BytesIO(b"wrong bytes" if self.corrupt else self.objects[request.selector])
        return io.BytesIO(b"")


def test_roundtrip_signs_all_required_headers_and_deletes_the_object():
    gateway = Gateway()
    assert load().roundtrip(ENV, opener=gateway)["status"] == "passed"
    assert gateway.methods == ["PUT", "GET", "DELETE", "GET"]
    assert gateway.objects == {}


def test_byte_mismatch_fails_and_still_deletes_the_test_object():
    gateway = Gateway(corrupt=True)
    with pytest.raises(ValueError, match="data comparison"):
        load().roundtrip(ENV, opener=gateway)
    assert gateway.objects == {}
    assert gateway.methods[-1] == "DELETE"


def test_http_requires_explicit_trusted_network_opt_in():
    env = {**ENV, "RGW_ALLOW_HTTP": "false"}
    gateway = Gateway()
    with pytest.raises(ValueError, match="trusted"):
        load().roundtrip(env, opener=gateway)
    assert gateway.methods == []
