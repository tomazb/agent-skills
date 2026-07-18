from __future__ import annotations

def test_skill_line_count_passes_under_limit(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text())
    issues = validator.check_skill_file(root)
    assert not any("lines" in issue and ">" in issue for issue in issues)


def test_skill_line_count_enforcement(validator, package_factory, make_skill_text):
    long_skill = make_skill_text() + ("extra line\n" * validator.MAX_SKILL_LINES)
    root = package_factory(skill_text=long_skill)
    issues = validator.check_skill_file(root)
    assert any("SKILL.md is" in issue for issue in issues)


def test_phase_headings_all_present(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text())
    issues = validator.check_skill_file(root)
    assert not any("phase" in issue.lower() for issue in issues)


def test_phase_headings_missing_one(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(missing_phases=[5]))
    issues = validator.check_skill_file(root)
    assert any("missing phases" in issue for issue in issues)


def test_phase_headings_missing_multiple(validator, package_factory, make_skill_text):
    root = package_factory(skill_text=make_skill_text(missing_phases=[0, 8, 16]))
    issues = validator.check_skill_file(root)
    assert any("missing phases" in issue for issue in issues)


def test_check_expected_references_all_present(validator, package_factory):
    root = package_factory(include_references=True)
    assert validator.check_expected_references(root) == []


def test_check_expected_references_missing_one(validator, package_factory):
    root = package_factory(include_references=True)
    missing_ref = root / validator.EXPECTED_REFERENCES[0]
    missing_ref.unlink()
    issues = validator.check_expected_references(root)
    assert len(issues) == 1
    assert validator.EXPECTED_REFERENCES[0] in issues[0]


def test_check_expected_references_none_present(validator, package_factory):
    root = package_factory(include_references=False)
    issues = validator.check_expected_references(root)
    assert len(issues) == len(validator.EXPECTED_REFERENCES)


def test_validate_root_clean_package(validator, package_factory):
    root = package_factory()
    issues = validator.validate_root(root)
    assert issues == [], f"Expected no issues, got: {issues}"


def test_missing_specialist_handoffs_fails(validator, package_factory, make_skill_text):
    skill_text = make_skill_text().replace("## Specialist handoffs", "## Other")
    root = package_factory(skill_text=skill_text)
    issues = validator.check_skill_file(root)
    assert any("Specialist handoffs" in issue for issue in issues)


def test_missing_storage_handoff_target_fails(validator, package_factory, make_skill_text):
    skill_text = make_skill_text().replace("openshift-odf", "storage-odf")
    root = package_factory(skill_text=skill_text)
    issues = validator.check_skill_file(root)
    assert any("openshift-odf" in issue for issue in issues)


def test_handoff_target_outside_section_does_not_satisfy(
    validator, package_factory, make_skill_text
):
    skill_text = make_skill_text().replace(
        "- ODF evidence (`StorageCluster`) → `openshift-odf`\n",
        "- ODF evidence (`StorageCluster`) → elsewhere\n",
    )
    skill_text += "\nMention `openshift-odf` outside the handoff section.\n"
    root = package_factory(skill_text=skill_text)
    issues = validator.check_skill_file(root)
    assert any("openshift-odf" in issue for issue in issues)


def test_missing_readiness_disclaimer_fails(validator, package_factory, make_skill_text):
    skill_text = make_skill_text().replace(
        "Release availability is not cluster upgrade readiness.",
        "Release availability is documented separately.",
    )
    root = package_factory(skill_text=skill_text)
    issues = validator.check_skill_file(root)
    assert any("not cluster upgrade readiness" in issue for issue in issues)
