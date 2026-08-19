# openshift-odf v1.6.0 — ODF 4.22.1 SNO CephFS Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update the openshift-odf skill so the ODF 4.22 SNO runbook documents CephFS as validated on 4.22.1, adds the newly-discovered pool-spec and CPU-request fixes, refines onboarding recovery, corrects the CSI-replica target, and extends the remediation generator to emit the 4.22 patches.

**Architecture:** Additive documentation edits to two reference files + SKILL.md, an extension to `render_sno_remediation.py` (TDD), and a version bump. The generator already emits reconcile-freeze, MDS/RGW topologyKey, per-Driver CSI replicas, and the mute; it gains an object/file-pool `replicasPerFailureDomain` removal block and a minimal-resource-requests block.

**Tech Stack:** Markdown runbooks, Python 3.9+ generator, pytest, repo skill validators.

**Branch:** `feat/odf-sno-420-scenario` (continues PR #14; base VERSION 1.5.0).

---

## Task 1: Extend `render_sno_remediation.py` for 4.22 pool-spec + resource-request patches

**Files:**
- Modify: `openshift-odf/scripts/render_sno_remediation.py`
- Test: `openshift-odf/tests/test_render_sno_remediation.py`

**Step 1: Write failing tests**

Add to `openshift-odf/tests/test_render_sno_remediation.py`:

```python
def test_emits_object_file_pool_failuredomain_removal():
    text = render_sno_remediation()
    # Object store + filesystem metadata/data pools must drop replicasPerFailureDomain
    assert "cephobjectstore ocs-storagecluster-cephobjectstore" in text
    assert "/spec/metadataPool/replicated/replicasPerFailureDomain" in text
    assert "/spec/dataPool/replicated/replicasPerFailureDomain" in text
    assert "cephfilesystem ocs-storagecluster-cephfilesystem" in text
    assert "/spec/metadataPool/replicated/replicasPerFailureDomain" in text


def test_emits_minimal_resource_requests():
    text = render_sno_remediation()
    # StorageCluster spec.resources minimal requests to avoid SNO CPU starvation
    assert '"mon"' in text and '"mgr"' in text and '"noobaa-core"' in text
    # frozen MDS/RGW resources patched directly on the CRs
    assert "metadataServer" in text and "gateway" in text
    # resourceProfile lean must be explicitly warned against, not used
    assert "resourceProfile" in text and "lean" in text


def test_resource_and_pool_blocks_are_valid_bash():
    import shutil, subprocess
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    text = render_sno_remediation()
    proc = subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
```

**Step 2: Run tests to verify they fail**

Run: `cd openshift-odf && python -m pytest tests/test_render_sno_remediation.py -q`
Expected: FAIL on the three new assertions (strings not yet emitted).

**Step 3: Add the new template blocks + generalize banner**

In `openshift-odf/scripts/render_sno_remediation.py`:

3a. Update the module docstring first line and `BANNER` to read `ODF 4.20/4.22 SNO` instead of `ODF 4.20 SNO`.

3b. After `_BLOCKPOOL_FD`, add:

```python
_OBJECT_FILE_FD = """\
# 3b. ODF 4.22 (Ceph 20.2 tentacle): the CephObjectStore and CephFilesystem
#     metadata/data pools reject size=1 while replicasPerFailureDomain=1
#     ("size must be greater"). CephBlockPool tolerates it, but the object and
#     file controllers do not — RGW and MDS never start. Drop the field (keep
#     size=1) so both reconcile.
oc -n {ns} patch cephobjectstore {name}-cephobjectstore --type json -p '[
  {{"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}},
  {{"op":"remove","path":"/spec/dataPool/replicated/replicasPerFailureDomain"}}
]'
oc -n {ns} patch cephfilesystem {name}-cephfilesystem --type json -p '[
  {{"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}}
]'
"""

_RESOURCE_REQUESTS = """\
# 6. SNO CPU-request starvation: ODF's default 'balanced' requests (mon 1050m,
#    mds/osd/rgw 2050m, noobaa 999m) saturate the node's schedulable CPU even
#    though real use is ~6%, leaving noobaa-core and CSI pods Pending. Do NOT
#    set 'resourceProfile: lean' (it traps the StorageCluster in Progressing on
#    4.22). Instead set minimal per-component requests. MDS/RGW are frozen CRs,
#    so patch them directly.
oc -n {ns} patch storagecluster {name} --type merge -p '{{
  "spec": {{
    "resources": {{
      "mon":             {{"requests": {{"cpu": "100m", "memory": "1Gi"}}}},
      "mgr":             {{"requests": {{"cpu": "100m", "memory": "1Gi"}}}},
      "noobaa-core":     {{"requests": {{"cpu": "100m", "memory": "1Gi"}}}},
      "noobaa-db":       {{"requests": {{"cpu": "100m", "memory": "512Mi"}}}},
      "noobaa-endpoint": {{"requests": {{"cpu": "100m", "memory": "512Mi"}}}}
    }}
  }}
}}'
oc -n {ns} patch storagecluster {name} --type json -p '[
  {{"op":"add","path":"/spec/storageDeviceSets/0/resources","value":{{"requests":{{"cpu":"100m","memory":"2Gi"}},"limits":{{"cpu":"2","memory":"5Gi"}}}}}}
]'
oc -n {ns} patch cephfilesystem {name}-cephfilesystem --type merge \\
  -p '{{"spec":{{"metadataServer":{{"resources":{{"requests":{{"cpu":"100m","memory":"1Gi"}},"limits":{{"cpu":"2","memory":"4Gi"}}}}}}}}}}'
oc -n {ns} patch cephobjectstore {name}-cephobjectstore --type merge \\
  -p '{{"spec":{{"gateway":{{"resources":{{"requests":{{"cpu":"100m","memory":"1Gi"}},"limits":{{"cpu":"2","memory":"4Gi"}}}}}}}}}}'
"""
```

3c. In `render_sno_remediation()`, insert `_OBJECT_FILE_FD` right after `_BLOCKPOOL_FD` and `_RESOURCE_REQUESTS` right after `_CSI_REPLICAS` in the `blocks` list:

```python
    blocks = [
        BANNER,
        _RECONCILE_IGNORE.format(name=name, ns=namespace),
        _TOPOLOGYKEY.format(name=name, ns=namespace),
        _BLOCKPOOL_FD.format(name=name, ns=namespace),
        _OBJECT_FILE_FD.format(name=name, ns=namespace),
        _CSI_REPLICAS.format(name=name, ns=namespace),
        _RESOURCE_REQUESTS.format(name=name, ns=namespace),
        _MUTE.format(name=name, ns=namespace),
    ]
```

**Step 4: Run tests to verify they pass**

Run: `cd openshift-odf && python -m pytest tests/test_render_sno_remediation.py -q`
Expected: PASS (all tests, including the pre-existing 6).

**Step 5: Commit**

```bash
git add openshift-odf/scripts/render_sno_remediation.py openshift-odf/tests/test_render_sno_remediation.py
git commit -m "openshift-odf: emit 4.22 object/file pool + resource-request patches in remediation generator"
```

---

## Task 2: Update the 4.22 runbook section for CephFS validation

**Files:**
- Modify: `openshift-odf/references/validated-odf-sno.md`

**Step 1: Freeze cephFilesystems + patch CephFilesystem pool (Pool Sizes section, ~line 505–527)**

In "Step 1: Freeze ODF reconciliation…", add `cephFilesystems` to the merged patch:

```json
    "managedResources": {
      "cephBlockPools":   {"reconcileStrategy": "ignore"},
      "cephObjectStores": {"reconcileStrategy": "ignore"},
      "cephFilesystems":  {"reconcileStrategy": "ignore"}
    }
```

In "Step 2: Patch ODF-managed CRs to size=1", append after the cephobjectstore patch:

```bash
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem \
  --type merge \
  -p '{"spec":{"metadataPool":{"replicated":{"size":1,"requireSafeReplicaSize":false}},"dataPools":[{"name":"data0","replicated":{"size":1,"requireSafeReplicaSize":false}}]}}'
```

**Step 2: Add MDS/RGW topologyKey + replicasPerFailureDomain regression subsection**

Immediately BEFORE the `## CSI Controller Plugin Replicas on SNO` header (line 562), insert:

````markdown
## ODF 4.22 Regression: Empty `topologyKey` on MDS and RGW (CephFS + Object)

The mon/OSD empty-`topologyKey` fix (baked into the StorageCluster above) is not
sufficient once CephFS and Object are enabled. On ODF 4.22 SNO, ocs-operator
also emits `topologyKey: ""` + `whenUnsatisfiable: DoNotSchedule` on:

- `CephFilesystem` `spec.metadataServer.placement` — MDS never schedules, the
  `CephFilesystem` stays `Failure`.
- `CephObjectStore` `spec.gateway.placement` — no RGW pod is created, so NooBaa
  cannot create its object-store user and stays `Configuring`.

Freeze `cephFilesystems`/`cephObjectStores` (Step 1 above), then patch both:

```bash
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem --type json -p '[
  {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
  {"op":"replace","path":"/spec/metadataServer/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
]'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore --type json -p '[
  {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/topologyKey","value":"kubernetes.io/hostname"},
  {"op":"replace","path":"/spec/gateway/placement/topologySpreadConstraints/0/whenUnsatisfiable","value":"ScheduleAnyway"}
]'
```

## ODF 4.22 Regression: `replicasPerFailureDomain=1` + `size=1` Rejected on Object/File Pools

On Ceph 20.2 "tentacle" (RHCEPH-9, shipped with ODF 4.22.1), the object and file
pool controllers reject a pool with `size: 1` while
`replicasPerFailureDomain: 1`:

```
invalid metadata pool spec: error pool size is 1 and replicasPerFailureDomain is 1, size must be greater
```

`CephBlockPool` tolerates this combination, but `CephObjectStore` and
`CephFilesystem` do not — their reconcile fails and RGW/MDS never start. Remove
the field (keep `size: 1`) after freezing reconciliation:

```bash
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore --type json -p '[
  {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"},
  {"op":"remove","path":"/spec/dataPool/replicated/replicasPerFailureDomain"}
]'
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem --type json -p '[
  {"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}
]'
```

**Note on `.mgr`:** the `.mgr` pool reverts to `size=3` after *any* mgr restart
(including the restart triggered by applying resource requests below). Re-run the
`ceph osd pool set .mgr size 1 --yes-i-really-mean-it` / `min_size 1` step after
such restarts, then re-mute `POOL_NO_REDUNDANCY`.

## ODF 4.22 SNO: CPU-Request Starvation

ODF's default "balanced" resource **requests** (mon `1050m`; mds/osd/rgw
`2050m`; noobaa-core/endpoint `999m`) saturate a single node's schedulable CPU
(observed 99% requested vs ~6% actually used), leaving `noobaa-core` and the
second CSI replica `Pending` with `Insufficient cpu`. Do **not** set
`resourceProfile: lean` (it traps the StorageCluster in `Progressing` on 4.22).
Set minimal per-component requests instead; MDS/RGW are frozen CRs so patch them
directly:

```bash
oc -n openshift-storage patch storagecluster ocs-storagecluster --type merge -p '{
  "spec": {"resources": {
    "mon":             {"requests": {"cpu": "100m", "memory": "1Gi"}},
    "mgr":             {"requests": {"cpu": "100m", "memory": "1Gi"}},
    "noobaa-core":     {"requests": {"cpu": "100m", "memory": "1Gi"}},
    "noobaa-db":       {"requests": {"cpu": "100m", "memory": "512Mi"}},
    "noobaa-endpoint": {"requests": {"cpu": "100m", "memory": "512Mi"}}
  }}
}'
oc -n openshift-storage patch storagecluster ocs-storagecluster --type json -p '[
  {"op":"add","path":"/spec/storageDeviceSets/0/resources","value":{"requests":{"cpu":"100m","memory":"2Gi"},"limits":{"cpu":"2","memory":"5Gi"}}}
]'
oc -n openshift-storage patch cephfilesystem ocs-storagecluster-cephfilesystem --type merge \
  -p '{"spec":{"metadataServer":{"resources":{"requests":{"cpu":"100m","memory":"1Gi"},"limits":{"cpu":"2","memory":"4Gi"}}}}}'
oc -n openshift-storage patch cephobjectstore ocs-storagecluster-cephobjectstore --type merge \
  -p '{"spec":{"gateway":{"resources":{"requests":{"cpu":"100m","memory":"1Gi"},"limits":{"cpu":"2","memory":"4Gi"}}}}}'
```

