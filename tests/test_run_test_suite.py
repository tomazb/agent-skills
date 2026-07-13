from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runner():
    repo_root = Path(__file__).resolve().parents[1]
    return load_module(repo_root / "scripts" / "run_test_suite.py", "run_test_suite")


def make_suite(repo_root: Path, relative_path: str) -> Path:
    suite_dir = repo_root / relative_path
    suite_dir.mkdir(parents=True)
    return suite_dir


def test_find_test_suites_orders_root_then_skills(tmp_path):
    module = load_runner()

    make_suite(tmp_path, "zeta/tests")
    make_suite(tmp_path, "tests")
    make_suite(tmp_path, "alpha/tests")
    make_suite(tmp_path, ".hidden/tests")

    assert module.find_test_suites(tmp_path) == [
        tmp_path / "tests",
        tmp_path / "alpha/tests",
        tmp_path / "zeta/tests",
    ]


def test_run_test_suites_builds_pytest_commands_and_junit_paths(tmp_path, monkeypatch):
    module = load_runner()
    make_suite(tmp_path, "tests")
    make_suite(tmp_path, "beta/tests")
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(command, cwd, check):
        calls.append((command, cwd, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    junit_dir = tmp_path / "artifacts"

    assert module.run_test_suites(tmp_path, junit_dir) == 0
    assert calls == [
        (
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests",
                f"--junitxml={junit_dir / 'root.xml'}",
            ],
            tmp_path,
            False,
        ),
        (
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "beta/tests",
                f"--junitxml={junit_dir / 'beta.xml'}",
            ],
            tmp_path,
            False,
        ),
    ]
    assert junit_dir.is_dir()


def test_run_test_suites_reports_failed_suites(tmp_path, monkeypatch, capsys):
    module = load_runner()
    make_suite(tmp_path, "tests")
    make_suite(tmp_path, "alpha/tests")
    returncodes = iter([0, 1])

    def fake_run(command, cwd, check):
        return subprocess.CompletedProcess(command, next(returncodes))

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.run_test_suites(tmp_path) == 1

    captured = capsys.readouterr()
    assert "Failed test suites:" in captured.err
    assert "- alpha/tests" in captured.err


def test_run_test_suites_reports_missing_pytest(tmp_path, monkeypatch, capsys):
    module = load_runner()
    make_suite(tmp_path, "tests")

    def fake_run(command, cwd, check):
        raise FileNotFoundError("pytest missing")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.run_test_suites(tmp_path) == 1

    captured = capsys.readouterr()
    assert "Unable to run pytest: pytest missing" in captured.err


def test_run_test_suites_returns_error_when_no_suites_found(tmp_path, capsys):
    module = load_runner()

    assert module.run_test_suites(tmp_path) == 1

    captured = capsys.readouterr()
    assert "No test suites found." in captured.err
