#!/usr/bin/env python3
"""Render the deterministic ODF 4.20/4.22 SNO post-install remediation commands.

This is a GENERATOR: it prints a reviewable bash script and never executes
`oc` or `ceph`. It emits fixed kube-API-level patches that are safe to apply
once the CephCluster is Ready — including CephFilesystem / CephObjectStore
CR-spec pool patches (failureDomain=host, remove replicasPerFailureDomain,
size=1). Live `ceph osd pool set` sizing, the POOL_NO_REDUNDANCY mute, and
StorageClient onboarding recovery are intentionally NOT emitted; follow the
runbooks referenced in the banner for those stateful steps.

`--release` is mandatory because the block sets differ:

* **4.20** — CephBlockPool failure-domain fix + object/file CR-spec fixes
  (shared with 4.22) + CSI replicas + mute note.
* **4.22** — the same CephBlockPool and object/file CR-spec fixes + CSI replicas
  + resource-request floor + mute note.

Emitting the wrong release against a cluster fails under `set -e` on the first
inapplicable patch; the rendered preflight aborts before any mutation when the
installed CSV does not match.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

# Validated releases. 4.22 covers the 4.22.1 procedure; do not pass 4.22.0.
RELEASES = ("4.20", "4.22")

# RFC 1123 label, the syntax Kubernetes accepts for object and namespace names.
# Rendered values land inside executable shell syntax, so anything outside this
# grammar is rejected rather than quoted: the patch payloads are single-quoted
# JSON, and shell-quoting the operands in place would corrupt them.
_RFC1123 = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

BANNER = """\
#!/usr/bin/env bash
# ODF {release} SNO deterministic remediation — REVIEW BEFORE RUNNING.
#
# Prerequisite: the CephCluster is Ready (mons up, OSD up/in).
#
# This script applies the deterministic kube-API patches validated for this
# ODF release ({release}), including CephFilesystem / CephObjectStore CR-spec
# pool patches (failureDomain=host, remove replicasPerFailureDomain, size=1).
# Do not re-run those same JSON removes from the runbook afterward — the fields
# are already gone and `set -e` would stop the script.
#
# It does NOT perform live `ceph osd pool set` sizing, the POOL_NO_REDUNDANCY
# mute, or StorageClient onboarding recovery (stateful / cluster-specific):
#   * Live pool sizing / mute: follow the pool-size section for this release in
#     references/validated-odf-sno.md (the ceph CLI steps only). It is titled
#     "Regression 2" on 4.20 and "Pool Sizes Not Reduced for SNO" on 4.22, so
#     search for the topic rather than the number.
#   * StorageClient onboarding recovery:
#     follow references/validation-hardening.md troubleshooting.
set -euo pipefail
{context_pin}"""

# Rendered only when --context is given. Every emitted `oc` goes through this
# wrapper, including the ones inside command substitutions, because a shell
# function is inherited by subshells. Without it the script uses bare `oc` and
# mutates whatever context happens to be current - the easiest way to patch the
# wrong cluster from a multi-cluster workstation.
_CONTEXT_PIN = """\

# Pin every `oc` below to one context (rendered from --context).
oc() {{ command oc --context={context} "$@"; }}
# Record the pinned context for the preflight. `oc config current-context` keeps
# printing the kubeconfig's own current-context even when --context overrides the
# request target, so it must not be used to label the target or to compare
# against ODF_EXPECT_CONTEXT.
ODF_TARGET_CONTEXT={context}
"""

# Must render before any mutating command: --release only selects templates, so
# without this the wrong-release script mutates resources and only then fails on
# an inapplicable patch. `set -e` stops the run, it does not undo those writes.
_RELEASE_PREFLIGHT = """\
# {n}. Preflight: announce the target cluster, then refuse to run against a
#     different ODF release. The release check answers "is this the right
#     software?"; it cannot answer "is this the right cluster?", so print that
#     too and set ODF_EXPECT_CONTEXT to make a mismatch fatal.
#     The server URL is authoritative. The context label comes from the --context
#     pin when there is one, and only otherwise from `oc config current-context`,
#     which reports the kubeconfig's current-context regardless of --context.
TARGET_CONTEXT="${{ODF_TARGET_CONTEXT:-$(oc config current-context 2>/dev/null || echo unknown)}}"
echo "target cluster: $(oc whoami --show-server 2>/dev/null || echo unknown)" \\
  "(context: $TARGET_CONTEXT)" >&2
