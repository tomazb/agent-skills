#!/usr/bin/env python3
"""S3 SigV4 smoke client; run inside a pod with OBC credentials in its environment.

Uses only Python's standard library. Never prints credentials, endpoint, bucket,
object name, or response bodies. No server authentication settings are changed.
"""
import datetime
import hashlib
import hmac
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def roundtrip(env, opener=None):
    host = env["BUCKET_HOST"].rstrip("/")
    parsed = urllib.parse.urlsplit(host if "://" in host else "//" + host)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment or parsed.port):
        raise ValueError("invalid OBC endpoint")
    port = int(env["BUCKET_PORT"])
    if not 1 <= port <= 65535:
        raise ValueError("invalid OBC port")
    scheme = parsed.scheme or ("https" if port in (443, 8443) else "http")
    if scheme not in ("http", "https"):
        raise ValueError("invalid OBC protocol")
    if scheme == "http" and env.get("RGW_ALLOW_HTTP") != "true":
        raise ValueError("HTTP requires explicit trusted in-cluster network opt-in")
    authority = parsed.netloc + ":" + str(port)
    if opener is None:
        handlers = [urllib.request.ProxyHandler({})]
        if scheme == "https":
            ca = env.get("RGW_TLS_CA", "public")
            if ca == "service-ca":
                ca = "/etc/rgw-ca/service-ca.crt"
            if ca != "public" and not ca.startswith("/"):
                raise ValueError("invalid TLS trust source")
            context = ssl.create_default_context(cafile=None if ca == "public" else ca)
            handlers.append(urllib.request.HTTPSHandler(context=context))
        opener = urllib.request.build_opener(*handlers)
    path = "/" + urllib.parse.quote(env["BUCKET_NAME"], safe="") + "/skill-smoke-" + secrets.token_hex(16)
    payload = secrets.token_bytes(128)
    region = env.get("BUCKET_REGION") or "us-east-1"

    def request(method, data=b""):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        day = stamp[:8]
        digest = hashlib.sha256(data).hexdigest()
        # urllib otherwise adds an unsigned form Content-Type on PUT. Ceph's
        # stricter verifier rejects that header; explicitly include and sign it.
        headers = {"content-type": "application/octet-stream", "host": authority,
                   "x-amz-content-sha256": digest, "x-amz-date": stamp}
        signed = ";".join(sorted(headers))
        canonical_headers = "".join(k + ":" + headers[k] + "\n" for k in sorted(headers))
        canonical = "\n".join([method, path, "", canonical_headers, signed, digest])
        scope = day + "/" + region + "/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        key = ("AWS4" + env["AWS_SECRET_ACCESS_KEY"]).encode()
        for part in [day, region, "s3", "aws4_request"]:
            key = hmac.new(key, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = ("AWS4-HMAC-SHA256 Credential=" + env["AWS_ACCESS_KEY_ID"] + "/" + scope
                                    + ", SignedHeaders=" + signed + ", Signature=" + signature)
        req = urllib.request.Request(scheme + "://" + authority + path,
                                     data=data if method == "PUT" else None, headers=headers, method=method)
        with opener.open(req, timeout=20) as response:
            return response.read()

    # Always try DELETE, including when PUT's response is lost after committing.
    try:
        request("PUT", payload)
        if request("GET") != payload:
            raise ValueError("restored object data comparison failed")
    finally:
        request("DELETE")
    try:
        request("GET")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise ValueError("deleted object remains readable")
    return {"status": "passed", "put_get_compare_delete": True}


def main():
    try:
        print(json.dumps(roundtrip(os.environ)))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": "S3 roundtrip unverified",
                          "http_status": getattr(error, "code", None)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
