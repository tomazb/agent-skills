#!/usr/bin/env python3
"""Decide whether a registry smoke push and pull succeeded.

Filesystem size is not an input. A repeated push of a content-addressed blob
can leave ``du`` unchanged and still be a successful upload. An image import
that never ran this push does not satisfy the check.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PUSH_MARKER = "registry-push-ok"
PULL_MARKER = "registry-smoke-ok"


def smoke_passed(push_log: str, pull_log: str, pull_marker: str = PULL_MARKER) -> bool:
    if not isinstance(push_log, str) or not isinstance(pull_log, str):
        return False
    pushed = any(line.strip() == PUSH_MARKER for line in push_log.splitlines())
    pulled = pull_log.strip() == pull_marker
    return pushed and pulled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push-log", required=True, type=Path)
    parser.add_argument("--pull-log", required=True, type=Path)
    parser.add_argument("--pull-marker", default=PULL_MARKER)
    args = parser.parse_args(argv)
    push_log = args.push_log.read_text(encoding="utf-8", errors="replace")
    pull_log = args.pull_log.read_text(encoding="utf-8", errors="replace")
    if smoke_passed(push_log, pull_log, args.pull_marker):
        print("registry smoke passed")
        return 0
    if not any(line.strip() == PUSH_MARKER for line in push_log.splitlines()):
        print("push log is missing registry-push-ok", file=sys.stderr)
    if pull_log.strip() != args.pull_marker:
        print("pull log does not match the smoke marker", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
