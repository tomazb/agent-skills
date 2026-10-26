#!/usr/bin/env python3
"""Fail when expandable Ceph RBD or CephFS StorageClasses omit resizer credentials.

The external-resizer authorizes ControllerExpandVolume only with
controller-expand-secret-name and controller-expand-secret-namespace. It does
not read the provisioner-secret parameters. Secret data is never printed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

EXPAND_NAME = "csi.storage.k8s.io/controller-expand-secret-name"
EXPAND_NAMESPACE = "csi.storage.k8s.io/controller-expand-secret-namespace"
VOLUME_DRIVERS = (".rbd.csi.ceph.com", ".cephfs.csi.ceph.com")
DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
DNS_SUBDOMAIN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")


class Failure(Exception):
    """The expansion-secret check could not succeed."""


def require(condition, message):
    if not condition:
        raise Failure(message)


def oc(args, context, kubeconfig):
    command = ["oc"]
    if kubeconfig:
        command.extend(["--kubeconfig", kubeconfig])
    if context:
        command.extend(["--context", context])
    command.extend(args)
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Failure("oc unavailable or timed out") from None


def class_name(item):
    require(isinstance(item, dict), "StorageClass item is not an object")
    meta = item.get("metadata")
    require(isinstance(meta, dict) and isinstance(meta.get("name"), str) and meta["name"],
            "StorageClass is missing metadata.name")
    return meta["name"]


def expandable(item):
    name = class_name(item)
    provisioner = item.get("provisioner")
    if not isinstance(provisioner, str) or not provisioner.endswith(VOLUME_DRIVERS):
        return None
    if item.get("allowVolumeExpansion") is not True:
        return None
    return name


def secret_ref(parameters, name):
    secret_name = parameters.get(EXPAND_NAME) if isinstance(parameters, dict) else None
    namespace = parameters.get(EXPAND_NAMESPACE) if isinstance(parameters, dict) else None
    if (not isinstance(secret_name, str) or not isinstance(namespace, str)
            or not secret_name.strip() or not namespace.strip()):
        raise Failure(name + " allowVolumeExpansion is true without controller-expand secret parameters")
    secret_name = secret_name.strip()
    namespace = namespace.strip()
    require(DNS_LABEL.fullmatch(namespace) is not None and len(namespace) <= 63
            and DNS_SUBDOMAIN.fullmatch(secret_name) is not None and len(secret_name) <= 253,
            name + " has an invalid controller-expand secret reference")
    return namespace, secret_name


def load_classes(stdout):
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError:
        raise Failure("unreadable StorageClass list") from None
    require(isinstance(document, dict) and isinstance(document.get("items"), list),
            "unreadable StorageClass list")
    return document["items"]


def require_user_keys(stdout, namespace, secret_name):
    label = namespace + "/" + secret_name
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError:
        raise Failure("unreadable secret " + label) from None
    require(isinstance(document, dict), "unreadable secret " + label)
    data = document.get("data")
    require(isinstance(data, dict), "secret " + label + " is missing userID or userKey")
    missing = [key for key in ("userID", "userKey")
               if not isinstance(data.get(key), str) or data.get(key) == ""]
    require(not missing, "secret " + label + " is missing " + " and ".join(missing))


def check(context, kubeconfig):
    listed = oc(["get", "sc", "-o", "json"], context, kubeconfig)
    require(listed.returncode == 0 and listed.stdout.strip(), "oc get sc failed")
    found = []
    for item in load_classes(listed.stdout):
        name = expandable(item)
        if name is None:
            continue
        namespace, secret_name = secret_ref(item.get("parameters"), name)
        found.append((name, namespace, secret_name))
    verified = set()
    for _, namespace, secret_name in found:
        if (namespace, secret_name) in verified:
            continue
        fetched = oc(["-n", namespace, "get", "secret", secret_name, "-o", "json"], context, kubeconfig)
        require(fetched.returncode == 0 and fetched.stdout.strip(),
                "cannot read secret " + namespace + "/" + secret_name)
        require_user_keys(fetched.stdout, namespace, secret_name)
        verified.add((namespace, secret_name))
    if not found:
        print("no expandable RBD or CephFS StorageClasses")
        return
    for name, namespace, secret_name in found:
        print("OK " + name + " secret " + namespace + "/" + secret_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check Ceph CSI volume-expansion secrets.")
    parser.add_argument("--context", default="")
    parser.add_argument("--kubeconfig", default="")
    args = parser.parse_args(argv)
    try:
        check(args.context, args.kubeconfig)
    except Failure as error:
        print("STOP: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