if [ -n "${{ODF_EXPECT_CONTEXT:-}}" ] && [ "$TARGET_CONTEXT" != "$ODF_EXPECT_CONTEXT" ]; then
  echo "target context '$TARGET_CONTEXT' does not match" \\
    "ODF_EXPECT_CONTEXT=$ODF_EXPECT_CONTEXT" >&2
  exit 1
fi
#     Resolve to exactly one CSV first. A glob matches across newlines, so a
#     newline-separated list whose first entry is the right release would
#     otherwise satisfy the release check while the cluster state is ambiguous.
mapfile -t OCS_CSVS < <(oc -n {ns} get csv \\
  -o jsonpath='{{range .items[*]}}{{.metadata.name}}{{"\\n"}}{{end}}' \\
  | grep '^ocs-operator\\.' || true)
case "${{#OCS_CSVS[@]}}" in
  0) echo "no ocs-operator CSV found in {ns}" >&2; exit 1 ;;
  1) INSTALLED_CSV="${{OCS_CSVS[0]}}" ;;
  *) echo "multiple ocs-operator CSVs in {ns}: ${{OCS_CSVS[*]}}" >&2
     echo "refusing to guess which one is current" >&2
     exit 1 ;;
esac
case "$INSTALLED_CSV" in
  ocs-operator.v{release}.*) ;;
  *) echo "installed ODF CSV '$INSTALLED_CSV' is not {release}; this script" >&2
     echo "renders the {release} remediation only - re-render with the" >&2
     echo "matching --release" >&2
     exit 1 ;;
esac
"""

_RECONCILE_IGNORE = """\
# {n}. Freeze ODF reconciliation for pools, object stores, and filesystems so the
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
# {n}. Empty-topologyKey regression: MDS (CephFilesystem) and RGW gateway
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

# Both 4.20 and 4.22. This block used to be 4.20-only on the assumption that
# 4.22 shipped a failure domain Rook accepts. Disproved on ODF 4.22.3 (htz2,
# 2026-09-16): the CephBlockPool CR shipped failureDomain=osd with size=3 and
# replicasPerFailureDomain=1, so Rook kept reverting the live `ceph osd pool set
# ... size 1` back to 3 and the cluster sat at "32 pgs inactive / undersized"
# and never reached HEALTH_OK.
_BLOCKPOOL_FD = """\
# {n}. CephBlockPool: Rook rejects size=1 while failureDomain=osd +
#    replicasPerFailureDomain=1 ("size must be greater than
#    replicasPerFailureDomain"). Switch to host, drop replicasPerFailureDomain,
#    and persist size=1 in the CR: the CR stays the desired state Rook applies
#    on its next reconcile of this pool, so a live-only `ceph osd pool set`
#    is undone whenever that reconcile is next triggered.
oc -n {ns} patch cephblockpool {name}-cephblockpool --type json -p '[
  {{"op":"replace","path":"/spec/failureDomain","value":"host"}},
  {{"op":"remove","path":"/spec/replicated/replicasPerFailureDomain"}},
  {{"op":"replace","path":"/spec/replicated/size","value":1}},
  {{"op":"add","path":"/spec/replicated/requireSafeReplicaSize","value":false}}
]'
"""

_CSI_REPLICAS = """\
# {n}. CSI controller plugins ship with 2 replicas (hard pod anti-affinity) that
#    cannot both schedule on SNO. Reduce to 1 via the Driver CRs (patching
#    OperatorConfig alone is not sufficient).
oc -n {ns} patch drivers.csi.ceph.io/{ns}.rbd.csi.ceph.com \\
  --type merge -p '{{"spec":{{"controllerPlugin":{{"replicas":1}}}}}}'
oc -n {ns} patch drivers.csi.ceph.io/{ns}.cephfs.csi.ceph.com \\
  --type merge -p '{{"spec":{{"controllerPlugin":{{"replicas":1}}}}}}'
# After patching, delete the stale Running ctrlplugin pods so the new
# single-replica ReplicaSet can schedule (see the runbook).
"""

# Emitted as commentary only: muting POOL_NO_REDUNDANCY before the pools are
# actually size=1 hides a warning that is still legitimate, and this script
# deliberately does not size pools.
_MUTE = """\
# {n}. Mute the expected single-replica warning — NOT EXECUTED HERE.
#    POOL_NO_REDUNDANCY is only the expected steady state once pool sizing from
#    the pool-size section for this release in references/validated-odf-sno.md
#    has been applied ("Regression 2" on 4.20, "Pool Sizes Not Reduced for SNO"
#    on 4.22). Run these
#    two commands by hand after that step, never before:
#      ROOK_OP=$(oc -n {ns} get pods -l app=rook-ceph-operator -o name | head -1)
#      CONF="/var/lib/rook/{ns}/{ns}.config"
#      oc -n {ns} exec "$ROOK_OP" -- ceph -c "$CONF" health mute POOL_NO_REDUNDANCY
"""

