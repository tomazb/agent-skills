from __future__ import annotations

import io
import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "query_versions.py"
SPEC = importlib.util.spec_from_file_location("query_versions", MODULE_PATH)
query_versions = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(query_versions)


def run_main(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> SystemExit:
    monkeypatch.setattr(sys, "argv", ["query_versions.py", *args])
    with pytest.raises(SystemExit) as exc_info:
        query_versions.main()
    return exc_info.value


def test_version_key_sorts_semver_values() -> None:
    versions = ["4.18.30", "4.18.0", "4.19.1", "4.18.2"]

    assert sorted(versions, key=query_versions.version_key) == [
        "4.18.0",
        "4.18.2",
        "4.18.30",
        "4.19.1",
    ]


def test_build_search_query_skips_none_filters() -> None:
    result = query_versions.build_search_query(
        enabled=True,
        rosa_enabled=None,
        hcp_enabled=False,
        channel_group="stable",
        version_pattern="4.18",
    )

    assert result == (
        "enabled = 'true' and hosted_control_plane_enabled = 'false' "
        "and channel_group = 'stable' and raw_id like '4.18%'"
    )


def test_discover_active_minors_stops_after_three_empty_channels() -> None:
    calls: list[str] = []

    def fake_fetcher(channel: str, arch: str) -> dict:
        calls.append(channel)
        if channel == "stable-4.12":
            return {"nodes": [{"version": "4.12.9"}, {"version": "4.12.10"}]}
        return {"nodes": []}

    results = query_versions.discover_active_minors(
        floor_minor=12,
        ceiling_minor=20,
        graph_fetcher=fake_fetcher,
    )

    assert [item["latest"] for item in results] == ["4.12.10"]
    assert calls == ["stable-4.12", "stable-4.13", "stable-4.14", "stable-4.15"]


def test_discover_active_minors_connection_errors_do_not_count_as_empty() -> None:
    calls: list[str] = []

    def fake_fetcher(channel: str, arch: str) -> dict:
        calls.append(channel)
        if channel == "stable-4.12":
            return {"nodes": [{"version": "4.12.9"}]}
        if channel == "stable-4.13":
            raise RuntimeError("Connection error: timed out")
        return {"nodes": []}

    results = query_versions.discover_active_minors(
        floor_minor=12,
        ceiling_minor=20,
        graph_fetcher=fake_fetcher,
    )

    assert [item["latest"] for item in results] == ["4.12.9"]
    assert calls == [
        "stable-4.12",
        "stable-4.13",
        "stable-4.14",
        "stable-4.15",
        "stable-4.16",
    ]


def test_discover_active_minors_raises_when_all_probes_fail_with_connection_errors() -> None:
    def fake_fetcher(channel: str, arch: str) -> dict:
        raise RuntimeError("Connection error: timed out")

    with pytest.raises(RuntimeError, match="Cannot reach api.openshift.com"):
        query_versions.discover_active_minors(
            floor_minor=12,
            ceiling_minor=14,
            graph_fetcher=fake_fetcher,
        )


def test_get_upgrade_targets_ignores_malformed_edges() -> None:
    def fake_fetcher(channel: str, arch: str) -> dict:
        return {
            "nodes": [{"version": "4.18.0"}, {"version": "4.18.1"}],
            "edges": [[0, 1], [0, 999], [0]],
        }

    targets = query_versions.get_upgrade_targets(
        "stable-4.18",
        "4.18.0",
        graph_fetcher=fake_fetcher,
    )

    assert targets == ["4.18.1"]


def test_find_upgrade_paths_checks_next_minor_channel() -> None:
    calls: list[str] = []

    def fake_upgrade_target_fetcher(channel: str, from_version: str, arch: str) -> list[str]:
        calls.append(channel)
        if channel == "stable-4.19":
            return ["4.19.0"]
        return []

    result = query_versions.find_upgrade_paths(
        "4.18.12",
        channel_types=["stable"],
        upgrade_target_fetcher=fake_upgrade_target_fetcher,
    )

    assert result == {"stable-4.19": ["4.19.0"]}
    assert calls == ["stable-4.18", "stable-4.19"]


def test_main_rejects_invalid_discovery_channel_type(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_info = run_main(monkeypatch, ["--discover", "--channel-type", "bogus"])

    assert exit_info.code == 2
    assert "--channel-type must be one of" in capsys.readouterr().err


def test_main_rejects_invalid_floor_ceiling_range(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_info = run_main(monkeypatch, ["--discover", "--floor", "20", "--ceiling", "10"])

    assert exit_info.code == 2
    assert "--ceiling must be greater than or equal to --floor" in capsys.readouterr().err


def test_main_rejects_invalid_size(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_info = run_main(monkeypatch, ["--token", "abc", "--size", "101"])

    assert exit_info.code == 2
    assert "--size must be between 1 and 100" in capsys.readouterr().err


def test_list_versions_builds_authenticated_query(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_make_request(
        endpoint: str,
        params: dict,
        token: str,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
    ) -> dict:
        captured["endpoint"] = endpoint
        captured["params"] = params
        captured["token"] = token
        captured["max_retries"] = max_retries
        captured["retry_base_delay"] = retry_base_delay
        return {"items": []}

    monkeypatch.setattr(query_versions, "make_request", fake_make_request)

    result = query_versions.list_versions(
        "token-value",
        search="enabled = 'true'",
        page=2,
        size=50,
        max_retries=7,
        retry_base_delay=0.2,
    )

    assert result == {"items": []}
    assert captured == {
        "endpoint": "/api/clusters_mgmt/v1/versions",
        "params": {"page": 2, "size": 50, "search": "enabled = 'true'"},
        "token": "token-value",
        "max_retries": 7,
        "retry_base_delay": 0.2,
    }


def test_get_version_uses_authenticated_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_make_request(
        endpoint: str,
        params: dict | None = None,
        token: str | None = None,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
    ) -> dict:
        captured["endpoint"] = endpoint
        captured["params"] = params
        captured["token"] = token
        captured["max_retries"] = max_retries
        captured["retry_base_delay"] = retry_base_delay
        return {"id": "openshift-v4.18.1"}

    monkeypatch.setattr(query_versions, "make_request", fake_make_request)

    result = query_versions.get_version(
        "token-value",
        "openshift-v4.18.1",
        max_retries=5,
        retry_base_delay=0.25,
    )

    assert result == {"id": "openshift-v4.18.1"}
    assert captured == {
        "endpoint": "/api/clusters_mgmt/v1/versions/openshift-v4.18.1",
        "params": None,
        "token": "token-value",
        "max_retries": 5,
        "retry_base_delay": 0.25,
    }


def test_make_request_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return self._payload

    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    def fake_urlopen(request, timeout=30):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "0"},
                io.BytesIO(b"rate limited"),
            )
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(query_versions.time, "sleep", fake_sleep)
    monkeypatch.setattr(query_versions.urllib.request, "urlopen", fake_urlopen)

    result = query_versions.make_request("/api/upgrades_info/v1/graph", {"channel": "stable-4.18"})

    assert result == {"ok": True}
    assert attempts["count"] == 2
    assert sleeps


def test_make_request_raises_after_urlerror_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    def fake_urlopen(request, timeout=30):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(query_versions.time, "sleep", fake_sleep)
    monkeypatch.setattr(query_versions.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Connection error"):
        query_versions.make_request(
            "/api/upgrades_info/v1/graph",
            {"channel": "stable-4.18"},
            max_retries=2,
        )

    assert len(sleeps) == 2


def test_main_rejects_negative_retry_count(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_info = run_main(monkeypatch, ["--discover", "--retry-count", "-1"])

    assert exit_info.code == 2
    assert "--retry-count must be 0 or greater" in capsys.readouterr().err


def test_main_rejects_nonpositive_retry_base_delay(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_info = run_main(monkeypatch, ["--discover", "--retry-base-delay", "0"])

    assert exit_info.code == 2
    assert "--retry-base-delay must be greater than 0" in capsys.readouterr().err