This dropped observed CPU requests from 99% to ~35% and let all components schedule.
````

**Step 3: Correct the CSI replicas section (~line 562–572)**

Replace the body of `## CSI Controller Plugin Replicas on SNO` with:

````markdown
ODF deploys 2 replicas of each CSI controller plugin for HA. On SNO the second
replica can never schedule (pod anti-affinity), and it also wastes scarce CPU
requests. Patching `operatorconfigs.csi.ceph.io` alone is **reverted** by
ocs-client-operator on 4.22.1 — patch the per-driver `drivers.csi.ceph.io` CRs
instead (this sticks):

```bash
oc -n openshift-storage patch drivers.csi.ceph.io openshift-storage.rbd.csi.ceph.com \
  --type merge -p '{"spec":{"controllerPlugin":{"replicas":1}}}'
oc -n openshift-storage patch drivers.csi.ceph.io openshift-storage.cephfs.csi.ceph.com \
  --type merge -p '{"spec":{"controllerPlugin":{"replicas":1}}}'
```
````

**Step 4: Flip Validation Notes (~line 585–593) to record CephFS validated**

Replace the `- RBD and MCG/RGW object validated. **CephFS not validated in this scenario.**` bullet with:

```markdown
- RBD (RWO), CephFS (RWX), and MCG/RGW object (OBC) all validated on ODF 4.22.1: a `ReadWriteOnce` rbd PVC and a `ReadWriteMany` cephfs PVC bound and a pod wrote to both; an `ObjectBucketClaim` bound. MDS ran active + 1 hot standby; `CephFilesystem` Ready.
- Applying minimal resource requests dropped node CPU requests from 99% to ~35%.
```

