from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "tools" / "validate_skill_package.py"


def make_skill_text(*, name: str = "openshift-longhorn", missing_sections: list[str] | None = None) -> str:
    missing = set(missing_sections or [])
    lines = [
        "---",
        f"name: {name}",
        "description: Use when demo validation is needed.",
        "---",
        "",
        "# OpenShift Longhorn Lifecycle",
        "",
        "## Routing",
        "",
        "Routing guidance.",
        "",
        "## Core Safety Rules",
        "",
        "Safety guidance.",
        "",
        "## Required Source Checks",
        "",
        "Source guidance. Use `openshift-versions` for channel questions. "
        "Release availability is not cluster upgrade readiness.",
        "",
        "## Inputs To Collect",
        "",
        "Input guidance.",
        "",
        "## Output Expectations",
        "",
        "Output guidance.",
        "",
    ]
    filtered: list[str] = []
    skip_next_blank = False
    for line in lines:
        if line in missing:
            skip_next_blank = True
            continue
        if skip_next_blank and line == "":
            skip_next_blank = False
            continue
        filtered.append(line)
    return "\n".join(filtered).rstrip() + "\n"


def reference_text() -> str:
    return """
# Reference

Use explicit destructive confirmation before mkfs or wipefs. Verify the exact
/dev/disk/by-id/ target with readlink -f, lsblk -f, findmnt, and wipefs -n.
SNO uses numberOfReplicas: "1" and default-replica-count with exactly one default StorageClass
and one default StorageClass reminder. V2 requires raw block disks,
hugepagesz=2M, hugepages=1024, vfio_pci, uio_pci_generic, nvme_tcp, privileged SCC,
and longhorn-preflight-checker cleanup with remove-scc-from-user. OpenShift
MachineConfig can reboot nodes; wait for MCP. Use YAML-aware manifest patching
for oauth-proxy. Do not downgrade Longhorn. Do not skip unsupported minor
versions. Ensure V2 Data Engine volumes are detached and create a system backup
before upgrade. Use `python3 scripts/patch_longhorn_okd_manifest.py` for OKD
manifest patching. Use `python3 scripts/render_smoke_manifest.py` for smoke
writers. Run `bash scripts/post_uninstall_audit.sh` after uninstall.
""".lstrip()


@pytest.fixture(scope="session")
def validator():
    spec = importlib.util.spec_from_file_location("validate_skill_package", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def package_factory(tmp_path, validator):
    counter = 0

    def _make(
        *,
        skill_text: str | None = None,
        include_references: bool = True,
        reference_content: str | None = None,
        include_version: bool = True,
        include_changelog: bool = True,
        include_package_json: bool = True,
        package_json_text: str | None = None,
        changelog_text: str | None = None,
    ) -> Path:
        nonlocal counter
        counter += 1
        root = tmp_path / f"pkg_{counter}"
        root.mkdir(parents=True, exist_ok=True)

        (root / "SKILL.md").write_text(skill_text or make_skill_text(), encoding="utf-8")
        (root / "README.md").write_text("# OpenShift Longhorn\n\nCurrent version: **1.2.3**\n", encoding="utf-8")

        tools = root / "tools"
        tools.mkdir()
        (tools / "validate_skill_package.py").write_text("# validator\n", encoding="utf-8")
        (tools / "validate_skill_package.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

        scripts = root / "scripts"
        scripts.mkdir()
        (scripts / "patch_longhorn_okd_manifest.py").write_text(
            "#!/usr/bin/env python3\n", encoding="utf-8"
        )
        (scripts / "post_uninstall_audit.sh").write_text(
            "#!/usr/bin/env bash\n", encoding="utf-8"
        )
        (scripts / "render_smoke_manifest.py").write_text(
            "#!/usr/bin/env python3\n", encoding="utf-8"
        )

        assets = root / "assets"
        assets.mkdir()
        (assets / "smoke-pvc-writer.yaml").write_text(
            "apiVersion: v1\nkind: Pod\nmetadata:\n  name: writer\n", encoding="utf-8"
        )

        if include_references:
            content = reference_content or reference_text()
            for rel in validator.EXPECTED_REFERENCES:
                ref = root / rel
                ref.parent.mkdir(parents=True, exist_ok=True)
                ref.write_text(content, encoding="utf-8")

        if include_version:
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        if include_changelog:
            (root / "CHANGELOG.md").write_text(
                changelog_text or "# Changelog\n\n## 1.2.3\n\n- Test.\n",
                encoding="utf-8",
            )
        if include_package_json:
            (root / "package.json").write_text(
                package_json_text
                or json.dumps({"name": "openshift-longhorn", "version": "1.2.3"}, indent=2) + "\n",
                encoding="utf-8",
            )
        return root

    return _make


@pytest.fixture(name="make_skill_text")
def make_skill_text_fixture():
    return make_skill_text


@pytest.fixture(name="reference_text")
def reference_text_fixture():
    return reference_text
