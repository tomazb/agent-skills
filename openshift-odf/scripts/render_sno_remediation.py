#!/usr/bin/env python3
"""Render the deterministic ODF 4.20/4.22 SNO post-install remediation commands.

This is a GENERATOR: it prints a reviewable bash script and never executes
`oc` or `ceph`. It emits only the fixed, kube-API-level patches that are safe
to apply once the CephCluster is Ready. Pool sizing (the live `ceph osd pool
ls` loop and the CephFilesystem/CephObjectStore size patches), the health mute
and client recovery are intentionally NOT emitted as executable commands;
follow the runbooks referenced in the banner for those stateful steps.

The remediation differs per ODF release, so `--release` is mandatory: the
CephBlockPool failure-domain fix applies to 4.20 only, while the object/file
`replicasPerFailureDomain` removal and the resource-request floor apply to
4.22 only. Emitting both against one cluster would fail under `set -e`.
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
# This script applies ONLY the deterministic, kube-API patches validated for
# ODF {release}. It does NOT perform pool sizing, the POOL_NO_REDUNDANCY mute
# or StorageClient onboarding recovery, which are stateful:
#   * Pool sizing (size=1 loop, CephFilesystem/CephObjectStore pool patches):
#     follow references/validated-odf-sno.md "Regression 2".
#   * StorageClient onboarding recovery:
#     follow references/validation-hardening.md troubleshooting.
set -euo pipefail
"""

# Must render before any mutating command: --release only selects templates, so
# without this the wrong-release script mutates resources and only then fails on
# an inapplicable patch. `set -e` stops the run, it does not undo those writes.
_RELEASE_PREFLIGHT = """\
# {n}. Preflight: refuse to run against a different ODF release.
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

# ODF 4.20 only: 4.22 ships the CephBlockPool with a failure domain Rook accepts.
_BLOCKPOOL_FD = """\
# {n}. CephBlockPool (4.20 only): Rook rejects size=1 while failureDomain=osd +
#    replicasPerFailureDomain=1 ("size must be greater than
#    replicasPerFailureDomain"). Switch to host, drop replicasPerFailureDomain,
#    and persist size=1 in the CR — Rook reconciles this CR even while
#    ocs-operator ignores it, so a live-only `ceph osd pool set` is reverted.
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
#    references/validated-odf-sno.md "Regression 2" has been applied. Run these
#    two commands by hand after that step, never before:
#      ROOK_OP=$(oc -n {ns} get pods -l app=rook-ceph-operator -o name | head -1)
#      CONF="/var/lib/rook/{ns}/{ns}.config"
#      oc -n {ns} exec "$ROOK_OP" -- ceph -c "$CONF" health mute POOL_NO_REDUNDANCY
"""

# ODF 4.22 only (Ceph 20.2 "tentacle").
_OBJECT_FILE_FD = """\
# {n}. ODF 4.22 (Ceph 20.2 tentacle): the CephObjectStore and CephFilesystem
#    metadata/data pools reject size=1 while replicasPerFailureDomain=1
#    ("size must be greater"). CephBlockPool tolerates it, but the object and
#    file controllers do not — RGW and MDS never start. Drop the field (keep
#    size=1) so both reconcile.
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
  {{"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}},
  {{"op":"remove","path":"/spec/dataPool/replicated/replicasPerFailureDomain"}}
]'
oc -n {ns} patch cephfilesystem {name}-cephfilesystem --type json -p '[
  {{"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}},
  {{"op":"remove","path":"/spec/dataPools/0/replicated/replicasPerFailureDomain"}}
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

# Ordered per release. The step numbers are assigned at render time so each
# release gets a contiguous 1..N sequence instead of gaps where a block is
# skipped.
_BLOCKS = {
    "4.20": (
        _RELEASE_PREFLIGHT,
        _RECONCILE_IGNORE,
        _TOPOLOGYKEY,
        _BLOCKPOOL_FD,
        _CSI_REPLICAS,
        _MUTE,
    ),
    "4.22": (
        _RELEASE_PREFLIGHT,
        _RECONCILE_IGNORE,
        _TOPOLOGYKEY,
        _OBJECT_FILE_FD,
        _CSI_REPLICAS,
        _RESOURCE_REQUESTS,
        _MUTE,
    ),
}


def _validate_name(label: str, value: str) -> str:
    # 63 is the RFC 1123 label limit Kubernetes enforces; a longer value renders
    # fine here but every emitted `oc` command would be rejected by the API.
    # fullmatch, not match: `$` also matches before a trailing newline, so
    # "my-ns\n" would pass and then split every emitted `oc` command in two.
    if _RFC1123.fullmatch(value) is None or len(value) > 63:
        raise ValueError(
            f"{label} {value!r} is not a valid RFC 1123 name "
            "(lowercase alphanumerics and '-', must start and end alphanumeric, "
            "max 63 characters)"
        )
    return value


def render_sno_remediation(
    release: str,
    name: str = "ocs-storagecluster",
    namespace: str = "openshift-storage",
    output: str | None = None,
) -> str:
    if release not in _BLOCKS:
        raise ValueError(
            f"release {release!r} is not a validated ODF SNO release; "
            f"expected one of {', '.join(RELEASES)}"
        )
    _validate_name("name", name)
    _validate_name("namespace", namespace)

    blocks = [BANNER.format(release=release)]
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
    args = parser.parse_args()
    try:
        text = render_sno_remediation(
            args.release, args.name, args.namespace, args.output
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