**Step 5: Update the 4.20 scenario cross-reference at line 403**

Change the parenthetical `(**CephFS not validated in this scenario**)` note at line 403 to `(CephFS validated separately on ODF 4.22.1 — see the 4.22 section below)` and remove the trailing "Do not enable CephFS on ODF 4.22 SNO…" sentence.

**Step 6: Commit**

```bash
git add openshift-odf/references/validated-odf-sno.md
git commit -m "openshift-odf: document CephFS validated on ODF 4.22.1 SNO with topologyKey/pool/resource fixes"
```

---

## Task 3: Refine onboarding-signature recovery ordering

**Files:**
- Modify: `openshift-odf/references/validation-hardening.md`

**Step 1:** In the "StorageClient stuck `Initializing`" fix (~lines 159–188), replace the numbered recovery with the convergent ordering:

````markdown
**Fix — regenerate the onboarding token against a stable key pair:**

The failure is a signature mismatch: the signed `onboarding-token-*` secret was
produced with a private key that no longer matches the public key the provider
verifies with. Repeatedly deleting the keys and restarting races (keys and token
regenerate out of order) and never converges. Regenerate the **token only**
against the existing key pair:

```bash
# 1. Confirm the key pair exists and is matched (same RSA modulus). If either
#    key is missing, restart ocs-operator once and wait for BOTH to be recreated
#    together before continuing.
oc -n openshift-storage get secret onboarding-private-key onboarding-ticket-key

# 2. Delete ONLY the signed token and the StorageClient (leave the keys intact).
TOKEN=$(oc -n openshift-storage get secret -o name | grep onboarding-token | head -1)
[ -n "$TOKEN" ] && oc -n openshift-storage delete "$TOKEN"
oc delete storageclients.ocs.openshift.io ocs-storagecluster --wait=false
oc patch storageclients.ocs.openshift.io ocs-storagecluster \
  --type merge -p '{"metadata":{"finalizers":[]}}' || true

# 3. Restart ocs-operator ONCE. Because the keys already exist, it regenerates
#    only the missing token — signed with the current private key — and recreates
#    the StorageClient. Do NOT delete the keys or restart repeatedly.
oc -n openshift-storage rollout restart deploy/ocs-operator
```
````

