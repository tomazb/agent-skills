#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

EXPECTED_NAME = "openshift-odf"
FENCE_RE = re.compile(r"^\s*```")
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)

EXPECTED_REFERENCES = [
    "references/install-and-preflight.md",
    "references/local-storage-disks.md",
    "references/block-rbd.md",
    "references/cephfs-filesystem.md",
    "references/object-mcg-rgw.md",
    "references/cluster-expand-shrink.md",
    "references/upgrade.md",
    "references/backup-restore-dr.md",
    "references/maintenance-uninstall.md",
    "references/validation-hardening.md",
    "references/validated-odf-sno.md",
]

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "VERSION",
    "CHANGELOG.md",
    "package.json",
    "assets/smoke-pvc-writer.yaml",
    "scripts/render_storagecluster.py",
    "scripts/post_uninstall_audit.sh",
    "scripts/render_smoke_manifest.py",
    "tools/validate_skill_package.py",
    "tools/validate_skill_package.sh",
]

REQUIRED_SKILL_SECTIONS = [
    "## Product Ownership Gate",
    "## Routing",
    "## Core Safety Rules",
    "## Required Source Checks",
    "## Inputs To Collect",
    "## Output Expectations",
]

OWNERSHIP_PEER_SKILL = "openshift-rook"

SAFETY_PHRASES = [
    "explicit destructive confirmation",
    "readlink -f",
    "lsblk -f",
    "wipefs -n",
    "ceph-volume lvm list",
    "/dev/disk/by-id/",
    "wipefs",
]

SNO_STORAGE_PHRASES = [
    "SNO",
    "replicated.size: 1",
    "requireSafeReplicaSize: false",
    "exactly one default StorageClass",
    "one default StorageClass",
]

# ODF service surface: block, filesystem, object, and the ODF-managed StorageCluster.
ODF_SERVICE_PHRASES = [
    "ceph-rbd",
    "CephFS",
    "RGW",
    "MCG",
    "StorageCluster",
    "ocs-storagecluster-ceph-rbd",
    "ocs-storagecluster-cephfs",
    "openshift-storage",
]

OPENSHIFT_PHRASES = [
    "MachineConfig",
    "reboot",
    "MCP",
    "SecurityContextConstraints",
    "SCC",
]

