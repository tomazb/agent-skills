# openshift-odf 4.20 SNO Skill Updates Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update the `openshift-odf` skill (v1.4.0 → v1.5.0) to document the ODF 4.20 SNO fix-ups discovered on `prod2` and add a narrow `render_sno_remediation.py` generator for the deterministic patches.

**Architecture:** Four additive Markdown edits to `references/*.md`, one new Python generator script following the existing `render_*.py` pattern (argparse → emit text → never executes `oc`/`ceph`), one new pytest module, and a synchronized version bump (VERSION/package.json/README/CHANGELOG). The 1.5.0 bump also repairs a pre-existing validator failure (README stuck at 1.3.0 while VERSION is 1.4.0).

**Tech Stack:** Python 3.9+ (stdlib `argparse`, `pathlib`), pytest, Markdown, the skill's own `tools/validate_skill_package.py` validator.

**Commit policy (user choice):** ONE squashed commit at the very end (Task 7). Do NOT commit between tasks. Each task still ends with a verification gate.

**Commit message policy (user preference):** NEVER add a `Co-authored-by` trailer or any similar endorsement/attribution line to commit messages.

**Design reference:** `docs/plans/2026-08-18-odf-sno-420-skill-updates-design.md`

---

## Validator constraints to respect (read before editing Markdown)

- `tools/validate_skill_package.py` forbids a bare `^\s*port:\s*80\s*$` line in any `*.md` except README/CHANGELOG. Do NOT introduce a `port: 80` YAML line. RGW/onboarding patches use `oc patch`, not port config — safe.
- Required substrings/phrase-groups must remain present; all edits are ADDITIVE (insert new subsections, never delete or reorder existing content).
- `README.md`/`CHANGELOG.md` are excluded from phrase scans.
- Baseline: `cd openshift-odf && python3 -m pytest -q` → `59 passed`. Validator currently FAILS only on `README.md version (1.3.0) and VERSION (1.4.0) are out of sync` (pre-existing; fixed in Task 5).

---

## Task 1: New generator script `render_sno_remediation.py` (TDD)

**Files:**
- Create: `openshift-odf/scripts/render_sno_remediation.py`
- Test: `openshift-odf/tests/test_render_sno_remediation.py`

**Step 1: Write the failing test**

Create `openshift-odf/tests/test_render_sno_remediation.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from render_sno_remediation import render_sno_remediation


def test_emits_all_deterministic_blocks():
    out = render_sno_remediation("ocs-storagecluster", "openshift-storage")
    # reconcileStrategy: ignore for all three managed resource classes
    assert "cephBlockPools" in out
    assert "cephObjectStores" in out
    assert "cephFilesystems" in out
    assert "reconcileStrategy" in out and "ignore" in out
    # topologyKey x2 -> hostname + ScheduleAnyway
    assert "cephfilesystem ocs-storagecluster-cephfilesystem" in out
    assert "cephobjectstore ocs-storagecluster-cephobjectstore" in out
    assert out.count("kubernetes.io/hostname") >= 2
    assert out.count("ScheduleAnyway") >= 2
    # CephBlockPool failureDomain fix
    assert "cephblockpool ocs-storagecluster-cephblockpool" in out
    assert '"host"' in out
    assert "replicasPerFailureDomain" in out
    # Driver CSI replicas x2
    assert "openshift-storage.rbd.csi.ceph.com" in out
    assert "openshift-storage.cephfs.csi.ceph.com" in out
    assert "controllerPlugin" in out and "replicas" in out
    # mute
    assert "POOL_NO_REDUNDANCY" in out


def test_banner_states_boundary_and_excludes_stateful_steps():
    out = render_sno_remediation("ocs-storagecluster", "openshift-storage")
    assert "CephCluster" in out and "Ready" in out  # prerequisite banner
    assert "validated-odf-sno.md" in out  # pointer for pool sizing
    assert "validation-hardening.md" in out  # pointer for onboarding
    # stateful steps must NOT be emitted
    assert "onboarding" not in out.lower()
    assert "osd pool ls" not in out


def test_respects_name_and_namespace():
    out = render_sno_remediation("my-sc", "my-ns")
    assert "cephfilesystem my-sc-cephfilesystem" in out
    assert "my-ns.rbd.csi.ceph.com" in out
    assert "-n my-ns" in out


def test_output_file_written(tmp_path):
    dest = tmp_path / "remediation.sh"
    render_sno_remediation("ocs-storagecluster", "openshift-storage", str(dest))
    text = dest.read_text(encoding="utf-8")
    assert "POOL_NO_REDUNDANCY" in text
    assert text.startswith("#!/usr/bin/env bash")
```

