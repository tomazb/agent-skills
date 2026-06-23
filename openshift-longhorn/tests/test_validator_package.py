from __future__ import annotations

from pathlib import Path


def test_valid_package_passes_cleanly(validator, package_factory):
    root = package_factory()
    assert validator.validate_root(root) == []


def test_frontmatter_name_mismatch_fails(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(name="openshift-longhorn-deploy"))
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
    # Replacing "one default StorageClass" also removes "exactly one default
    # StorageClass" (it is a superstring), so both SNO StorageClass phrases drop.
    text = (
        reference_text()
        .replace('numberOfReplicas: "1"', "replica setting")
        .replace("one default StorageClass", "cluster default class")
    )
    # Guard against future fixture rewording silently turning these into no-ops.
    assert 'numberOfReplicas: "1"' not in text
    assert "exactly one default StorageClass" not in text
    assert "one default StorageClass" not in text
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("SNO replica/default StorageClass" in issue for issue in issues)


def test_present_sno_storageclass_rules_pass(validator, package_factory, reference_text):
    # The unmodified reference text contains every SNO phrase, so the group must pass.
    root = package_factory(reference_content=reference_text())
    issues = validator.check_phrase_group(
        validator.package_markdown_text(root),
        validator.SNO_STORAGE_PHRASES,
        "SNO replica/default StorageClass",
    )
    assert issues == []


def test_v1_and_v2_preflight_paths_are_documented():
    root = Path(__file__).resolve().parents[1]
    install_text = (root / "references" / "install-and-preflight.md").read_text(encoding="utf-8")
    v1_text = (root / "references" / "v1-filesystem.md").read_text(encoding="utf-8")
    v2_text = (root / "references" / "v2-block-data-engine.md").read_text(encoding="utf-8")

    assert 'longhornctl --kubeconfig "${KUBECONFIG}" check preflight' in install_text
    assert 'longhornctl --kubeconfig "${KUBECONFIG}" check preflight' in v1_text
    assert "Do not use `--enable-spdk` for a V1-only check" in v1_text
    assert "longhornctl check preflight --enable-spdk" in v2_text
    assert "temporary privileged SCC workflow" in v2_text


def test_live_preflight_warning_interpretation_is_documented():
    root = Path(__file__).resolve().parents[1]
    install_text = (root / "references" / "install-and-preflight.md").read_text(encoding="utf-8")
    v2_text = (root / "references" / "v2-block-data-engine.md").read_text(encoding="utf-8")

    assert "https://github.com/longhorn/cli/releases" in install_text
    assert "verify the checksum" in install_text
    assert "/host/proc/config.gz" in install_text
    assert "KubeDNS" in install_text
    assert "ublk_drv cannot be loaded" in v2_text
    assert "diskDriver: aio" in v2_text


def test_missing_v2_raw_block_hugepage_module_and_scc_guidance_fails(
    validator, package_factory, reference_text
):
    text = (
        reference_text()
        .replace("raw block", "block")
        .replace("hugepagesz=2M", "hugepage size")
        .replace("hugepages=1024", "hugepage count")
        .replace("vfio_pci", "vfio")
        .replace("uio_pci_generic", "uio")
        .replace("nvme_tcp", "nvme")
        .replace("privileged SCC", "temporary privilege")
    )
    # Guard against future fixture rewording silently turning these into no-ops.
    assert "raw block" not in text
    assert "hugepagesz=2M" not in text
    assert "privileged SCC" not in text
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("V2 raw block/hugepages/modules/SCC" in issue for issue in issues)


def test_missing_raw_block_phrase_alone_fails(validator, package_factory, reference_text):
    # Dropping only "raw block" must be enough to flag the V2 guidance group.
    text = reference_text().replace("raw block", "block storage")
    assert "raw block" not in text
    root = package_factory(reference_content=text)
    issues = validator.validate_root(root)
    assert any("V2 raw block/hugepages/modules/SCC" in issue for issue in issues)


def test_readme_version_matches_passes(validator, package_factory):
    # The factory writes README "Current version: **1.2.3**" and VERSION "1.2.3",
    # so the sync check must report no issues.
    root = package_factory()
    assert validator.check_readme_version(root) == []


def test_readme_version_mismatch_fails(validator, package_factory):
    root = package_factory()
    (root / "README.md").write_text(
        "# OpenShift Longhorn\n\nCurrent version: **9.9.9**\n", encoding="utf-8"
    )
    issues = validator.validate_root(root)
    assert any("README.md version" in issue and "out of sync" in issue for issue in issues)


def test_readme_missing_version_marker_fails(validator, package_factory):
    root = package_factory()
    (root / "README.md").write_text(
        "# OpenShift Longhorn\n\nNo version marker here.\n", encoding="utf-8"
    )
    issues = validator.validate_root(root)
    assert any("missing 'Current version" in issue for issue in issues)
