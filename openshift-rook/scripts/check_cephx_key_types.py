#!/usr/bin/env python3
"""Validate a Ceph 20.2.4 auth dump before approving AES256K-only policy."""

import collections
import json
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(document):
    require(isinstance(document, dict), "unexpected audit document")
    data = document.get("data")
    require(isinstance(data, dict), "missing audit data")
    for name in ("secrets", "rotating_secrets"):
        require(isinstance(data.get(name), list) and bool(data[name]),
                "missing or empty " + name + " inventory")
    types = collections.Counter()

    def key(value, path, *, pending=False):
        require(isinstance(value, dict), path + " must be a key record")
        number, label = value.get("type"), value.get("type_str")
        require(type(number) is int and isinstance(label, str), path + " has an invalid key type")
        kind = (number, label)
        if pending and kind == (0, "none"):
            return  # Ceph explicitly represents an unused pending-key slot.
        require(kind in ((1, "aes"), (2, "aes256k")), path + " has an unknown or empty key type")
        types[label] += 1

    for index, record in enumerate(data["secrets"]):
        path = "secrets[" + str(index) + "]"
        require(isinstance(record, dict), path + " must be an auth record")
        auth = record.get("auth")
        require(isinstance(auth, dict) and "key" in auth, path + " is missing auth.key")
        require(not (set(auth) - {"key", "pending_key", "caps"}), path + " has unexpected auth fields")
        key(auth["key"], path + ".auth.key")
        if "pending_key" in auth:
            key(auth["pending_key"], path + ".auth.pending_key", pending=True)

    for index, record in enumerate(data["rotating_secrets"]):
        path = "rotating_secrets[" + str(index) + "]"
        require(isinstance(record, dict), path + " must be a rotating record")
        secrets = record.get("secrets")
        require(isinstance(secrets, dict), path + " is missing secrets")
        keys = secrets.get("keys")
        require(isinstance(keys, list) and bool(keys), path + " is missing a nonempty keys list")
        for key_index, entry in enumerate(keys):
            entry_path = path + ".secrets.keys[" + str(key_index) + "]"
            require(isinstance(entry, dict), entry_path + " must be a rotating-key record")
            expiring = entry.get("expiring_key")
            require(isinstance(expiring, dict) and "key" in expiring,
                    entry_path + " is missing expiring_key.key")
            key(expiring["key"], entry_path + ".expiring_key.key")
    return types


def main():
    try:
        types = audit(json.load(sys.stdin))
    except (ValueError, TypeError) as error:
        # Report only schema paths; never include entity IDs or credential data.
        print("STOP: " + str(error), file=sys.stderr)
        return 1
    print("Audited key types: " + json.dumps(dict(types), sort_keys=True))
    if set(types) != {"aes256k"}:
        print("STOP: all keys must report aes256k before restricting allowedCiphers", file=sys.stderr)
        return 1
    print("All audited keys use aes256k; verify client mount compatibility separately")
    return 0


if __name__ == "__main__":
    sys.exit(main())