UPGRADE_PHRASES = [
    "Do not downgrade",
    "release notes",
    "HEALTH_OK",
    "active+clean",
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
    missing = [
        section
        for section in REQUIRED_SKILL_SECTIONS
        if not re.search(r"^" + re.escape(section) + r"\s*$", skill_text, re.MULTILINE)
    ]
    if missing:
        return [f"SKILL.md is missing required sections: {', '.join(missing)}"]
    return []


def extract_section(skill_text: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading.lstrip('# ').strip())}\s*$",
        skill_text,
        re.MULTILINE,
    )
    if not match:
        return None
    start = match.end()
    next_heading = re.search(r"^##\s+", skill_text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(skill_text)
    return skill_text[start:end]


def check_ownership_gate(skill_text: str) -> list[str]:
    """Require an evidence-based ODF vs Rook ownership gate before routing."""
    gate = extract_section(skill_text, "Product Ownership Gate")
    if gate is None:
        return ["SKILL.md: missing Product Ownership Gate section"]

    issues: list[str] = []
    routing = extract_section(skill_text, "Routing")
    gate_pos = skill_text.find("## Product Ownership Gate")
    routing_pos = skill_text.find("## Routing")
    if routing is not None and (routing_pos == -1 or gate_pos > routing_pos):
        issues.append(
            "SKILL.md: Product Ownership Gate must appear before Routing"
        )

    lowered = gate.lower()
    for marker in ("StorageCluster", "CephCluster"):
        if marker not in gate:
            issues.append(
                f"SKILL.md: Product Ownership Gate missing discovery marker '{marker}'"
            )
    if "Subscription" not in gate and "CSV" not in gate:
        issues.append(
            "SKILL.md: Product Ownership Gate missing ODF/OCS Subscription or CSV evidence"
        )
    if OWNERSHIP_PEER_SKILL not in gate:
        issues.append(
            f"SKILL.md: Product Ownership Gate missing handoff to '{OWNERSHIP_PEER_SKILL}'"
        )
    if "namespace" not in lowered:
        issues.append(
            "SKILL.md: Product Ownership Gate must warn that namespace presence alone is insufficient"
        )
    if not any(token in lowered for token in ("mixed", "conflict", "unknown", "insufficient")):
        issues.append(
            "SKILL.md: Product Ownership Gate must stop on mixed, conflicting, or unknown ownership"
        )
    if not any(
        token in lowered
        for token in ("stop", "do not", "never", "refuse", "hand off", "handoff")
    ):
        issues.append(
            "SKILL.md: Product Ownership Gate must refuse mutation until ownership is classified"
        )
    if "rook" not in lowered:
        issues.append(
            "SKILL.md: Product Ownership Gate must classify upstream Rook-owned clusters"
        )
    return issues


PHRASE_SCAN_EXCLUDES = {"README.md", "CHANGELOG.md"}

# Patterns that must NOT appear in the skill's markdown. On ODF, the StorageCluster
# is the source of truth; hand-editing the Rook CRs or applying upstream Rook
# manifests corrupts operator state.
FORBIDDEN_CONTENT_PATTERNS = [
    (
        re.compile(r"operator-openshift\.yaml", re.MULTILINE),
        "upstream Rook operator manifest (ODF installs via OLM Subscription)",
    ),
    (
        re.compile(r"helm\s+install\s+rook-ceph", re.MULTILINE),
        "Helm install of upstream Rook (ODF is OLM-managed)",
    ),
    (
        re.compile(r"^\s*port:\s*80\s*$", re.MULTILINE),
        "RGW 'port: 80' (non-root RGW cannot bind privileged ports on OpenShift)",
    ),
]

# Substrings that must appear somewhere in the skill's markdown.
REQUIRED_CONTENT_SUBSTRINGS = [
    ("autoscale", "PG autoscaler guidance (the autoscaler is on by default)"),
    ("odf-operator", "ODF operator installed through OLM Subscription"),
    ("enableCephTools", "toolbox enablement via OCSInitialization"),
    (
        "cluster.ocs.openshift.io/openshift-storage",
        "storage node labeling for ODF scheduling",
    ),
]


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


def check_content_regressions(root: Path) -> list[str]:
    issues: list[str] = []
    files = [
        path
        for path in sorted(root.rglob("*.md"))
        if path.name not in PHRASE_SCAN_EXCLUDES
    ]
    for path in files:
        text = read_text(path)
        rel = str(path.relative_to(root))
        for pattern, label in FORBIDDEN_CONTENT_PATTERNS:
            if pattern.search(text):
                issues.append(f"{rel}: forbidden pattern — {label}")

    all_text = "\n".join(read_text(path) for path in files)
    for needle, label in REQUIRED_CONTENT_SUBSTRINGS:
        if needle not in all_text:
            issues.append(f"Missing required guidance: {label} ('{needle}')")
    return issues


def check_required_reference_guidance(root: Path) -> list[str]:
    issues: list[str] = []

    _cache: dict[str, str] = {}

    def read_reference(rel: str) -> str:
        if rel not in _cache:
            path = root / rel
            _cache[rel] = read_text(path) if path.exists() else ""
        return _cache[rel]

    def require(rel: str, label: str, needles: list[str]) -> None:
        text = read_reference(rel)
        missing = [needle for needle in needles if needle not in text]
        if missing:
            issues.append(f"{rel}: missing {label}: {', '.join(missing)}")

    def require_order(rel: str, label: str, needles: list[str]) -> None:
        text = read_reference(rel)
        pos = -1
        for needle in needles:
            next_pos = text.find(needle, pos + 1)
            if next_pos == -1:
                issues.append(f"{rel}: missing ordered {label}: {needle}")
                return
            pos = next_pos

    require(
        "references/install-and-preflight.md",
        "OLM install guidance",
        [
            "openshift-storage",
            "openshift.io/cluster-monitoring",
            "OperatorGroup",
            "packagemanifest odf-operator",
            "name: odf-operator",
            "cluster.ocs.openshift.io/openshift-storage",
            "monDataDirHostPath",
            "enableCephTools",
            "python3 scripts/render_storagecluster.py",
        ],
    )
    require_order(
        "references/install-and-preflight.md",
        "OLM install ordering",
        [
            "kind: Namespace",
            "kind: OperatorGroup",
            "kind: Subscription",
            "kind: StorageCluster",
        ],
    )
    require(
        "references/local-storage-disks.md",
        "Local Storage Operator disk prep guidance",
        [
            "local-storage-operator",
            "LocalVolumeDiscovery",
            "LocalVolumeSet",
            "localblock",
            "deviceInclusionSpec",
        ],
    )
    require(
        "references/upgrade.md",
        "OLM upgrade guidance",
        [
            "installPlanApproval",
            "installplan",
            "ceph versions",
            "interoperability",
        ],
    )
    require(
        "references/object-mcg-rgw.md",
        "MCG/RGW OBC validation guidance",
        [
            "openshift-storage.noobaa.io",
            "ObjectBucketClaim",
            "ObjectBucket",
            "ocs-storagecluster-ceph-rgw",
            "cephObjectStores",
        ],
    )
    require(
        "references/cluster-expand-shrink.md",
        "supported OSD removal guidance",
        [
            "ocs-osd-removal",
            "FAILED_OSD_IDS",
            "storageDeviceSets",
        ],
    )
    require(
        "references/cluster-expand-shrink.md",
        "BlueStore disk reuse guidance",
        [
            "BlueStore",
            "full-disk zero",
        ],
    )
    require(
        "references/maintenance-uninstall.md",
        "ODF uninstall guidance",
        [
            "uninstall.ocs.openshift.io/cleanup-policy",
            "uninstall.ocs.openshift.io/mode",
            "delete storagecluster",
            "post_uninstall_audit.sh",
        ],
    )
    require(
        "references/maintenance-uninstall.md",
        "BlueStore disk reuse guidance",
        [
            "BlueStore",
            "full-disk zero",
        ],
    )
    require(
        "references/validation-hardening.md",
        "ODF validation/monitoring guidance",
        [
            "enableCephTools",
            "Data Foundation",
            "rbd-smoke-writer",
            "cephfs-smoke-writer",
            "python3 scripts/render_smoke_manifest.py",
        ],
    )
    require(
        "references/validated-odf-sno.md",
        "validated SNO evidence",
        [
            "ocs-storagecluster-ceph-rbd",
            "openshift-storage.noobaa.io",
            "localblock",
            "HEALTH_OK",
        ],
    )
    forbid_pattern_rel = "references/install-and-preflight.md"
    if re.search(
        r"operator-openshift\.yaml", read_reference(forbid_pattern_rel), re.MULTILINE
    ):
        issues.append(
            f"{forbid_pattern_rel}: forbidden upstream Rook operator manifest reference"
        )

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
    issues.extend(check_ownership_gate(skill_text))
    issues.extend(check_versions_handoff(skill_text))
    if "references/validated-odf-sno.md" not in skill_text:
        issues.append("SKILL.md: missing validated ODF SNO routing guidance.")
    return issues


def check_versions_handoff(skill_text: str) -> list[str]:
    source_checks = extract_section(skill_text, "Required Source Checks") or ""
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
    issues.extend(check_phrase_group(all_text, SNO_STORAGE_PHRASES, "SNO replica/default StorageClass"))
    issues.extend(check_phrase_group(all_text, ODF_SERVICE_PHRASES, "ODF storage services"))
    issues.extend(check_phrase_group(all_text, OPENSHIFT_PHRASES, "OpenShift SCC/MachineConfig"))
    issues.extend(check_phrase_group(all_text, UPGRADE_PHRASES, "upgrade safety"))
    issues.extend(check_content_regressions(root))
    issues.extend(check_required_reference_guidance(root))

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
