#!/usr/bin/env python3
"""Read-only gate for optional Rook manager integration, not the Rook operator."""
import argparse
import re
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="exact running Ceph release, e.g. 20.2.4")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        print("STOP: exact stable Ceph version required", file=sys.stderr)
        return 2
    major, minor, patch = map(int, args.version.split("."))
    if (major, minor) == (20, 2) and patch >= 3:
        print("STOP: Rook manager node_proxy_fullreport regression on 20.2.3/20.2.4; "
              "later Tentacle patches require verified upstream fix evidence. "
              "Keep only the optional rook manager module disabled; preserve Prometheus.", file=sys.stderr)
        return 1
    if major not in (19, 20) or minor != 2:
        print("STOP: manager compatibility for this release is unverified", file=sys.stderr)
        return 2
    print("No known node-proxy regression in this release; optional integration still requires release-note review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
