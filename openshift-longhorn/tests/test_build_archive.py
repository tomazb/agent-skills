from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import zipfile


def load_build_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "build_skill_artifacts.py"
    spec = importlib.util.spec_from_file_location("build_skill_artifacts", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_includes_package_files_and_excludes_generated_artifacts(tmp_path):
    module = load_build_module()
    skill_dir = Path(__file__).resolve().parents[1]
    # Plant a generated artifact under an archived directory (tools/) so the test
    # actually proves __pycache__/.pyc exclusion. Use an isolated dir we fully own
    # and never touch a shared cache directory in teardown.
    pycache = skill_dir / "tools" / "__pycache__"
    preexisting = pycache.exists()
    pycache.mkdir(exist_ok=True)
    generated = pycache / "generated.pyc"
    generated.write_bytes(b"generated")

    try:
        archive_path = module.build_archive(skill_dir, tmp_path)
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
    finally:
        generated.unlink(missing_ok=True)
        if not preexisting:
            shutil.rmtree(pycache, ignore_errors=True)

    required = {
        "openshift-longhorn/SKILL.md",
        "openshift-longhorn/README.md",
        "openshift-longhorn/package.json",
        "openshift-longhorn/VERSION",
        "openshift-longhorn/CHANGELOG.md",
        "openshift-longhorn/references/install-and-preflight.md",
        "openshift-longhorn/references/v2-block-data-engine.md",
        "openshift-longhorn/references/validated-v2-ocp422-sno.md",
        "openshift-longhorn/tools/validate_skill_package.py",
        "openshift-longhorn/tools/validate_skill_package.sh",
    }
    assert required.issubset(names)
    assert all("__pycache__/" not in name for name in names)
    assert all(not name.endswith(".pyc") for name in names)
    # The development test suite is not shipped in the packaged skill, so the
    # archive stays self-contained and does not depend on repo-root scripts/.
    assert all("/tests/" not in name for name in names)
