#!/usr/bin/env python3
"""Exit 0 only when kube-apiserver is available and not rolling.

The registry ``Managed`` patch restarts the single-node API servers. Apply it
only after this check passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def api_ready(operator: dict) -> tuple[bool, str]:
    status = operator.get("status") if isinstance(operator, dict) else None
    conditions = status.get("conditions") if isinstance(status, dict) else None
    if not isinstance(conditions, list):
        return False, "clusteroperator status has no conditions"

    found: dict[str, object] = {}
    for condition in conditions:
        if isinstance(condition, dict) and isinstance(condition.get("type"), str):
            found[condition["type"]] = condition.get("status")

    available = found.get("Available")
    progressing = found.get("Progressing")
    degraded = found.get("Degraded")
    detail = f"Available={available} Progressing={progressing} Degraded={degraded}"
    ready = available == "True" and progressing == "False" and degraded == "False"
    return ready, detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    loaded = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        print("clusteroperator document is not an object", file=sys.stderr)
        return 1
    ready, detail = api_ready(loaded)
    if ready:
        print(detail)
        return 0
    print(detail, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
