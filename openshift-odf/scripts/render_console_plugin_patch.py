#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_ODF_PLUGINS = ("odf-console", "odf-client-console")


def merge_console_plugins(
    current: list[str] | None,
    to_add: list[str],
) -> list[str]:
    """Return current plugins plus any missing names, preserving order."""
    if not to_add:
        raise ValueError("at least one plugin must be added")
    merged = list(current or [])
    for name in to_add:
        if name not in merged:
            merged.append(name)
    return merged


def remove_console_plugins(
    current: list[str] | None,
    to_remove: list[str],
) -> list[str]:
    """Return current plugins with named entries removed, preserving order."""
    if not to_remove:
        raise ValueError("at least one plugin must be removed")
    drop = set(to_remove)
    return [name for name in (current or []) if name not in drop]


def render_merge_patch(
    current: list[str] | None,
    to_add: list[str],
    output: str,
) -> None:
    """Write a console.operator merge patch that keeps already-enabled plugins."""
    payload = {"spec": {"plugins": merge_console_plugins(current, to_add)}}
    Path(output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def render_remove_patch(
    current: list[str] | None,
    to_remove: list[str],
    output: str,
) -> None:
    """Write a console.operator merge patch that drops named plugins only."""
    payload = {"spec": {"plugins": remove_console_plugins(current, to_remove)}}
    Path(output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render a console.operator.openshift.io merge patch that enables or "
            "disables ODF console plugins without dropping unrelated plugins in "
            "spec.plugins"
        )
    )
    parser.add_argument(
        "--current-plugins",
        default="[]",
        help='JSON array of currently enabled plugins, e.g. \'["monitoring-plugin"]\'',
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--add",
        nargs="+",
        help="Plugin names to enable (default when neither --add nor --remove)",
    )
    group.add_argument(
        "--remove",
        nargs="+",
        help="Plugin names to disable/prune from the enabled list",
    )
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()
    current = json.loads(args.current_plugins)
    if current is not None and not isinstance(current, list):
        raise ValueError("--current-plugins must be a JSON array")

    if args.remove:
        render_remove_patch(current, args.remove, args.output)
        print(f"console plugin remove patch written to {args.output}")
    else:
        to_add = args.add if args.add is not None else list(DEFAULT_ODF_PLUGINS)
        render_merge_patch(current, to_add, args.output)
        print(f"console plugin merge patch written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
