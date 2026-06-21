from __future__ import annotations


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
