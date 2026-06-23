from __future__ import annotations

from pathlib import Path


def test_valid_package_passes_cleanly(validator, package_factory):
    root = package_factory()
    assert validator.validate_root(root) == []


def test_frontmatter_name_mismatch_fails(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(name="openshift-rook-ceph-deploy"))
    issues = validator.validate_root(root)
    assert any("frontmatter name" in issue for issue in issues)


def test_missing_lifecycle_reference_fails(validator, package_factory):
    root = package_factory()
    missing = root / validator.EXPECTED_REFERENCES[0]
    missing.unlink()
    issues = validator.validate_root(root)
    assert any(str(missing.relative_to(root)) in issue for issue in issues)


def test_missing_required_helper_file_fails(validator, package_factory):
    root = package_factory()
    missing = root / "scripts" / "render_smoke_manifest.py"
    missing.unlink()
    issues = validator.validate_root(root)
    assert any(str(missing.relative_to(root)) in issue for issue in issues)


def test_missing_required_skill_section_fails(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(missing_sections=["## Routing"]))
    issues = validator.validate_root(root)
    assert any("missing required sections" in issue for issue in issues)


def test_missing_destructive_confirmation_language_fails(validator, package_factory, reference_text):
    text = reference_text().replace("explicit destructive confirmation", "operator approval")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("destructive disk safety" in issue for issue in issues)


def test_missing_sno_replica_and_default_storageclass_rules_fail(validator, package_factory, reference_text):
    text = (
        reference_text()
        .replace("replicated.size: 1", "replica setting")
        .replace("one default StorageClass", "cluster default class")
    )
    assert "replicated.size: 1" not in text
    assert "exactly one default StorageClass" not in text
    assert "one default StorageClass" not in text
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("SNO replica/default StorageClass" in issue for issue in issues)


def test_present_sno_storageclass_rules_pass(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    issues = validator.check_phrase_group(
        validator.package_markdown_text(root),
        validator.SNO_STORAGE_PHRASES,
        "SNO replica/default StorageClass",
    )
    assert issues == []


def test_missing_ceph_service_types_fails(validator, package_factory, reference_text):
    text = (
        reference_text()
        .replace("RBD", "block")
        .replace("CephFS", "fs")
        .replace("RGW", "object")
        .replace("cephblockpool", "pool")
        .replace("cephfilesystem", "filesystem")
        .replace("cephobjectstore", "objectstore")
    )
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("Ceph service types" in issue for issue in issues)


def test_missing_openshift_machineconfig_scc_fails(validator, package_factory, reference_text):
    text = reference_text().replace("MachineConfig", "host config").replace("SCC", "security context")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("OpenShift SCC/MachineConfig" in issue for issue in issues)


def test_missing_upgrade_safety_fails(validator, package_factory, reference_text):
    text = reference_text().replace("Do not downgrade", "do not revert").replace("release notes", "changelog")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("upgrade safety" in issue for issue in issues)


def test_readme_version_matches_passes(validator, package_factory):
    root = package_factory()
    assert validator.check_readme_version(root) == []


def test_readme_version_mismatch_fails(validator, package_factory):
    root = package_factory()
    (root / "README.md").write_text(
        "# OpenShift Rook Ceph\n\nCurrent version: **9.9.9**\n", encoding="utf-8"
    )
    issues = validator.validate_root(root)
    assert any("README.md version" in issue and "out of sync" in issue for issue in issues)


def test_readme_missing_version_marker_fails(validator, package_factory):
    root = package_factory()
    (root / "README.md").write_text(
        "# OpenShift Rook Ceph\n\nNo version marker here.\n", encoding="utf-8"
    )
    issues = validator.validate_root(root)
    assert any("missing 'Current version" in issue for issue in issues)


def test_forbidden_gateway_type_s3_fails(validator, package_factory, reference_text):
    text = reference_text() + "\nspec:\n  gateway:\n    type: s3\n"
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("type: s3" in issue for issue in issues)


def test_forbidden_rgw_privileged_http_port_fails(validator, package_factory, reference_text):
    text = reference_text() + "\nspec:\n  gateway:\n    port: 80\n"
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("port: 80" in issue for issue in issues)


def test_forbidden_rgw_privileged_secure_port_fails(validator, package_factory, reference_text):
    text = reference_text() + "\nspec:\n  gateway:\n    securePort: 443\n"
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("securePort: 443" in issue for issue in issues)


def test_non_privileged_rgw_ports_pass(validator, package_factory, reference_text):
    text = reference_text() + "\nspec:\n  gateway:\n    port: 8080\n    securePort: 8443\n"
    root = package_factory(reference_content=text)
    assert validator.check_content_regressions(root) == []


def test_missing_autoscaler_guidance_fails(validator, package_factory, reference_text):
    text = reference_text().replace("autoscale", "manual-pg")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("PG autoscaler" in issue for issue in issues)


def test_missing_operator_openshift_guidance_fails(validator, package_factory, reference_text):
    text = reference_text().replace("operator-openshift.yaml", "operator.yaml")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("operator-openshift.yaml" in issue for issue in issues)
