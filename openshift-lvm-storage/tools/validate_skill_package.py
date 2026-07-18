#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

EXPECTED_NAME = "openshift-lvm-storage"
FENCE_RE = re.compile(r"^\s*```")
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)

EXPECTED_REFERENCES = [
    "references/install-and-preflight.md",
    "references/volume-group-provisioning.md",
    "references/filesystem-volumes.md",
    "references/block-volumes.md",
    "references/expand-shrink.md",
    "references/upgrade.md",
    "references/backup-restore-dr.md",
    "references/maintenance-uninstall.md",
    "references/validation-hardening.md",
    "references/validated-lvms-ocp-sno.md",
]

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "VERSION",
    "CHANGELOG.md",
    "package.json",
    "assets/smoke-pvc-writer.yaml",
    "scripts/patch_lvms_manifest.py",
    "scripts/post_uninstall_audit.sh",
    "scripts/render_smoke_manifest.py",
    "tools/validate_skill_package.py",
    "tools/validate_skill_package.sh",
]

REQUIRED_SKILL_SECTIONS = [
    "## Routing",
    "## Core Safety Rules",
    "## Required Source Checks",
    "## Inputs To Collect",
    "## Output Expectations",
]

SAFETY_PHRASES = [
    "explicit destructive confirmation",
    "readlink -f",
    "lsblk -f",
    "wipefs -n",
    "pvs",
    "vgs",
    "lvs",
    "/dev/disk/by-id/",
    "pvcreate",
    "vgcreate",
    "vgremove",
    "lvremove",
    "wipefs",
]

SNO_STORAGE_PHRASES = [
    "SNO",
    "exactly one default StorageClass",
    "one default StorageClass",
]

LVMS_PHRASES = [
    "LVMCluster",
    "thinPoolConfig",
    "overprovisionRatio",
    "sizePercent",
    "deviceSelector",
    "forceWipeDevicesAndDestroyAllData",
    "WaitForFirstConsumer",
    "topolvm.io",
    "LogicalVolume",
]

OPENSHIFT_PHRASES = [
    "MachineConfig",
    "reboot",
    "MCP",
    "SCC",
    "OLM",
    "Subscription",
    "CSV",
]

UPGRADE_PHRASES = [
    "Do not downgrade",
    "release notes",
]

MAX_SKILL_LINES = 180


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def ends_with_newline(path: Path) -> bool:
    content = path.read_bytes()
    return not content or content.endswith(b"\n")


def fence_count_ok(text: str) -> bool:
    fences = sum(1 for line in text.splitlines() if FENCE_RE.match(line))
    return fences % 2 == 0


def parse_frontmatter(skill_text: str) -> dict[str, str] | None:
    match = FRONTMATTER_RE.match(skill_text)
    if not match:
        return None

    data: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def check_markdown_file(path: Path, root: Path) -> list[str]:
    issues: list[str] = []
    rel = str(path.relative_to(root))
    text = read_text(path)

    if not ends_with_newline(path):
        issues.append(f"{rel}: missing trailing newline")
    if not fence_count_ok(text):
        issues.append(f"{rel}: odd number of ``` fences (unclosed code block?)")

    return issues


def check_required_files(root: Path) -> list[str]:
    return [
        f"Missing required file: {rel}"
        for rel in REQUIRED_FILES
        if not (root / rel).exists()
    ]


def check_frontmatter(root: Path) -> list[str]:
    skill_file = root / "SKILL.md"
    if not skill_file.exists():
        return ["Missing SKILL.md at package root."]

    frontmatter = parse_frontmatter(read_text(skill_file))
    if frontmatter is None:
        return ["SKILL.md: missing or invalid YAML frontmatter"]

    issues: list[str] = []
    if frontmatter.get("name") != EXPECTED_NAME:
        issues.append(
            f"SKILL.md: frontmatter name '{frontmatter.get('name', '')}' does not match '{EXPECTED_NAME}'"
        )
    description = frontmatter.get("description", "")
    if not description:
        issues.append("SKILL.md: missing frontmatter description")
    elif not description.startswith("Use when"):
        issues.append("SKILL.md: description must start with 'Use when'")
    return issues


def check_expected_references(root: Path) -> list[str]:
    return [
        f"Missing expected reference: {rel}"
        for rel in EXPECTED_REFERENCES
        if not (root / rel).exists()
    ]


def check_required_sections(skill_text: str) -> list[str]:
    missing = [section for section in REQUIRED_SKILL_SECTIONS if section not in skill_text]
    if missing:
        return [f"SKILL.md is missing required sections: {', '.join(missing)}"]
    return []


PHRASE_SCAN_EXCLUDES = {"README.md", "CHANGELOG.md"}


def package_markdown_text(root: Path) -> str:
    return "\n".join(
        read_text(path)
        for path in sorted(root.rglob("*.md"))
        if path.name not in PHRASE_SCAN_EXCLUDES
    )


def missing_phrases(text: str, phrases: list[str]) -> list[str]:
    return [phrase for phrase in phrases if phrase not in text]


def check_phrase_group(text: str, phrases: list[str], label: str) -> list[str]:
    missing = missing_phrases(text, phrases)
    if missing:
        return [f"Missing {label} guidance: {', '.join(missing)}"]
    return []


