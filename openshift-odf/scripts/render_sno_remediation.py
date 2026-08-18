#!/usr/bin/env python3
"""Render the deterministic ODF 4.20/4.22 SNO post-install remediation commands.

This is a GENERATOR: it prints a reviewable bash script and never executes
`oc` or `ceph`. It emits only the fixed, kube-API-level patches that are safe
to apply once the CephCluster is Ready. Pool sizing (the live `ceph osd pool
ls` loop and the CephFilesystem/CephObjectStore size patches) and client
recovery are intentionally NOT emitted; follow the runbooks referenced in the
banner for those stateful steps.
"""
from __future__ import annotations

import argparse
from pathlib import Path

BANNER = """\
#!/usr/bin/env bash
# ODF 4.20/4.22 SNO deterministic remediation — REVIEW BEFORE RUNNING.
#
# Prerequisite: the CephCluster is Ready (mons up, OSD up/in).
#
# This script applies ONLY the deterministic, kube-API patches. It does NOT
# perform pool sizing or StorageClient onboarding recovery, which are stateful:
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
# 6. Mute the expected single-replica warning. Run AFTER pool sizing from the
#    runbook (POOL_NO_REDUNDANCY is only correct once pools are size=1).
ROOK_OP=$(oc -n {ns} get pods -l app=rook-ceph-operator -o name | head -1)
CONF="/var/lib/rook/{ns}/{ns}.config"
oc -n {ns} exec "$ROOK_OP" -- ceph -c "$CONF" health mute POOL_NO_REDUNDANCY
"""

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
  {{"op":"remove","path":"/spec/metadataPool/replicated/replicasPerFailureDomain"}},
  {{"op":"remove","path":"/spec/dataPools/0/replicated/replicasPerFailureDomain"}}
]'
"""

_RESOURCE_REQUESTS = """\
# 5. SNO CPU-request starvation: ODF's default 'balanced' requests (mon 1050m,
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
        _OBJECT_FILE_FD.format(name=name, ns=namespace),
        _CSI_REPLICAS.format(name=name, ns=namespace),
        _RESOURCE_REQUESTS.format(name=name, ns=namespace),
        _MUTE.format(name=name, ns=namespace),
    ]
    text = "\n".join(blocks)
    if not text.endswith("\n"):
        text += "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render deterministic ODF 4.20 SNO remediation commands (review before running)."
    )
    parser.add_argument("--name", default="ocs-storagecluster")
    parser.add_argument("--namespace", default="openshift-storage")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    text = render_sno_remediation(args.name, args.namespace, args.output)
    if args.output:
        print(f"SNO remediation script written to {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