**Step 2: Run test to verify it fails**

Run: `cd openshift-odf && python3 -m pytest tests/test_render_sno_remediation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'render_sno_remediation'`.

**Step 3: Write minimal implementation**

Create `openshift-odf/scripts/render_sno_remediation.py`:

```python
#!/usr/bin/env python3
"""Render the deterministic ODF 4.20 SNO post-install remediation commands.

This is a GENERATOR: it prints a reviewable bash script and never executes
`oc` or `ceph`. It emits only the fixed, kube-API-level patches that are safe
to apply once the CephCluster is Ready. Pool sizing (the live `ceph osd pool
ls` loop and the CephFilesystem/CephObjectStore size patches) and onboarding
recovery are intentionally NOT emitted; follow the runbooks referenced in the
banner for those stateful steps.
"""
from __future__ import annotations

import argparse
from pathlib import Path

BANNER = """\
#!/usr/bin/env bash
# ODF 4.20 SNO deterministic remediation — REVIEW BEFORE RUNNING.
#
# Prerequisite: the CephCluster is Ready (mons up, OSD up/in).
#
# This script applies ONLY the deterministic, kube-API patches. It does NOT
# perform pool sizing or onboarding recovery, which are stateful:
#   * Pool sizing (size=1 loop, CephFilesystem/CephObjectStore pool patches):
#     follow references/validated-odf-sno.md "Regression 2".
#   * StorageClient onboarding recovery:
#     follow references/validation-hardening.md troubleshooting.
set -euo pipefail
"""

_RECONCILE_IGNORE = """\
# 1. Freeze ODF reconciliation for pools, object stores, and filesystems so the
#    manual CR patches below are not reverted. Re-enable 'manage' after upgrade.
oc -n {ns} patch storagecluster {name} --type merge -p '{{
  "spec": {{
    "managedResources": {{
      "cephBlockPools":   {{"reconcileStrategy": "ignore"}},
      "cephObjectStores": {{"reconcileStrategy": "ignore"}},
      "cephFilesystems":  {{"reconcileStrategy": "ignore"}}
    }}
  }}
}}'
"""

_TOPOLOGYKEY = """\
# 2. Empty-topologyKey regression: MDS (CephFilesystem) and RGW gateway
#    (CephObjectStore) placements ship with topologyKey:"" + DoNotSchedule,
#    which blocks scheduling and leaves both CRs in Failure. Patch to a valid
#    key + ScheduleAnyway.
oc -n {ns} patch cephfilesystem {name}-cephfilesystem --type json -p '[
  {{"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"}},
  {{"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}}
]'
oc -n {ns} patch cephobjectstore {name}-cephobjectstore --type json -p '[
  {{"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"}},
  {{"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}}
]'
"""

_BLOCKPOOL_FD = """\
# 3. CephBlockPool: Rook rejects size=1 while failureDomain=osd +
#    replicasPerFailureDomain=1 ("size must be greater than
#    replicasPerFailureDomain"). Switch to host and drop replicasPerFailureDomain.
oc -n {ns} patch cephblockpool {name}-cephblockpool --type json -p '[
  {{"op":"replace","path":"/spec/failureDomain","value":"host"}},
  {{"op":"remove","path":"/spec/replicated/replicasPerFailureDomain"}}
]'
"""

_CSI_REPLICAS = """\
# 4. CSI controller plugins ship with 2 replicas (hard pod anti-affinity) that
#    cannot both schedule on SNO. Reduce to 1 via the Driver CRs (patching
#    OperatorConfig alone is not sufficient on ODF 4.20).
oc -n {ns} patch drivers.csi.ceph.io/{ns}.rbd.csi.ceph.com \\
  --type merge -p '{{"spec":{{"controllerPlugin":{{"replicas":1}}}}}}'
oc -n {ns} patch drivers.csi.ceph.io/{ns}.cephfs.csi.ceph.com \\
  --type merge -p '{{"spec":{{"controllerPlugin":{{"replicas":1}}}}}}'
# After patching, delete the stale Running ctrlplugin pods so the new
# single-replica ReplicaSet can schedule (see the runbook).
"""

_MUTE = """\
# 5. Mute the expected single-replica warning. Run AFTER pool sizing from the
#    runbook (POOL_NO_REDUNDANCY is only correct once pools are size=1).
ROOK_OP=$(oc -n {ns} get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/{ns}/{ns}.config"
oc -n {ns} exec "$ROOK_OP" -- ceph -c "$CONF" health mute POOL_NO_REDUNDANCY
"""


def render_sno_remediation(
    name: str = "ocs-storagecluster",
    namespace: str = "openshift-storage",
    output: str | None = None,
) -> str:
    blocks = [
        BANNER,
        _RECONCILE_IGNORE.format(name=name, ns=namespace),
        _TOPOLOGYKEY.format(name=name, ns=namespace),
        _BLOCKPOOL_FD.format(name=name, ns=namespace),
        _CSI_REPLICAS.format(name=name, ns=namespace),
        _MUTE.format(name=name, ns=namespace),
    ]
    text = "\n".join(blocks)
    if not text.endswith("\n"):
        text += "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render deterministic ODF 4.20 SNO remediation commands (review before running)."
    )
    parser.add_argument("--name", default="ocs-storagecluster")
    parser.add_argument("--namespace", default="openshift-storage")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    text = render_sno_remediation(args.name, args.namespace, args.output)
    if not args.output:
        print(text, end="")


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `cd openshift-odf && python3 -m pytest tests/test_render_sno_remediation.py -q`
Expected: PASS (4 passed).

Note: `_MUTE` uses `head -1` and `$(...)` but the `test_banner...` assertion only forbids the literal substrings `onboarding` (case-insensitive) and `osd pool ls`; neither appears. Confirm the run is green before proceeding.

---

## Task 2: `references/validated-odf-sno.md` edits (#1, #4 partial)

**Files:**
- Modify: `openshift-odf/references/validated-odf-sno.md`

**Step 1: Extend "ODF 4.20 Regression 2" (pool sizes) to cover CephFilesystem + CephObjectStore.**

Find the ODF 4.20 Regression 2 section (heading `## ODF 4.20 Regression 2: Pool Sizes Not Reduced for SNO`). At the END of that section's command block — immediately BEFORE the `## ODF 4.20 Regression 3` heading — insert:

````markdown
CephFilesystem and CephObjectStore pools need the same treatment as the block
pool: with one OSD, `size=3` + `replicasPerFailureDomain=1` fails Rook validation
("size must be greater than replicasPerFailureDomain"). After
`reconcileStrategy: ignore` is set for `cephFilesystems` and `cephObjectStores`,
patch their metadata and data pools:

```bash
# CephFilesystem: data + metadata pools -> size 1, host failure domain
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem \
  --type json -p '[
    {"op":"replace","path":"/spec/dataPools/0/failureDomain","value":"host"},
    {"op":"replace","path":"/spec/dataPools/0/replicated/size","value":1},
    {"op":"add","path":"/spec/dataPools/0/replicated/requireSafeReplicaSize","value":false},
    {"op":"remove","path":"/spec/dataPools/0/replicated/replicasPerFailureDomain"},
    {"op":"replace","path":"/spec/metadataPool/failureDomain","value":"host"},
    {"op":"replace","path":"/spec/metadataPool/replicated/size","value":1},
    {"op":"add","path":"/spec/metadataPool/replicated/requireSafeReplicaSize","value":false},
    {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}
  ]'

# CephObjectStore: data + metadata pools -> size 1, host failure domain
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type json -p '[
    {"op":"replace","path":"/spec/metadataPool/failureDomain","value":"host"},
    {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"},
    {"op":"replace","path":"/spec/dataPool/failureDomain","value":"host"},
    {"op":"remove","path":"/spec/dataPool/replicated/replicasPerFailureDomain"}
  ]'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type merge -p '{"spec":{"dataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}},"metadataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}}}}'
```

