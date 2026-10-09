#!/usr/bin/env bash
set -euo pipefail

# Read-only: classify who runs Ceph on the cluster before anything Rook shares with
# ODF (the ceph.rook.io, csi.ceph.io, and objectbucket.io CRDs, the rook-ceph and
# rook-ceph-csi SCCs) is deleted. The rule is ROOK_CEPH_OWNERSHIP_JQ in rook_common.sh.
#
# stdout: the upstream Rook namespaces on one line, space-separated; empty when
#         there is none. Nothing else goes to stdout, so `$(...)` captures it cleanly.
# stderr: the cluster classified, one line per Rook namespace, per ODF signal, and
#         per object whose owner is unknown, then the verdict.
# exit:   0 classified: "upstream Rook only" or "no Rook or ODF".
#         1 ODF present (hand off to openshift-odf), or could not classify: an oc
#           failure (only "no such resource type" for the CephCluster CRD reads as
#           none; the ODF and Ceph CSI kinds are read only when the API serves
#           them), empty or unparseable output, a jq failure, or any CephCluster,
#           operator, or Ceph CSI whose owner is unknown.
#         2 bad arguments.
# A caller that deletes anything shared with ODF must continue only on exit 0.

OC_GLOBAL_ARGS=()
OC_CONTEXT_LABEL=""

# printf, not `cat <<EOF`: usage must work when PATH holds nothing but oc and jq.
usage() {
  printf '%s\n' \
    'Usage: classify_ceph_ownership.sh [--context NAME] [--kubeconfig PATH]' \
    '                                  [--namespace NAME] [--csi-prefix PREFIX]' \
    '' \
    'Read-only. Prints the namespaces running an upstream (non-OLM) Rook cluster on' \
    'stdout and the verdict on stderr. Exit 0 classified (Rook only, or nothing),' \
    '1 ODF present or could not classify.' \
    '' \
    '  --context NAME       kubeconfig context to use (default: the current one)' \
    '  --kubeconfig PATH    kubeconfig file to use' \
    '  --namespace NAME     Rook operator namespace (default: rook-ceph)' \
    '  --csi-prefix PREFIX  CSI_DRIVER_NAME_PREFIX of this Rook (default: the namespace)' \
    '  -h, --help           show this help'
}

case "${BASH_SOURCE[0]}" in
  */*) SCRIPT_DIR="${BASH_SOURCE[0]%/*}" ;;
  *) SCRIPT_DIR="." ;;
esac
# shellcheck source-path=SCRIPTDIR
# shellcheck source=rook_common.sh
source "$SCRIPT_DIR/rook_common.sh"

parse_oc_args "$@"

stop() {
  echo "verdict: unknown - $* - do not delete anything shared with ODF" >&2
  exit 1
}

for cmd in oc jq; do
  command -v "$cmd" >/dev/null 2>&1 || stop "$cmd CLI is required but not installed"
done

oc() { command oc "${OC_GLOBAL_ARGS[@]}" "$@"; }

# Fail before any lookup if the cluster cannot be reached as requested (an unknown
# --context, an expired login), and name the cluster the verdict is for.
run_split oc whoami
[ "$RUN_RC" -eq 0 ] || stop "cannot reach the cluster: $RUN_ERR"
run_split oc whoami --show-server
echo "classifying ${RUN_OUT:-unknown server}${OC_CONTEXT_LABEL:+ (context: $OC_CONTEXT_LABEL)}" >&2

# Fetch a list as JSON into LIST_JSON. With "missing-type-is-empty", only "the
# server doesn't have a resource type" reads as an empty list; every other
# failure, and a success that printed nothing, stops the run.
fetch_list() {
  local label="$1"
  local tolerance="$2"
  shift 2

  run_split "$@" -o json
  if [ "$RUN_RC" -ne 0 ]; then
    if [ "$tolerance" = "missing-type-is-empty" ] && is_missing_resource_type "$RUN_ERR"; then
      LIST_JSON='{"items":[]}'
      return 0
    fi
    stop "$label lookup failed: $RUN_ERR"
  fi
  [ -n "$RUN_OUT" ] || stop "$label lookup returned nothing"
  LIST_JSON="$RUN_OUT"
}

# Fetch a CRD-backed list only when the API serves it. Discovery is strict, so an
# absent group is read from a successful, empty discovery, never from an error.
fetch_if_served() {
  local label="$1"
  local group="$2"
  local resource="$3"
  shift 3

  local line
  run_split oc api-resources --api-group="$group" --verbs=list -o name
  [ "$RUN_RC" -eq 0 ] || stop "$group API discovery failed: $RUN_ERR"
  while IFS= read -r line; do
    if [ "$line" = "$resource" ]; then
      fetch_list "$label" strict oc get "$resource" "$@"
      return 0
    fi
  done <<<"$RUN_OUT"
  LIST_JSON='{"items":[]}'
}

fetch_list "CephCluster" missing-type-is-empty oc get cephclusters.ceph.rook.io -A
clusters="$LIST_JSON"
fetch_list "rook-ceph-operator Deployment" strict \
  oc get deployments -A --field-selector metadata.name=rook-ceph-operator
deployments="$LIST_JSON"
fetch_if_served "StorageCluster" ocs.openshift.io storageclusters.ocs.openshift.io -A
storageclusters="$LIST_JSON"
fetch_list "Subscription" strict oc get subscriptions.operators.coreos.com -A
subscriptions="$LIST_JSON"
fetch_list "ClusterServiceVersion" strict oc get clusterserviceversions.operators.coreos.com -A
csvs="$LIST_JSON"
# A Ceph CSI can outlive its operator and CephCluster while it still serves volumes.
fetch_if_served "Ceph CSI Driver" csi.ceph.io drivers.csi.ceph.io -A
csi_drivers="$LIST_JSON"
fetch_list "CSIDriver" strict oc get csidrivers
csidrivers="$LIST_JSON"
fetch_list "PersistentVolume" strict oc get pv
pvs="$LIST_JSON"

run_split jq_slurp "$ROOK_CEPH_OWNERSHIP_JQ" "$clusters" "$deployments" "$storageclusters" \
  "$subscriptions" "$csvs" "$csi_drivers" "$csidrivers" "$pvs" "\"$ROOK_CSI_DRIVER_RE\""
[ "$RUN_RC" -eq 0 ] || stop "could not parse the Ceph ownership lists: $RUN_ERR"

namespaces=""
odf=""
unknown=""
while IFS=$'\t' read -r kind subject detail; do
  case "$kind" in
    rook)
      namespaces="${namespaces:+$namespaces }$subject"
      echo "upstream Rook in $subject: CephCluster: $detail" >&2 ;;
    odf)
      odf="${odf:+$odf, }$subject"
      echo "ODF: $subject: $detail" >&2 ;;
    unknown)
      unknown="${unknown:+$unknown, }$subject"
      echo "unknown owner of $subject: $detail" >&2 ;;
  esac
done <<<"$RUN_OUT"

if [ -n "$odf" ]; then
  echo "verdict: ODF present ($odf) - hand off to openshift-odf; do not delete shared CRDs or SCCs" >&2
  exit 1
fi
[ -z "$unknown" ] || stop "ownership of $unknown could not be classified"

if [ -n "$namespaces" ]; then
  echo "verdict: upstream Rook only, in: $namespaces" >&2
else
  echo "verdict: no Rook or ODF" >&2
fi
printf '%s\n' "$namespaces"
