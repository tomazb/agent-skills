from __future__ import annotations

from pathlib import Path


def test_valid_package_passes_cleanly(validator, package_factory):
    root = package_factory()
    assert validator.validate_root(root) == []


def test_frontmatter_name_mismatch_fails(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(name="openshift-odf-deploy"))
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
    missing = root / "scripts" / "render_storagecluster.py"
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


def test_missing_odf_service_types_fails(validator, package_factory, reference_text):
    text = (
        reference_text()
        .replace("ceph-rbd", "block")
        .replace("CephFS", "fs")
        .replace("RGW", "object")
        .replace("MCG", "multicloud")
    )
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("ODF storage services" in issue for issue in issues)


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
        "# OpenShift Data Foundation\n\nCurrent version: **9.9.9**\n", encoding="utf-8"
    )
    issues = validator.validate_root(root)
    assert any("README.md version" in issue and "out of sync" in issue for issue in issues)


def test_readme_missing_version_marker_fails(validator, package_factory):
    root = package_factory()
    (root / "README.md").write_text(
        "# OpenShift Data Foundation\n\nNo version marker here.\n", encoding="utf-8"
    )
    issues = validator.validate_root(root)
    assert any("missing 'Current version" in issue for issue in issues)


def test_forbidden_upstream_rook_operator_manifest_fails(validator, package_factory, reference_text):
    text = reference_text() + "\nApply operator-openshift.yaml first.\n"
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("upstream Rook operator manifest" in issue for issue in issues)


def test_forbidden_helm_install_rook_fails(validator, package_factory, reference_text):
    text = reference_text() + "\nRun helm install rook-ceph rook-release/rook-ceph.\n"
    root = package_factory(reference_content=text)
    issues = validator.check_content_regressions(root)
    assert any("Helm install" in issue for issue in issues)


def test_forbidden_rgw_privileged_http_port_fails(validator, package_factory, reference_text):
    text = reference_text() + "\nspec:\n  gateway:\n    port: 80\n"
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("port: 80" in issue for issue in issues)


def test_non_privileged_rgw_ports_pass(validator, package_factory, reference_text):
    text = reference_text() + "\nspec:\n  gateway:\n    port: 8080\n    securePort: 8443\n"
    root = package_factory(reference_content=text)
    assert validator.check_content_regressions(root) == []


def test_missing_autoscaler_guidance_fails(validator, package_factory, reference_text):
    text = reference_text().replace("autoscale", "manual-pg")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("PG autoscaler" in issue for issue in issues)


def test_missing_odf_operator_guidance_fails(validator, package_factory, reference_text):
    text = reference_text().replace("odf-operator", "storage-operator")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("odf-operator" in issue for issue in issues)


def test_missing_enable_ceph_tools_guidance_fails(validator, package_factory, reference_text):
    text = reference_text().replace("enableCephTools", "toolsEnabled")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("enableCephTools" in issue for issue in issues)


def test_missing_node_label_guidance_fails(validator, package_factory, reference_text):
    text = reference_text().replace("cluster.ocs.openshift.io/openshift-storage", "storage-node")
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("cluster.ocs.openshift.io/openshift-storage" in issue for issue in issues)


def test_missing_olm_install_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8").replace("OperatorGroup", "operator group"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("install-and-preflight.md" in issue and "OperatorGroup" in issue for issue in issues)


def test_missing_olm_install_ordering_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8").replace("kind: Subscription", "kind: Sub"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any(
        "install-and-preflight.md" in issue and "kind: Subscription" in issue for issue in issues
    )


def test_missing_local_storage_operator_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    lso = root / "references" / "local-storage-disks.md"
    lso.write_text(
        lso.read_text(encoding="utf-8").replace("LocalVolumeSet", "LocalVolume"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("local-storage-disks.md" in issue and "LocalVolumeSet" in issue for issue in issues)


def test_missing_upgrade_reference_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    upgrade = root / "references" / "upgrade.md"
    upgrade.write_text(
        upgrade.read_text(encoding="utf-8").replace("installPlanApproval", "planApproval"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("references/upgrade.md" in issue and "installPlanApproval" in issue for issue in issues)


def test_missing_mcg_rgw_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    obj = root / "references" / "object-mcg-rgw.md"
    obj.write_text(
        obj.read_text(encoding="utf-8").replace("openshift-storage.noobaa.io", "noobaa-sc"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any(
        "object-mcg-rgw.md" in issue and "openshift-storage.noobaa.io" in issue for issue in issues
    )


def test_missing_osd_removal_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    expand = root / "references" / "cluster-expand-shrink.md"
    expand.write_text(
        expand.read_text(encoding="utf-8").replace("ocs-osd-removal", "osd-remove"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any(
        "cluster-expand-shrink.md" in issue and "ocs-osd-removal" in issue for issue in issues
    )


def test_missing_uninstall_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    uninstall = root / "references" / "maintenance-uninstall.md"
    uninstall.write_text(
        uninstall.read_text(encoding="utf-8").replace(
            "uninstall.ocs.openshift.io/cleanup-policy", "cleanup-annotation"
        ),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any(
        "maintenance-uninstall.md" in issue
        and "uninstall.ocs.openshift.io/cleanup-policy" in issue
        for issue in issues
    )


def test_missing_validation_dashboard_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    validation = root / "references" / "validation-hardening.md"
    validation.write_text(
        validation.read_text(encoding="utf-8").replace("Data Foundation", "storage console"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any(
        "validation-hardening.md" in issue and "Data Foundation" in issue for issue in issues
    )


def test_missing_validated_sno_evidence_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    sno = root / "references" / "validated-odf-sno.md"
    sno.write_text(
        sno.read_text(encoding="utf-8").replace("HEALTH_OK", "healthy"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("validated-odf-sno.md" in issue and "HEALTH_OK" in issue for issue in issues)
