from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from render_console_plugin_patch import (
    merge_console_plugins,
    parse_current_plugins,
    render_merge_patch,
)


def test_parse_current_plugins_accepts_json_and_jsonpath_forms():
    assert parse_current_plugins("[]") == []
    assert parse_current_plugins('["monitoring-plugin","networking-console-plugin"]') == [
        "monitoring-plugin",
        "networking-console-plugin",
    ]
    assert parse_current_plugins("[monitoring-plugin networking-console-plugin]") == [
        "monitoring-plugin",
        "networking-console-plugin",
    ]
    assert parse_current_plugins("[monitoring-plugin,networking-console-plugin]") == [
        "monitoring-plugin",
        "networking-console-plugin",
    ]
    assert parse_current_plugins("monitoring-plugin networking-console-plugin") == [
        "monitoring-plugin",
        "networking-console-plugin",
    ]


def test_parse_current_plugins_rejects_non_string_json_array():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        parse_current_plugins("[1, 2]")


def test_merge_preserves_existing_plugins_and_appends_new():
    merged = merge_console_plugins(
        ["monitoring-plugin", "networking-console-plugin"],
        ["odf-console", "odf-client-console"],
    )
    assert merged == [
        "monitoring-plugin",
        "networking-console-plugin",
        "odf-console",
        "odf-client-console",
    ]


def test_merge_is_idempotent_when_odf_plugins_already_present():
    current = [
        "monitoring-plugin",
        "odf-console",
        "odf-client-console",
        "networking-console-plugin",
    ]
    assert merge_console_plugins(current, ["odf-console", "odf-client-console"]) == current


def test_merge_treats_missing_current_list_as_empty():
    assert merge_console_plugins(None, ["odf-console"]) == ["odf-console"]
    assert merge_console_plugins([], ["odf-console"]) == ["odf-console"]


def test_merge_rejects_empty_add_list():
    with pytest.raises(ValueError, match="at least one plugin"):
        merge_console_plugins(["monitoring-plugin"], [])


def test_render_merge_patch_writes_full_observed_list(tmp_path: Path):
    output = tmp_path / "console-plugins.patch.json"
    render_merge_patch(
        ["monitoring-plugin"],
        ["odf-console", "odf-client-console"],
        str(output),
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "spec": {
            "plugins": [
                "monitoring-plugin",
                "odf-console",
                "odf-client-console",
            ]
        }
    }
    # A payload of only odf-console would disable monitoring.
    assert "monitoring-plugin" in payload["spec"]["plugins"]


def test_remove_drops_odf_plugins_and_preserves_others():
    from render_console_plugin_patch import remove_console_plugins

    remaining = remove_console_plugins(
        [
            "monitoring-plugin",
            "odf-console",
            "networking-console-plugin",
            "odf-client-console",
        ],
        ["odf-console", "odf-client-console"],
    )
    assert remaining == ["monitoring-plugin", "networking-console-plugin"]


def test_remove_is_idempotent_when_odf_plugins_absent():
    from render_console_plugin_patch import remove_console_plugins

    current = ["monitoring-plugin", "networking-console-plugin"]
    assert remove_console_plugins(current, ["odf-console", "odf-client-console"]) == current


def test_render_remove_patch_writes_remaining_list(tmp_path: Path):
    from render_console_plugin_patch import render_remove_patch

    output = tmp_path / "console-plugins-remove.patch.json"
    render_remove_patch(
        ["monitoring-plugin", "odf-console", "odf-client-console"],
        ["odf-console", "odf-client-console"],
        str(output),
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {"spec": {"plugins": ["monitoring-plugin"]}}


def test_cli_default_add_is_odf_console_only(tmp_path: Path, monkeypatch):
    from render_console_plugin_patch import main

    output = tmp_path / "default.patch.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "render_console_plugin_patch.py",
            "--current-plugins",
            '["monitoring-plugin"]',
            "--output",
            str(output),
        ],
    )
    assert main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["spec"]["plugins"] == ["monitoring-plugin", "odf-console"]
    assert "odf-client-console" not in payload["spec"]["plugins"]