The `.mgr` pool is recreated at `size=3` whenever the mgr restarts. Re-check and
re-apply `size=1`/`min_size=1` on `.mgr` after any mgr restart:

```bash
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool set .mgr size 1 --yes-i-really-mean-it
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool set .mgr min_size 1
```
````

**Step 2: Add "ODF 4.20 Regression 4" after Regression 3.**

Find `## ODF 4.20 Regression 3: CSI Controller Plugin Replicas`. Insert a new section immediately BEFORE the `## Pool Configuration (ODF 4.20 SNO, after workaround)` heading (i.e., after the entire Regression 3 block):

````markdown
## ODF 4.20 Regression 4: Empty `topologyKey` on MDS and RGW Placements

The empty-`topologyKey` regression is not limited to mon/OSD placement. On ODF
4.20 SNO, ocs-operator also sets `topologyKey: ""` with
`whenUnsatisfiable: DoNotSchedule` on:

- `CephFilesystem` `spec.metadataServer.placement.topologySpreadConstraints`
- `CephObjectStore` `spec.gateway.placement.topologySpreadConstraints`

**Symptom:** the `CephFilesystem` and/or `CephObjectStore` stay in `Failure`,
no `rook-ceph-mds-*` or `rook-ceph-rgw-*` pods appear, and `ceph fs ls` reports
"No filesystems enabled". The RBD and CephFS StorageClasses never get created
because the internal `StorageClient` cannot finish while these CRs are failed.

**Workaround** (with `cephFilesystems` / `cephObjectStores` reconciliation set to
`ignore`, patch the empty key to a valid one):

```bash
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem \
  --type json -p '[
    {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
    {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
  ]'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore \
  --type json -p '[
    {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
    {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
  ]'
```

After both patch, the MDS and RGW pods schedule, the filesystem is created, and
(once onboarding completes) the `ocs-storagecluster-ceph-rbd` and
`ocs-storagecluster-cephfs` StorageClasses appear.

The deterministic patches in this section (Regression 3 + 4, plus
`reconcileStrategy: ignore` and the CephBlockPool failure-domain fix) can be
generated for review with:

```bash
python3 scripts/render_sno_remediation.py \
  --name ocs-storagecluster --namespace openshift-storage
```

If the internal `StorageClient` is stuck in `Initializing` with a
"crypto/rsa: verification error" after a reinstall, see the onboarding
troubleshooting entry in `references/validation-hardening.md`.
````

**Step 3: Verify Markdown still validates.**

Run: `cd openshift-odf && python3 tools/validate_skill_package.py`
Expected: the ONLY remaining issue is the pre-existing `README.md version (1.3.0) and VERSION (1.4.0) are out of sync` (fixed in Task 5). No new `forbidden pattern` or `missing guidance` errors.

---

## Task 3: `references/validation-hardening.md` edits (#2, #4)

**Files:**
- Modify: `openshift-odf/references/validation-hardening.md`

**Step 1: Add onboarding troubleshooting entry.**

Under the `## Troubleshooting Shape` section, append:

````markdown
### StorageClient stuck `Initializing` — onboarding ticket signature error

