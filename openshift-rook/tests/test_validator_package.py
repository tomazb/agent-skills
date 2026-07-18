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


def test_missing_patch_helper_invocation_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8").replace(
            "python3 scripts/patch_rook_ceph_manifest.py", "manual manifest edits"
        ),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("patch_rook_ceph_manifest.py" in issue for issue in issues)


def test_missing_smoke_helper_invocation_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    validation = root / "references" / "validation-hardening.md"
    validation.write_text(
        validation.read_text(encoding="utf-8").replace(
            "python3 scripts/render_smoke_manifest.py", "hand-written smoke YAML"
        ),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("render_smoke_manifest.py" in issue for issue in issues)


def test_missing_ownership_gate_fails(validator, package_factory, make_skill_text):
    root = package_factory(
        skill_text=make_skill_text(missing_sections=["## Product Ownership Gate"])
    )
    issues = validator.validate_root(root)
    assert any("Product Ownership Gate" in issue for issue in issues)


def test_ownership_gate_missing_odf_handoff_fails(validator, package_factory, make_skill_text):
    skill_text = make_skill_text().replace("openshift-odf", "another-skill")
    root = package_factory(skill_text=skill_text)
    issues = validator.validate_root(root)
    assert any("openshift-odf" in issue for issue in issues)


def test_ownership_gate_missing_discovery_markers_fails(
    validator, package_factory, make_skill_text
):
    skill_text = (
        make_skill_text()
        .replace("StorageCluster", "storage CR")
        .replace("CephCluster", "ceph CR")
        .replace("Subscription", "operator install")
        .replace("CSV", "operator bundle")
    )
    root = package_factory(skill_text=skill_text)
    issues = validator.validate_root(root)
    assert any("StorageCluster" in issue or "CephCluster" in issue for issue in issues)
    assert any("Subscription" in issue or "CSV" in issue for issue in issues)


def test_missing_versions_handoff_fails(validator, package_factory, make_skill_text):
    skill_text = make_skill_text().replace("openshift-versions", "version lookup")
    root = package_factory(skill_text=skill_text)
    issues = validator.validate_root(root)
    assert any("openshift-versions" in issue for issue in issues)


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


def test_missing_csi_operator_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(install.read_text(encoding="utf-8").replace("csi-operator.yaml", "csi.yaml"), encoding="utf-8")
    issues = validator.validate_root(root)
    assert any("install-and-preflight.md" in issue and "csi-operator.yaml" in issue for issue in issues)


def test_missing_cephconnection_failure_mode_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(install.read_text(encoding="utf-8").replace("CephConnection", "connection CR"), encoding="utf-8")
    issues = validator.validate_root(root)
    assert any("install-and-preflight.md" in issue and "CephConnection" in issue for issue in issues)


def test_missing_namespace_creation_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8").replace("oc create ns rook-ceph", "oc create project rook-ceph"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("install-and-preflight.md" in issue and "oc create ns rook-ceph" in issue for issue in issues)


def test_missing_sno_pg_ceiling_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8").replace("mon_max_pg_per_osd", "pg ceiling"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("install-and-preflight.md" in issue and "mon_max_pg_per_osd" in issue for issue in issues)


def test_missing_explicit_sno_device_pinning_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8").replace("/dev/disk/by-id/<stable-disk-id>", "/dev/nvme0n1"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any(
        "install-and-preflight.md" in issue and "/dev/disk/by-id/<stable-disk-id>" in issue
        for issue in issues
    )


def test_missing_install_sequence_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8").replace(
            "oc apply -f /tmp/rook-ceph-common.yaml",
            "oc apply -f /tmp/rook-ceph-common-manifest.yaml",
        ),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any(
        "install-and-preflight.md" in issue and "oc apply -f /tmp/rook-ceph-common.yaml" in issue
        for issue in issues
    )


