from __future__ import annotations

from pathlib import Path


def test_repo_root_pytest_uses_importlib_mode():
    repo_root = Path(__file__).resolve().parents[1]
    pytest_ini = repo_root / "pytest.ini"

    assert pytest_ini.exists()
    assert "--import-mode=importlib" in pytest_ini.read_text(encoding="utf-8")
