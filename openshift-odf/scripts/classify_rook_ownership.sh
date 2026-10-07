#!/usr/bin/env bash
set -euo pipefail

# Read-only: classify whether an upstream (non-OLM) Rook cluster runs next to, or
# after, ODF, before anything shared with Rook is deleted. The rule is
# ODF_CEPH_OWNERSHIP_JQ in odf_common.sh.
#
# stdout: the upstream Rook namespaces on one line, space-separated; empty when
#         there is none. Nothing else goes to stdout, so `$(...)` captures it cleanly.
# stderr: the cluster classified, one line per upstream namespace, per residue
#         CephCluster, and per object whose owner is unknown, then the verdict.
# exit:   0 classified: "upstream Rook present in: ..." or "no upstream Rook".
#         1 could not classify: an oc failure (only "no such resource type" for
#           the CephCluster and Ceph CSI Driver CRDs reads as none), empty or
#           unparseable output, a jq failure, or any CephCluster, operator, or
#           leftover non-ODF Ceph CSI whose owner is unknown.
#         2 bad arguments.
# A caller that deletes Rook-shared objects must continue only on exit 0.

OC_GLOBAL_ARGS=()
OC_CONTEXT_LABEL=""

# printf, not `cat <<EOF`: usage must work when PATH holds nothing but oc and jq.
usage() {
  printf '%s\n' \
    'Usage: classify_rook_ownership.sh [--context NAME] [--kubeconfig PATH]' \
    '' \
    'Read-only. Prints the namespaces running an upstream (non-OLM) Rook cluster on' \
    'stdout and the verdict on stderr. Exit 0 classified, 1 could not classify.' \
    '' \
    '  --context NAME       kubeconfig context to use (default: the current one)' \
    '  --kubeconfig PATH    kubeconfig file to use' \
    '  -h, --help           show this help'
}

case "${BASH_SOURCE[0]}" in
  */*) SCRIPT_DIR="${BASH_SOURCE[0]%/*}" ;;
  *) SCRIPT_DIR="." ;;
esac
# shellcheck source-path=SCRIPTDIR
# shellcheck source=odf_common.sh
source "$SCRIPT_DIR/odf_common.sh"

parse_oc_args "$@"

stop() {
  echo "verdict: unknown - $* - do not delete anything shared with Rook" >&2
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

fetch_list "CephCluster" missing-type-is-empty oc get cephclusters.ceph.rook.io -A
clusters="$LIST_JSON"
fetch_list "rook-ceph-operator Deployment" strict \
  oc get deployments -A --field-selector metadata.name=rook-ceph-operator
deployments="$LIST_JSON"
# A Ceph CSI can outlive its operator and CephCluster while it still serves volumes.
fetch_list "Ceph CSI Driver" missing-type-is-empty oc get drivers.csi.ceph.io -A
csi_drivers="$LIST_JSON"
fetch_list "CSIDriver" strict oc get csidrivers
csidrivers="$LIST_JSON"
fetch_list "PersistentVolume" strict oc get pv
pvs="$LIST_JSON"

run_split jq_slurp "$ODF_CEPH_OWNERSHIP_JQ" "$clusters" "$deployments" "$csi_drivers" "$csidrivers" "$pvs"
[ "$RUN_RC" -eq 0 ] || stop "could not parse the Ceph ownership lists: $RUN_ERR"

namespaces=""
unknown=""
while IFS=$'\t' read -r kind subject detail; do
  case "$kind" in
    upstream)
      namespaces="${namespaces:+$namespaces }$subject"
      echo "upstream Rook in $subject: CephCluster: $detail" >&2 ;;
    residue)
      echo "residue CephCluster $subject: $detail" >&2 ;;
    unknown)
      unknown="${unknown:+$unknown, }$subject"
      echo "unknown owner of $subject: $detail" >&2 ;;
  esac
done <<<"$RUN_OUT"

[ -z "$unknown" ] || stop "ownership of $unknown could not be classified"

if [ -n "$namespaces" ]; then
  echo "verdict: upstream Rook present in: $namespaces" >&2
else
  echo "verdict: no upstream Rook" >&2
fi
printf '%s\n' "$namespaces"