**Step 2:** Keep the existing **Verify** paragraph (Connected + populated CONSUMER + ClientProfile + ceph-rbd/cephfs StorageClasses). Add a sentence: "Observed on ODF 4.22.1 after a StorageCluster delete/recreate; the key point is to never delete the keys after the token."

**Step 3: Commit**

```bash
git add openshift-odf/references/validation-hardening.md
git commit -m "openshift-odf: refine StorageClient onboarding recovery to a convergent token-only regen"
```

---

## Task 4: Lift the "no CephFS on 4.22" caveat in SKILL.md

**Files:**
- Modify: `openshift-odf/SKILL.md`

**Step 1:** In the Core Safety Rules version-scoped exception (line 47), replace the sentence `Do not enable CephFS with this workaround: its pool-reconciliation path was not validated for ODF 4.22 SNO.` with:

```text
CephFS is supported on ODF 4.22.1 SNO once the MDS/RGW empty-topologyKey patches and the object/file-pool `replicasPerFailureDomain` removal are also applied (see `references/validated-odf-sno.md`); freeze `cephFilesystems` alongside `cephBlockPools`/`cephObjectStores` before patching.
```

**Step 2:** In line 78 (Output Expectations), ensure the exception wording references both 4.20 and 4.22 SNO (already "version-scoped ODF 4.22 SNO pool workaround"); extend to `…ODF 4.20/4.22 SNO pool, topologyKey, and resource workarounds…`.

**Step 3: Commit**

```bash
git add openshift-odf/SKILL.md
git commit -m "openshift-odf: lift no-CephFS-on-4.22 caveat now that 4.22.1 CephFS is validated"
```

---

## Task 5: Version bump to 1.6.0

**Files:**
- Modify: `openshift-odf/VERSION`, `openshift-odf/package.json`, `openshift-odf/README.md`, `openshift-odf/CHANGELOG.md`

**Step 1:** Set `openshift-odf/VERSION` to `1.6.0`. Set `"version": "1.6.0"` in `package.json`. Update the version marker in `README.md` (search for `1.5.0`).

**Step 2:** Add a `## 1.6.0` entry at the top of `CHANGELOG.md`:

```markdown
## 1.6.0
- Validated ODF 4.22.1 SNO **with CephFS**: RBD, CephFS, and Object all pass.
- Documented MDS/RGW empty-topologyKey fixes for 4.22 (CephFS + Object).
- New: object/file pool `replicasPerFailureDomain` removal for Ceph 20.2 "tentacle".
- New: SNO CPU-request starvation workaround via minimal `spec.resources` (lean profile still unsafe on 4.22).
- Corrected CSI ctrlplugin replica fix to patch per-`drivers.csi.ceph.io` CRs (operatorconfig is reverted on 4.22.1).
- Refined StorageClient onboarding-signature recovery to a convergent token-only regeneration.
- Extended `render_sno_remediation.py` to emit the 4.22 pool-spec and resource-request patches.
- Lifted the "no CephFS on 4.22" caveat in SKILL.md.
```

**Step 3: Commit**

```bash
git add openshift-odf/VERSION openshift-odf/package.json openshift-odf/README.md openshift-odf/CHANGELOG.md
git commit -m "openshift-odf: bump to 1.6.0"
```

---

## Task 6: Validation gates

**Step 1:** Run the generator tests:
Run: `cd openshift-odf && python -m pytest tests/ -q`
Expected: all PASS.

**Step 2:** Bash-syntax + JSON check the generator output:
Run: `cd openshift-odf && python scripts/render_sno_remediation.py | bash -n`
Expected: exit 0.

**Step 3:** Skill + collection validators:
Run: `python3 scripts/validate_skill_collection.py`
Run the skill's own validator if present (e.g. `openshift-odf/tests/validate_skill.py` or the repo equivalent used in prior versions).
Expected: PASS.

**Step 4:** No commit (validation only). If anything fails, fix in the owning task and re-run.

---

## Task 7: Final review + push

**Step 1:** `git --no-pager log --oneline origin/main..HEAD` — confirm the new commits are present and trailer-free.

**Step 2:** Request code review (requesting-code-review skill), address findings.

**Step 3:** Push and update PR #14 (finishing-a-development-branch, Option 2). The existing PR reuses the head branch; update its body to note the 1.6.0 / 4.22.1 CephFS scope.