# Both 4.20 and 4.22: CephObjectStore / CephFilesystem reject size=1 while
# replicasPerFailureDomain=1 ("size must be greater"). Observed on ODF 4.20.18
# (Ceph 19.2) and ODF 4.22.1 (Ceph 20.2). A merge patch that only sets size
# leaves the field in place — use JSON remove. Also switch failureDomain to
# host so Rook accepts size=1 the same way as the block-pool fix.
_OBJECT_FILE_FD = """\
# {n}. CephObjectStore and CephFilesystem metadata/data pools reject size=1
#    while replicasPerFailureDomain=1 ("size must be greater"). Drop the field,
#    set failureDomain=host, and persist size=1. A `--type merge` size-only
#    patch does NOT remove replicasPerFailureDomain and leaves RGW/MDS stuck
#    Progressing / Failure.
# Precondition: exactly one CephFilesystem data pool. The patch below targets
# /spec/dataPools/0; with more pools the others would keep the rejected field,
# so stop and patch each index by hand instead.
DATA_POOLS=$(oc -n {ns} get cephfilesystem {name}-cephfilesystem \\
  -o jsonpath='{{range .spec.dataPools[*]}}{{"x"}}{{end}}')
if [ "${{#DATA_POOLS}}" -ne 1 ]; then
  echo "expected exactly 1 CephFilesystem data pool, found ${{#DATA_POOLS}} —" \\
       "patch each /spec/dataPools/<i> by hand" >&2
  exit 1
fi
oc -n {ns} patch cephobjectstore {name}-cephobjectstore --type json -p '[
  {{"op":"replace","path":"/spec/metadataPool/failureDomain","value":"host"}},
  {{"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}},
  {{"op":"replace","path":"/spec/metadataPool/replicated/size","value":1}},
  {{"op":"add","path":"/spec/metadataPool/replicated/requireSafeReplicaSize","value":false}},
  {{"op":"replace","path":"/spec/dataPool/failureDomain","value":"host"}},
  {{"op":"remove","path":"/spec/dataPool/replicated/replicasPerFailureDomain"}},
  {{"op":"replace","path":"/spec/dataPool/replicated/size","value":1}},
  {{"op":"add","path":"/spec/dataPool/replicated/requireSafeReplicaSize","value":false}}
]'
oc -n {ns} patch cephfilesystem {name}-cephfilesystem --type json -p '[
  {{"op":"replace","path":"/spec/metadataPool/failureDomain","value":"host"}},
  {{"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}},
  {{"op":"replace","path":"/spec/metadataPool/replicated/size","value":1}},
  {{"op":"add","path":"/spec/metadataPool/replicated/requireSafeReplicaSize","value":false}},
  {{"op":"replace","path":"/spec/dataPools/0/failureDomain","value":"host"}},
  {{"op":"remove","path":"/spec/dataPools/0/replicated/replicasPerFailureDomain"}},
  {{"op":"replace","path":"/spec/dataPools/0/replicated/size","value":1}},
  {{"op":"add","path":"/spec/dataPools/0/replicated/requireSafeReplicaSize","value":false}}
]'
"""