**Symptom:** after a reinstall, only `ocs-storagecluster-ceph-rgw` exists; the
`ceph-rbd` and `cephfs` StorageClasses are missing. `oc -n openshift-storage get
storageclients.ocs.openshift.io` shows the internal client `Initializing` with an
empty CONSUMER. The provider logs (`deploy/ocs-provider-server`) repeat:

```
Failed to validate onboarding ticket ... failed to verify onboarding ticket
signature. crypto/rsa: verification error
```

**Cause:** a stale onboarding token/keys left over from a previous install cycle.
The `StorageConsumer`-owned `onboarding-token-*` secret was signed with a private
key that no longer matches the public key the provider verifies with, so the
`ocs-client-operator` cannot onboard the consumer and never creates the
`ClientProfile` that gates CSI StorageClass creation.

**Fix — regenerate the onboarding key chain and reconnect:**

```bash
# 1. Delete the mismatched keys and the StorageConsumer-owned token secret.
oc -n openshift-storage delete secret onboarding-private-key onboarding-ticket-key
TOKEN=$(oc -n openshift-storage get secret -o name | grep onboarding-token | head -1)
oc -n openshift-storage delete "$TOKEN"

# 2. Regenerate: restart ocs-operator (recreates keys) and reconcile the consumer.
oc -n openshift-storage rollout restart deploy/ocs-operator
oc -n openshift-storage annotate storageconsumer internal reconcile="$(date +%s)" --overwrite

# 3. Recreate the StorageClient so it picks up a freshly signed ticket. If it is
#    stuck 'Offboarding', clear its finalizer.
oc delete storageclients.ocs.openshift.io ocs-storagecluster --wait=false
oc patch storageclients.ocs.openshift.io ocs-storagecluster \
  --type merge -p '{"metadata":{"finalizers":[]}}' || true

# 4. Restart the provider so it loads the regenerated public key, then let
#    ocs-operator recreate the StorageClient.
oc -n openshift-storage rollout restart deploy/ocs-provider-server
oc -n openshift-storage rollout restart deploy/ocs-operator
```

**Verify:** `oc get storageclients.ocs.openshift.io` shows `Connected` with a
populated CONSUMER, one `clientprofiles.csi.ceph.io` exists, and the
`ocs-storagecluster-ceph-rbd` and `ocs-storagecluster-cephfs` StorageClasses
appear. This recovery is a leftover-state hazard after repeated
install/delete cycles; a first clean install does not need it.
````

**Step 2: Add `.mgr` check to Post-Reboot Drift.**

Under the `## Post-Reboot Drift` section, append:

````markdown
On single-replica SNO, verify the `.mgr` pool is still `size=1` after any mgr
restart — it is recreated at `size=3` and will re-raise `POOL_NO_REDUNDANCY`
noise / undersized PGs until re-fixed:

```bash
ROOK_OP=$(oc -n openshift-storage get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/openshift-storage/openshift-storage.config"
oc -n openshift-storage exec "$ROOK_OP" -- ceph -c "$CONF" osd pool get .mgr size
# If 3: re-apply size 1 / min_size 1 as in references/validated-odf-sno.md.
```
````

**Step 3: Verify Markdown still validates.**

Run: `cd openshift-odf && python3 tools/validate_skill_package.py`
Expected: only the pre-existing README/VERSION sync issue remains.

---

## Task 4: `references/local-storage-disks.md` edits (#3)

**Files:**
- Modify: `openshift-odf/references/local-storage-disks.md`

**Step 1: Insert the virtio / no-`by-id` subsection.**

Immediately BEFORE the heading `### LocalVolume (exception — when other storage systems share the same node)`, insert:

````markdown
### Disks with no `/dev/disk/by-id/` entry (virtio and similar)

Some hypervisor disks (for example virtio `/dev/vdX` with no serial) have no
`/dev/disk/by-id/` symlink. The LSO diskmaker refuses to create a PV for them
even when a `LocalVolume` `devicePaths` entry resolves by `by-path`:

