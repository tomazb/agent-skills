#!/usr/bin/env python3
"""Read-only intent router. Metadata reset permits reuse; it is not sanitization."""
import argparse
import json
import sys

from select_erase_method import main as select_sanitization


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", choices=("reuse", "sanitize"), default="reuse")
    args, capabilities = parser.parse_known_args(argv)
    if args.intent == "sanitize":
        return select_sanitization(capabilities)
    if capabilities:
        parser.error("device sanitization capabilities require --intent sanitize")
    print(json.dumps({
        "intent": "reuse", "method": "bluestore-metadata-reset",
        "runbook": "references/maintenance-uninstall.md: rook_wipe_osd_disk",
        "sanitized": False,
        "requires": "exact-disk destructive approval, fresh unused-disk evidence, all BlueStore labels cleared, ceph-volume raw list empty",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
