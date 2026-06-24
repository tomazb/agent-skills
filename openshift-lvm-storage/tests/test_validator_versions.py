from __future__ import annotations

import pytest


def test_version_sync_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_version_sync(root)
    assert issues == []


def test_changelog_version_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_changelog_version(root)
    assert issues == []


def test_readme_version_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_readme_version(root)
    assert issues == []


def test_frontmatter_ok(validator, package_factory):
    root = package_factory()
    issues = validator.check_frontmatter(root)
    assert issues == []
