from __future__ import annotations

import json


def test_semver_regex_accepts_prerelease_and_build_metadata(bump_version_module):
    assert bump_version_module.SEMVER_RE.match("1.2.3-rc.1+build.456")


def test_semver_regex_rejects_leading_zero_identifiers(bump_version_module):
    for version in ("01.2.3", "1.02.3", "1.2.03", "1.2.3-01"):
        assert not bump_version_module.SEMVER_RE.match(version)


def test_bump_version_fails_when_readme_version_line_missing(
    tmp_path, bump_version_module, monkeypatch, capsys
):
    root = tmp_path / "pkg"
    tools_dir = root / "tools"
    tools_dir.mkdir(parents=True)

    (root / "package.json").write_text(
        json.dumps({"name": "challenging-decisions", "version": "1.0.0"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# Challenging Decisions\n\nNo current version line here.\n",
        encoding="utf-8",
    )

    fake_script = tools_dir / "bump_version.py"
    fake_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(bump_version_module, "__file__", str(fake_script))

    exit_code = bump_version_module.main(["bump_version.py", "1.2.3"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "README.md" in captured.err
    assert json.loads((root / "package.json").read_text(encoding="utf-8"))["version"] == "1.0.0"
    assert (root / "VERSION").read_text(encoding="utf-8") == "1.0.0\n"


def test_bump_version_fails_when_package_json_is_not_an_object(
    tmp_path, bump_version_module, monkeypatch, capsys
):
    root = tmp_path / "pkg"
    tools_dir = root / "tools"
    tools_dir.mkdir(parents=True)

    (root / "package.json").write_text("[]\n", encoding="utf-8")
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# Challenging Decisions\n\nCurrent version: **1.0.0**\n",
        encoding="utf-8",
    )

    fake_script = tools_dir / "bump_version.py"
    fake_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(bump_version_module, "__file__", str(fake_script))

    exit_code = bump_version_module.main(["bump_version.py", "1.2.3"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "package.json must contain a JSON object" in captured.err


def test_bump_version_fails_when_readme_is_missing(
    tmp_path, bump_version_module, monkeypatch, capsys
):
    root = tmp_path / "pkg"
    tools_dir = root / "tools"
    tools_dir.mkdir(parents=True)

    (root / "package.json").write_text(
        json.dumps({"name": "challenging-decisions", "version": "1.0.0"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")

    fake_script = tools_dir / "bump_version.py"
    fake_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(bump_version_module, "__file__", str(fake_script))

    exit_code = bump_version_module.main(["bump_version.py", "1.2.3"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "README.md was not found" in captured.err
    assert json.loads((root / "package.json").read_text(encoding="utf-8"))["version"] == "1.0.0"
    assert (root / "VERSION").read_text(encoding="utf-8") == "1.0.0\n"


def test_bump_version_rolls_back_when_a_file_update_fails(
    tmp_path, bump_version_module, monkeypatch, capsys
):
    root = tmp_path / "pkg"
    tools_dir = root / "tools"
    tools_dir.mkdir(parents=True)

    package_file = root / "package.json"
    version_file = root / "VERSION"
    readme_file = root / "README.md"

    package_file.write_text(
        json.dumps({"name": "challenging-decisions", "version": "1.0.0"}, indent=2) + "\n",
        encoding="utf-8",
    )
    version_file.write_text("1.0.0\n", encoding="utf-8")
    readme_file.write_text(
        "# Challenging Decisions\n\nCurrent version: **1.0.0**\n",
        encoding="utf-8",
    )

    fake_script = tools_dir / "bump_version.py"
    fake_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(bump_version_module, "__file__", str(fake_script))

    original_replace_file = bump_version_module.replace_file

    def flaky_replace(source, destination):
        if destination == version_file:
            raise OSError("disk full")
        return original_replace_file(source, destination)

    monkeypatch.setattr(bump_version_module, "replace_file", flaky_replace)

    exit_code = bump_version_module.main(["bump_version.py", "1.2.3"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "failed to update version files" in captured.err
    assert json.loads(package_file.read_text(encoding="utf-8"))["version"] == "1.0.0"
    assert version_file.read_text(encoding="utf-8") == "1.0.0\n"
    assert "Current version: **1.0.0**" in readme_file.read_text(encoding="utf-8")


def test_version_sync_match(validator, package_factory):
    root = package_factory()
    assert validator.check_version_sync(root) == []


def test_version_sync_mismatch(validator, package_factory):
    root = package_factory(
        package_json_text='{"name":"challenging-decisions","version":"9.9.9"}\n'
    )
    issues = validator.check_version_sync(root)
    assert len(issues) == 1
    assert "out of sync" in issues[0]


def test_version_sync_invalid_package_json(validator, package_factory):
    root = package_factory(
        package_json_text='{"name": "challenging-decisions", "version": "1.0.0"'
    )
    issues = validator.check_version_sync(root)
    assert issues == ["package.json is not valid JSON."]


def test_version_sync_requires_package_json_object(validator, package_factory):
    root = package_factory(package_json_text="[]\n")
    issues = validator.check_version_sync(root)
    assert issues == ["package.json must contain a JSON object."]


def test_version_sync_rejects_invalid_semver_even_when_versions_match(
    validator, package_factory
):
    root = package_factory(
        package_json_text='{"name":"challenging-decisions","version":"01.2.3"}\n'
    )
    (root / "VERSION").write_text("01.2.3\n", encoding="utf-8")
    issues = validator.check_version_sync(root)
    assert issues == ["VERSION must be a valid semantic version."]


def test_changelog_version_match(validator, package_factory):
    root = package_factory()
    assert validator.check_changelog_version(root) == []


def test_changelog_version_mismatch(validator, package_factory):
    root = package_factory(changelog_text="# Changelog\n\n## 9.9.9\n- New release.\n")
    issues = validator.check_changelog_version(root)
    assert len(issues) == 1
    assert "does not contain a heading for VERSION '1.0.0'" in issues[0]


def test_readme_version_match(validator, package_factory):
    root = package_factory()
    assert validator.check_readme_version(root) == []


def test_readme_version_mismatch(validator, package_factory):
    root = package_factory(readme_text="# Challenging Decisions\n\nCurrent version: **9.9.9**\n")
    issues = validator.check_readme_version(root)
    assert issues == ["README.md version does not match VERSION '1.0.0'."]


def test_readme_version_duplicate_lines_fail_validation(validator, package_factory):
    root = package_factory(
        readme_text=(
            "# Challenging Decisions\n\n"
            "Current version: **1.0.0**\n"
            "Current version: **1.0.0**\n"
        )
    )
    issues = validator.check_readme_version(root)
    assert issues == ["README.md must contain exactly one 'Current version: **...**' line."]