# ODF 4.22 only: the 4.20 scenario does not hit CPU-request starvation.
_RESOURCE_REQUESTS = """\
# {n}. SNO CPU-request starvation: ODF's default 'balanced' requests (mon 1050m,
#    mds/osd/rgw 2050m, noobaa 999m) saturate the node's schedulable CPU even
#    though real use is ~6%, leaving noobaa-core and CSI pods Pending. Do NOT
#    set 'resourceProfile: lean' (it traps the StorageCluster in Progressing on
#    4.22). Instead set minimal per-component requests. MDS/RGW are frozen CRs,
#    so patch them directly.
#    Deliberately NO 'noobaa-db' entry. Lowering the noobaa-db request makes
#    NooBaa's PGTune recompute the CNPG postgres spec (shared_buffers,
#    effective_cache_size, requests). NooBaa refuses to apply a CNPG spec change
#    while its own phase is Creating, and it cannot leave Creating because that
#    same reconcile errors out - a permanent deadlock. Observed on ODF 4.22.3
#    (htz2, 2026-09-16): the CNPG cluster was Ready 2/2 for 10+ minutes with zero
#    noobaa-core pods and the StorageCluster stuck Progressing. Restarting
#    noobaa-operator does not clear it; removing the key does, immediately.
#    If noobaa-db really must be constrained, apply it only after NooBaa is Ready.
oc -n {ns} patch storagecluster {name} --type merge -p '{{
  "spec": {{
    "resources": {{
      "mon":             {{"requests": {{"cpu": "100m", "memory": "1Gi"}}}},
      "mgr":             {{"requests": {{"cpu": "100m", "memory": "1Gi"}}}},
      "noobaa-core":     {{"requests": {{"cpu": "100m", "memory": "1Gi"}}}},
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

# Ordered per release. The step numbers are assigned at render time so each
# release gets a contiguous 1..N sequence instead of gaps where a block is
# skipped.
_BLOCKS = {
    "4.20": (
        _RELEASE_PREFLIGHT,
        _RECONCILE_IGNORE,
        _TOPOLOGYKEY,
        _BLOCKPOOL_FD,
        _OBJECT_FILE_FD,
        _CSI_REPLICAS,
        _MUTE,
    ),
    "4.22": (
        _RELEASE_PREFLIGHT,
        _RECONCILE_IGNORE,
        _TOPOLOGYKEY,
        _BLOCKPOOL_FD,
        _OBJECT_FILE_FD,
        _CSI_REPLICAS,
        _RESOURCE_REQUESTS,
        _MUTE,
    ),
}


def _validate_name(label: str, value: str) -> str:
    """Reject names that would break rendered `oc` argv or Kubernetes DNS labels.

    63 is the RFC 1123 label limit Kubernetes enforces; a longer value renders
    fine here but every emitted `oc` command would be rejected by the API.
    fullmatch, not match: `$` also matches before a trailing newline, so
    "my-ns\\n" would pass and then split every emitted `oc` command in two.
    """
    if _RFC1123.fullmatch(value) is None or len(value) > 63:
        raise ValueError(
            f"{label} {value!r} is not a valid RFC 1123 name "
            "(lowercase alphanumerics and '-', must start and end alphanumeric, "
            "max 63 characters)"
        )
    return value


_CONTEXT_SAFE = re.compile(r"^[A-Za-z0-9._:@/-]+$")


def _validate_context(value: str) -> str:
    """Reject context names that would break out of the rendered `oc` argv.

    The name is interpolated into an unquoted shell word inside the `oc()`
    wrapper, so anything with whitespace, quotes or shell metacharacters could
    inject a second command into every `oc` call the script makes.
    """
    if _CONTEXT_SAFE.fullmatch(value) is None:
        raise ValueError(
            f"context {value!r} contains characters that are unsafe to render "
            "into a shell command; expected only letters, digits and ._:@/-"
        )
    return value


def render_sno_remediation(
    release: str,
    name: str = "ocs-storagecluster",
    namespace: str = "openshift-storage",
    output: str | None = None,
    context: str | None = None,
) -> str:
    """Return (and optionally write) the reviewable remediation bash script.

    Selects the release-specific `_BLOCKS` templates, numbers steps contiguously,
    and prefixes the BANNER that documents what is and is not emitted.
    """
    if release not in _BLOCKS:
        raise ValueError(
            f"release {release!r} is not a validated ODF SNO release; "
            f"expected one of {', '.join(RELEASES)}"
        )
    _validate_name("name", name)
    _validate_name("namespace", namespace)
    context_pin = ""
    if context is not None:
        _validate_context(context)
        context_pin = _CONTEXT_PIN.format(context=context)

    blocks = [BANNER.format(release=release, context_pin=context_pin)]
    for step, template in enumerate(_BLOCKS[release], start=1):
        blocks.append(
            template.format(n=step, name=name, ns=namespace, release=release)
        )
    text = "\n".join(blocks)
    if not text.endswith("\n"):
        text += "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    return text


def main() -> int:
    """CLI entry: parse `--release` / name / namespace / output and print or write."""
    parser = argparse.ArgumentParser(
        description="Render deterministic ODF SNO remediation commands (review before running)."
    )
    parser.add_argument(
        "--release",
        required=True,
        choices=RELEASES,
        help="validated ODF release the remediation targets (4.22 covers 4.22.1)",
    )
    parser.add_argument("--name", default="ocs-storagecluster")
    parser.add_argument("--namespace", default="openshift-storage")
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--context",
        default=None,
        help=(
            "kubeconfig context to pin every emitted `oc` to. Without it the "
            "script targets whatever context is current when it runs."
        ),
    )
    args = parser.parse_args()
    try:
        text = render_sno_remediation(
            args.release, args.name, args.namespace, args.output, args.context
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.output:
        print(f"SNO remediation script written to {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
