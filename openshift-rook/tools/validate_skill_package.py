#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

EXPECTED_NAME = "openshift-rook"
FENCE_RE = re.compile(r"^\s*```")
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)

EXPECTED_REFERENCES = [
    "references/install-and-preflight.md",
    "references/osd-disk-prep.md",
    "references/rbd-block-pools.md",
    "references/cephfs-filesystem.md",
    "references/rgw-object-store.md",
    "references/cluster-expand-shrink.md",
    "references/upgrade.md",
    "references/backup-restore-dr.md",
    "references/maintenance-uninstall.md",
    "references/validation-hardening.md",
    "references/validated-rook-ceph-sno.md",
]

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "VERSION",
    "CHANGELOG.md",
    "package.json",
    "assets/smoke-pvc-writer.yaml",
    "scripts/patch_rook_ceph_manifest.py",
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

OWNERSHIP_PEER_SKILL = "openshift-odf"

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

CEPH_SERVICE_PHRASES = [
    "RBD",
    "CephFS",
    "RGW",
    "cephblockpool",
    "cephfilesystem",
    "cephobjectstore",
    "mon.count",
    "mgr.count",
]

OPENSHIFT_PHRASES = [
    "MachineConfig",
    "reboot",
    "MCP",
    "privileged",
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
    """Require an evidence-based Rook vs ODF ownership gate before routing."""
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
    if "odf" not in lowered:
        issues.append(
            "SKILL.md: Product Ownership Gate must classify ODF-owned clusters"
        )
    return issues


PHRASE_SCAN_EXCLUDES = {"README.md", "CHANGELOG.md"}

# Patterns that must NOT appear in the skill's markdown (regressions fixed in v1.1.0).
FORBIDDEN_CONTENT_PATTERNS = [
    (
        re.compile(r"^\s*type:\s*s3\b", re.MULTILINE),
        "invalid CephObjectStore gateway field 'type: s3' (no such field)",
    ),
    (
        re.compile(r"^\s*port:\s*80\s*$", re.MULTILINE),
        "RGW 'port: 80' (non-root RGW cannot bind privileged ports on OpenShift; use 8080)",
    ),
    (
        re.compile(r"^\s*securePort:\s*443\s*$", re.MULTILINE),
        "RGW 'securePort: 443' (use a non-privileged port such as 8443 on OpenShift)",
    ),
]

# Substrings that must appear somewhere in the skill's markdown.
REQUIRED_CONTENT_SUBSTRINGS = [
    ("autoscale", "PG autoscaler guidance (the autoscaler is on by default)"),
    ("operator-openshift.yaml", "OpenShift operator manifest with dedicated SCC"),
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

    def forbid_pattern(rel: str, pattern: re.Pattern[str], label: str) -> None:
        text = read_reference(rel)
        if pattern.search(text):
            issues.append(f"{rel}: forbidden {label}")

    require(
        "references/install-and-preflight.md",
        "direct-manifest install guidance",
        [
            "oc create ns rook-ceph",
            "csi-operator.yaml",
            "CephConnection",
            "/dev/disk/by-id/<stable-disk-id>",
            "osd_pool_default_size",
            "mon_warn_on_pool_no_redundancy",
            "mon_max_pg_per_osd",
            "ceph mgr module enable rook",
            "ceph orch set backend rook",
            "useAllDevices: false",
            "python3 scripts/patch_rook_ceph_manifest.py",
        ],
    )
    require_order(
        "references/install-and-preflight.md",
        "CSI/operator manifest ordering",
        [
            "curl -fsSLo /tmp/rook-ceph-csi-operator.yaml",
            "curl -fsSLo /tmp/rook-ceph-operator.yaml",
            "oc create ns rook-ceph",
            "oc apply --server-side --force-conflicts -f /tmp/rook-ceph-crds.yaml",
            "oc apply -f /tmp/rook-ceph-common.yaml",
            "oc apply -f /tmp/rook-ceph-csi-operator.yaml",
            "oc apply -f /tmp/rook-ceph-operator.yaml",
        ],
    )
    require(
        "references/upgrade.md",
        "manifest upgrade guidance",
        [
            "csi-operator.yaml",
            "CephConnection",
        ],
    )
    require_order(
        "references/upgrade.md",
        "upgrade CSI/operator ordering",
        [
            "curl -fsSLo /tmp/rook-ceph-csi-operator.yaml",
            "curl -fsSLo /tmp/rook-ceph-operator.yaml",
            "oc apply --server-side --force-conflicts -f /tmp/rook-ceph-crds.yaml",
            "oc apply -f /tmp/rook-ceph-common.yaml",
            "oc apply -f /tmp/rook-ceph-csi-operator.yaml",
            "oc apply -f /tmp/rook-ceph-operator.yaml",
        ],
    )
    require(
        "references/rgw-object-store.md",
        "RGW OBC/route validation guidance",
        [
            "ObjectBucket",
            "Ceph Object Gateway",
            "TLS or connection failure",
            "curl -kI",
        ],
    )
    forbid_pattern(
        "references/rgw-object-store.md",
        re.compile(r"HTTP 200", re.MULTILINE),
        "RGW route validation that requires HTTP 200",
    )
    require(
        "references/validation-hardening.md",
        "dashboard/orchestrator guidance",
        [
            "http-dashboard",
            "internal Prometheus",
            "PROMETHEUS_API_HOST",
            "ceph mgr module enable rook",
            "ceph orch set backend rook",
            "python3 scripts/render_smoke_manifest.py",
        ],
    )
    require(
        "references/maintenance-uninstall.md",
        "post-uninstall audit helper invocation",
        [
            "scripts/post_uninstall_audit.sh",
        ],
    )
    require(
        "references/validated-rook-ceph-sno.md",
        "validated SNO evidence",
        [
            "v1.20.2",
            "v20.2.2",
            "mon_max_pg_per_osd",
            "rook-ceph-rgw-obc",
            "Backend: rook",
        ],
    )
    forbid_pattern(
        "references/install-and-preflight.md",
        re.compile(
            r"^oc apply -f /tmp/rook-ceph-operator\.yaml\s*$.*?^oc apply -f /tmp/rook-ceph-csi-operator\.yaml\s*$",
            re.MULTILINE | re.DOTALL,
        ),
        "install guidance that applies operator before csi-operator",
    )
    forbid_pattern(
        "references/install-and-preflight.md",
        re.compile(
            r"^oc apply -f /tmp/rook-ceph-csi-operator\.yaml\s*$.*?^oc apply -f /tmp/rook-ceph-common\.yaml\s*$",
            re.MULTILINE | re.DOTALL,
        ),
        "install guidance that applies csi-operator before common.yaml",
    )
    forbid_pattern(
        "references/install-and-preflight.md",
        re.compile(
            r"^oc apply -f /tmp/rook-ceph-common\.yaml\s*$.*?oc create ns rook-ceph",
            re.MULTILINE | re.DOTALL,
        ),
        "install guidance that creates namespace after common.yaml",
    )
    forbid_pattern(
        "references/upgrade.md",
        re.compile(
            r"^oc apply -f /tmp/rook-ceph-operator\.yaml\s*$.*?^oc apply -f /tmp/rook-ceph-csi-operator\.yaml\s*$",
            re.MULTILINE | re.DOTALL,
        ),
        "upgrade guidance that applies operator before csi-operator",
    )
    forbid_pattern(
        "references/upgrade.md",
        re.compile(
            r"^oc apply -f /tmp/rook-ceph-csi-operator\.yaml\s*$.*?^oc apply -f /tmp/rook-ceph-common\.yaml\s*$",
            re.MULTILINE | re.DOTALL,
        ),
        "upgrade guidance that applies csi-operator before common.yaml",
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
    return issues


def check_versions_handoff(skill_text: str) -> list[str]:
    source_checks = extract_section(skill_text, "Required Source Checks") or ""
    if "openshift-versions" not in source_checks:
        return [
            "SKILL.md: Required Source Checks missing openshift-versions handoff"
        ]
    lowered = source_checks.lower()
    if "not cluster upgrade readiness" not in lowered and "release availability" not in lowered:
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
    issues.extend(check_phrase_group(all_text, CEPH_SERVICE_PHRASES, "Ceph service types"))
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
