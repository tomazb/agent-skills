#!/usr/bin/env bash
set -euo pipefail

# Read-only: classify whether an upstream (non-OLM) Rook cluster runs next to, or
# after, ODF, before anything shared with Rook is deleted.
#
# stdout: the upstream Rook namespaces on one line, space-separated; empty when
#         there is none. Nothing else goes to stdout, so `$(...)` captures it cleanly.
# stderr: the verdict line, one line per upstream namespace, and one line per
#         CephCluster that is residue, with the reason.
# exit:   0 classified (either way), 1 could not classify, 2 bad arguments.
#
# Any failure to classify exits 1: an oc error other than "no such resource type",
# a successful call with empty or unparseable output, or a jq failure. A caller that
# deletes Rook-shared objects must continue only on exit 0.

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

# Fetch a list as JSON into LIST_JSON. "No such resource type" is an empty list;
# every other failure, and a success that printed nothing, stops the run.
fetch_list() {
  local label="$1"
  shift

  run_split "$@" -o json
  if [ "$RUN_RC" -ne 0 ]; then
    if is_not_found "$RUN_ERR"; then
      LIST_JSON='{"items":[]}'
      return 0
    fi
    stop "$label lookup failed: $RUN_ERR"
  fi
  [ -n "$RUN_OUT" ] || stop "$label lookup returned nothing"
  LIST_JSON="$RUN_OUT"
}

fetch_list "CephCluster" oc get cephclusters.ceph.rook.io -A
clusters="$LIST_JSON"
fetch_list "rook-ceph-operator Deployment" \
  oc get deployments -A --field-selector metadata.name=rook-ceph-operator
deployments="$LIST_JSON"

run_split jq_slurp "$ODF_CEPH_OWNERSHIP_JQ" "$clusters" "$deployments"
[ "$RUN_RC" -eq 0 ] || stop "could not parse the CephCluster or Deployment list: $RUN_ERR"

namespaces=""
while IFS=$'\t' read -r kind subject detail; do
  case "$kind" in
    upstream)
      namespaces="${namespaces:+$namespaces }$subject"
      echo "upstream Rook in $subject: non-OLM rook-ceph-operator Deployment, CephCluster: $detail" >&2 ;;
    residue)
      echo "residue CephCluster $subject: $detail" >&2 ;;
  esac
done <<<"$RUN_OUT"

if [ -n "$namespaces" ]; then
  echo "verdict: upstream Rook present in: $namespaces" >&2
else
  echo "verdict: no upstream Rook" >&2
fi
printf '%s\n' "$namespaces"