REQUIRED_HELPER_INVOCATIONS = [
    (
        "references/install-and-preflight.md",
        "python3 scripts/patch_lvms_manifest.py",
        "LVMS manifest patch helper invocation",
    ),
    (
        "references/validation-hardening.md",
        "python3 scripts/render_smoke_manifest.py",
        "smoke manifest helper invocation",
    ),
    (
        "references/maintenance-uninstall.md",
        "scripts/post_uninstall_audit.sh",
        "post-uninstall audit helper invocation",
    ),
]


def check_helper_invocations(root: Path) -> list[str]:
    issues: list[str] = []
    for rel, needle, label in REQUIRED_HELPER_INVOCATIONS:
        path = root / rel
        text = read_text(path) if path.exists() else ""
        if needle not in text:
            issues.append(f"{rel}: missing {label}: {needle}")
    return issues


def check_version_sync(root: Path) -> list[str]:
    version_file = root / "VERSION"
    package_file = root / "package.json"
    if not version_file.exists():
        return ["Missing VERSION file."]
    if not package_file.exists():
        return ["Missing package.json file."]

    version = read_text(version_file).strip()
    try:
        package_data = json.loads(read_text(package_file))
    except json.JSONDecodeError:
        return ["package.json is not valid JSON."]

    package_name = package_data.get("name", "")
    package_version = package_data.get("version", "")
    issues: list[str] = []
    if package_name != EXPECTED_NAME:
        issues.append(f"package.json name '{package_name}' does not match '{EXPECTED_NAME}'.")
    if package_version != version:
        issues.append(
            f"VERSION ({version}) and package.json version ({package_version}) are out of sync."
        )
    return issues


def check_changelog_version(root: Path) -> list[str]:
    version_file = root / "VERSION"
    changelog_file = root / "CHANGELOG.md"
    if not changelog_file.exists():
        return ["Missing CHANGELOG.md file."]
    if not version_file.exists():
        return []

    version = read_text(version_file).strip()
    expected = {f"## {version}", f"## v{version}"}
    if any(line.strip() in expected for line in read_text(changelog_file).splitlines()):
        return []
    return [f"CHANGELOG.md does not contain a heading for VERSION '{version}'."]


README_VERSION_RE = re.compile(r"Current version:\s*\*\*(?P<version>[^*]+)\*\*")


def check_readme_version(root: Path) -> list[str]:
    version_file = root / "VERSION"
    readme_file = root / "README.md"
    if not readme_file.exists() or not version_file.exists():
        return []

    version = read_text(version_file).strip()
    match = README_VERSION_RE.search(read_text(readme_file))
    if match is None:
        return ["README.md: missing 'Current version: **<version>**' marker."]
    readme_version = match.group("version").strip()
    if readme_version != version:
        return [
            f"README.md version ({readme_version}) and VERSION ({version}) are out of sync."
        ]
    return []


def check_versions_handoff(skill_text: str) -> list[str]:
    match = re.search(
        r"^## Required Source Checks\s*$",
        skill_text,
        re.MULTILINE,
    )
    if not match:
        return ["SKILL.md: Required Source Checks missing openshift-versions handoff"]
    start = match.end()
    next_heading = re.search(r"^##\s+", skill_text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(skill_text)
    source_checks = skill_text[start:end]
    if "openshift-versions" not in source_checks:
        return [
            "SKILL.md: Required Source Checks missing openshift-versions handoff"
        ]
    lowered = source_checks.lower()
    if (
        "not cluster upgrade readiness" not in lowered
        or "release availability" not in lowered
    ):
        return [
            "SKILL.md: Required Source Checks must clarify that release availability "
            "is not cluster upgrade readiness"
        ]
    return []


def check_skill_file(root: Path) -> list[str]:
    skill_file = root / "SKILL.md"
    if not skill_file.exists():
        return ["Missing SKILL.md at package root."]

    issues = check_markdown_file(skill_file, root)
    skill_text = read_text(skill_file)
    line_count = len(skill_text.splitlines())
    if line_count > MAX_SKILL_LINES:
        issues.append(f"SKILL.md is {line_count} lines (> {MAX_SKILL_LINES}).")
    issues.extend(check_required_sections(skill_text))
    issues.extend(check_versions_handoff(skill_text))
    return issues


def validate_root(root: Path) -> list[str]:
    issues: list[str] = []
    skill_file = root / "SKILL.md"

    issues.extend(check_required_files(root))
    issues.extend(check_frontmatter(root))
    issues.extend(check_skill_file(root))
    issues.extend(check_expected_references(root))
    issues.extend(check_version_sync(root))
    issues.extend(check_changelog_version(root))
    issues.extend(check_readme_version(root))

    all_text = package_markdown_text(root)
    issues.extend(check_phrase_group(all_text, SAFETY_PHRASES, "destructive disk safety"))
    issues.extend(check_phrase_group(all_text, SNO_STORAGE_PHRASES, "SNO default StorageClass"))
    issues.extend(check_phrase_group(all_text, LVMS_PHRASES, "LVMS-specific guidance"))
    issues.extend(check_phrase_group(all_text, OPENSHIFT_PHRASES, "OpenShift SCC/MachineConfig/OLM"))
    issues.extend(check_phrase_group(all_text, UPGRADE_PHRASES, "upgrade safety"))
    issues.extend(check_helper_invocations(root))

    for md_file in sorted(root.rglob("*.md")):
        if md_file == skill_file:
            continue
        issues.extend(check_markdown_file(md_file, root))

    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = validate_root(root)

    if issues:
        print("Validation FAILED:\n")
        for issue in issues:
            print(f"- {issue}")
        print("\nFix the issues above and re-run validation.")
        return 1

    print("Validation PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