def test_missing_dashboard_prometheus_fallback_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    validation = root / "references" / "validation-hardening.md"
    validation.write_text(
        validation.read_text(encoding="utf-8")
        .replace("internal Prometheus", "internal metrics service")
        .replace("PROMETHEUS_API_HOST", "dashboard Prometheus host"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("validation-hardening.md" in issue and "internal Prometheus" in issue for issue in issues) or any(
        "validation-hardening.md" in issue and "PROMETHEUS_API_HOST" in issue for issue in issues
    )


def test_missing_dashboard_route_port_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    validation = root / "references" / "validation-hardening.md"
    validation.write_text(
        validation.read_text(encoding="utf-8").replace("http-dashboard", "dashboard-http"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("validation-hardening.md" in issue and "http-dashboard" in issue for issue in issues)


def test_missing_rook_orchestrator_backend_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    validation = root / "references" / "validation-hardening.md"
    validation.write_text(
        validation.read_text(encoding="utf-8").replace("ceph orch set backend rook", "ceph orch backend"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("validation-hardening.md" in issue and "ceph orch set backend rook" in issue for issue in issues)


def test_missing_upgrade_csi_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    upgrade = root / "references" / "upgrade.md"
    upgrade.write_text(upgrade.read_text(encoding="utf-8").replace("csi-operator.yaml", "csi.yaml"), encoding="utf-8")
    issues = validator.validate_root(root)
    assert any("references/upgrade.md" in issue and "csi-operator.yaml" in issue for issue in issues)


def test_missing_upgrade_sequence_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    upgrade = root / "references" / "upgrade.md"
    upgrade.write_text(
        upgrade.read_text(encoding="utf-8").replace(
            "oc apply -f /tmp/rook-ceph-common.yaml",
            "oc apply -f /tmp/rook-ceph-common-manifest.yaml",
        ),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("references/upgrade.md" in issue and "oc apply -f /tmp/rook-ceph-common.yaml" in issue for issue in issues)


def test_missing_rgw_route_validation_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    rgw = root / "references" / "rgw-object-store.md"
    rgw.write_text(
        rgw.read_text(encoding="utf-8").replace("Ceph Object Gateway", "object gateway"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("references/rgw-object-store.md" in issue and "Ceph Object Gateway" in issue for issue in issues)


def test_missing_rgw_non_200_route_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    rgw = root / "references" / "rgw-object-store.md"
    rgw.write_text(
        rgw.read_text(encoding="utf-8").replace("TLS or connection failure", "HTTP 200 only"),
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("references/rgw-object-store.md" in issue and "TLS or connection failure" in issue for issue in issues)


def test_forbidden_rgw_http_200_only_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    rgw = root / "references" / "rgw-object-store.md"
    rgw.write_text(rgw.read_text(encoding="utf-8") + "\nRGW Route returns HTTP 200.\n", encoding="utf-8")
    issues = validator.validate_root(root)
    assert any("references/rgw-object-store.md" in issue and "HTTP 200" in issue for issue in issues)


def test_missing_validated_sno_evidence_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    sno = root / "references" / "validated-rook-ceph-sno.md"
    sno.write_text(sno.read_text(encoding="utf-8").replace("v1.20.2", "v1.x"), encoding="utf-8")
    issues = validator.validate_root(root)
    assert any("references/validated-rook-ceph-sno.md" in issue and "v1.20.2" in issue for issue in issues)


def test_conflicting_install_order_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    install = root / "references" / "install-and-preflight.md"
    install.write_text(
        install.read_text(encoding="utf-8")
        + "\noc apply -f /tmp/rook-ceph-operator.yaml\noc apply -f /tmp/rook-ceph-csi-operator.yaml\n",
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("references/install-and-preflight.md" in issue and "operator before csi-operator" in issue for issue in issues)


def test_conflicting_upgrade_order_guidance_fails(validator, package_factory, reference_text):
    root = package_factory(reference_content=reference_text())
    upgrade = root / "references" / "upgrade.md"
    upgrade.write_text(
        upgrade.read_text(encoding="utf-8")
        + "\noc apply -f /tmp/rook-ceph-operator.yaml\noc apply -f /tmp/rook-ceph-csi-operator.yaml\n",
        encoding="utf-8",
    )
    issues = validator.validate_root(root)
    assert any("references/upgrade.md" in issue and "operator before csi-operator" in issue for issue in issues)