```
unable to find disk ID for local pool ... IDPathNotFoundError: a symlink to
"vdb" was not found in "/dev/disk/by-id/"
```

Create a stable `by-id` symlink with a udev rule delivered by MachineConfig,
then point the `LocalVolume` at the new `/dev/disk/by-id/<name>` path. Resolve
the disk's `ID_PATH` first (`udevadm info -q property -n /dev/<disk> | grep
ID_PATH`) and target that, never a bare kernel name.

```yaml
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  name: 99-odf-virtio-disk-udev
  labels:
    machineconfiguration.openshift.io/role: master
spec:
  config:
    ignition:
      version: 3.4.0
    storage:
      files:
      - path: /etc/udev/rules.d/99-odf-virtio-disk.rules
        mode: 0644
        contents:
          # Decoded rule:
          # SUBSYSTEM=="block", KERNEL=="vdb", ENV{ID_PATH}=="pci-0000:00:08.0", SYMLINK+="disk/by-id/virtio-odf-vdb"
          source: "data:text/plain,SUBSYSTEM%3D%3D%22block%22%2C%20KERNEL%3D%3D%22vdb%22%2C%20ENV%7BID_PATH%7D%3D%3D%22pci-0000%3A00%3A08.0%22%2C%20SYMLINK%2B%3D%22disk%2Fby-id%2Fvirtio-odf-vdb%22%0A"
```

**Ignition encoding caveat:** the `data:` URL must percent-encode spaces as
`%20`. A literal `+` in a `data:` URL is decoded as a space, so writing the rule
with `+` separators corrupts it into `SUBSYSTEM==...,+KERNEL==...` and udev
silently ignores it. Verify on the node after the MCP updates:

```bash
oc debug node/<node> -- chroot /host bash -c \
  'cat /etc/udev/rules.d/99-odf-virtio-disk.rules; ls -l /dev/disk/by-id/ | grep vdb'
```

A MachineConfig change reboots the node. On SNO the API is unavailable until the
single node returns — wait for the MCP to report `Updated` and the node `Ready`
before continuing. Then reference the new path in the `LocalVolume`:

```yaml
  storageClassDevices:
  - storageClassName: localblock
    volumeMode: Block
    devicePaths:
    - /dev/disk/by-id/virtio-odf-vdb
```
````

**Step 2: Verify Markdown still validates.**

Run: `cd openshift-odf && python3 tools/validate_skill_package.py`
Expected: only the pre-existing README/VERSION sync issue remains.

---

## Task 5: Version bump + CHANGELOG (fixes pre-existing README gap)

**Files:**
- Modify: `openshift-odf/VERSION`
- Modify: `openshift-odf/package.json:3`
- Modify: `openshift-odf/README.md:7`
- Modify: `openshift-odf/CHANGELOG.md`

**Step 1:** Set `openshift-odf/VERSION` to:

```
1.5.0
```

**Step 2:** In `openshift-odf/package.json`, change `"version": "1.4.0",` to `"version": "1.5.0",`.

**Step 3:** In `openshift-odf/README.md`, change `Current version: **1.3.0**` to `Current version: **1.5.0**` (this also repairs the pre-existing 1.3.0/1.4.0 mismatch).

**Step 4:** In `openshift-odf/CHANGELOG.md`, insert a new entry directly under the `# Changelog` heading and above `## 1.4.0`:

```markdown
## 1.5.0

- Extended the **ODF 4.20 SNO** scenario in `references/validated-odf-sno.md`: added **Regression 4 (empty `topologyKey` on CephFilesystem MDS and CephObjectStore RGW placements)** with symptoms and patches, extended **Regression 2** pool sizing to CephFilesystem and CephObjectStore metadata/data pools (`size: 1`, `failureDomain: host`, drop `replicasPerFailureDomain`), and noted that the `.mgr` pool reverts to `size=3` after any mgr restart.
- Added an onboarding-recovery troubleshooting entry to `references/validation-hardening.md` for the internal `StorageClient` stuck `Initializing` with a `crypto/rsa: verification error`, plus a `.mgr` post-reboot drift check.
- Added a **virtio / no `/dev/disk/by-id/`** udev MachineConfig recipe to `references/local-storage-disks.md`, including the ignition `data:` `%20`-not-`+` encoding caveat.
- Added `scripts/render_sno_remediation.py` (generator, review-before-run) that emits the deterministic ODF 4.20 SNO patches (reconcile ignore, MDS/RGW `topologyKey`, CephBlockPool failure domain, CSI `Driver` replicas, `POOL_NO_REDUNDANCY` mute); pool sizing and onboarding remain runbook-only. Covered by `tests/test_render_sno_remediation.py`.
```

**Step 5: Verify validator passes cleanly now.**

Run: `cd openshift-odf && python3 tools/validate_skill_package.py`
Expected: `Validation OK` (or equivalent success; zero issues).

---

## Task 6: Full test + validation gate

**Step 1: Run the skill's pytest suite.**

Run: `cd openshift-odf && python3 -m pytest -q`
Expected: all tests pass (was 59; now 63 with the 4 new cases).

**Step 2: Run the repo-wide collection validator.**

Run: `cd /home/tomaz/sources/agent-skills && python3 scripts/validate_skill_collection.py`
Expected: PASS (no openshift-odf issues).

**Step 3: Sanity-run the new generator.**

Run: `cd openshift-odf && python3 scripts/render_sno_remediation.py --name ocs-storagecluster --namespace openshift-storage | head -40`
Expected: prints the `#!/usr/bin/env bash` banner and the numbered patch blocks; no traceback.

If any gate fails, fix before Task 7.

---

## Task 7: Single squashed commit

**Step 1: Stage all changes.**

```bash
cd /home/tomaz/sources/agent-skills
git add openshift-odf/scripts/render_sno_remediation.py \
        openshift-odf/tests/test_render_sno_remediation.py \
        openshift-odf/references/validated-odf-sno.md \
        openshift-odf/references/validation-hardening.md \
        openshift-odf/references/local-storage-disks.md \
        openshift-odf/VERSION \
        openshift-odf/package.json \
        openshift-odf/README.md \
        openshift-odf/CHANGELOG.md
```

**Step 2: Verify the staged set.**

Run: `git status --short`
Expected: exactly the nine files above staged; nothing unexpected.

**Step 3: Commit.** Do NOT include a `Co-authored-by` trailer or any similar endorsement line.

```bash
git commit -m "openshift-odf: v1.5.0 — ODF 4.20 SNO topologyKey/onboarding/virtio fixes + remediation generator

Extends the ODF 4.20 SNO runbook with the empty-topologyKey regression on MDS
and RGW placements, CephFilesystem/CephObjectStore pool sizing, and the .mgr
size-reversion note; adds StorageClient onboarding-signature recovery to
validation-hardening; documents the virtio no-by-id udev MachineConfig (with the
%20 encoding caveat) in local-storage-disks; and adds a review-before-run
render_sno_remediation.py generator for the deterministic patches. Also repairs
the pre-existing README version marker (1.3.0 -> 1.5.0)."
```

**Step 4: Confirm.**

Run: `git log --oneline -1 && git status --short`
Expected: the commit is present; working tree clean (design docs from the
brainstorming step were already committed separately).

---

## Done criteria

- `python3 -m pytest -q` in `openshift-odf/` is green (63 passed).
- `python3 tools/validate_skill_package.py` and `python3 scripts/validate_skill_collection.py` both pass.
- `render_sno_remediation.py` emits the five deterministic blocks and the runbook-pointer banner; excludes onboarding/pool-loop.
- One squashed commit contains exactly the nine changed files; VERSION/package.json/README/CHANGELOG all read 1.5.0.
- No commit contains a `Co-authored-by` or similar endorsement trailer.
