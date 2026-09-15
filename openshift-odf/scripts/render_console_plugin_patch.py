#!/usr/bin/env python3
"""Render console.operator merge patches that enable or prune ODF plugins.

Merges against the live `spec.plugins` list so enabling `odf-console` does not
replace monitoring/networking plugins. Default `--add` is `odf-console` only;
pass `odf-client-console` explicitly when that ConsolePlugin CR exists (see
`references/console-plugin.md`).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Sole implicit default when --add is omitted. Add odf-client-console only when
# its ConsolePlugin CR exists (see references/console-plugin.md).
DEFAULT_ODF_PLUGINS = ("odf-console",)


def parse_current_plugins(raw: str) -> list[str]:
    """Parse --current-plugins from JSON or oc/kubectl jsonpath array forms.

    Accepts:
      - JSON arrays: '["a","b"]' or '[]'
      - jsonpath-ish: '[a b]', '[a,b]', or bare 'a b'
    """
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    else:
        if parsed is None:
            return []
        if isinstance(parsed, list):
            if not all(isinstance(item, str) for item in parsed):
                raise argparse.ArgumentTypeError(
                    "--current-plugins JSON array must contain only strings"
                )
            return list(parsed)
        raise argparse.ArgumentTypeError("--current-plugins must be a JSON array of strings")

    # jsonpath often prints [name1 name2] without quotes/commas
    inner = text
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1].strip()
    if not inner:
        return []
    parts = [p for p in re.split(r"[\s,]+", inner) if p]
    if not parts:
        raise argparse.ArgumentTypeError(
            f"--current-plugins is not valid JSON or jsonpath array output: {raw!r}"
        )
    return parts


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
    """CLI entry: parse current plugins and write an add or remove merge patch."""
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
        type=parse_current_plugins,
        help=(
            "Currently enabled plugins as a JSON array or oc jsonpath output "
            "(e.g. '[\"monitoring-plugin\"]' or '[monitoring-plugin networking-console-plugin]')"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--add",
        nargs="+",
        help=(
            "Plugin names to enable. When omitted, defaults to odf-console only — "
            "pass odf-client-console explicitly when that ConsolePlugin CR exists"
        ),
    )
    group.add_argument(
        "--remove",
        nargs="+",
        help="Plugin names to disable/prune from the enabled list",
    )
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()
    current = args.current_plugins

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
