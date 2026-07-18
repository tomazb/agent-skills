#!/usr/bin/env bash
set -euo pipefail

# Read-only post-uninstall audit for OpenShift Data Foundation (ODF).
# A warning marks the audit as failed: any ODF residue needs an operator decision.

FAILED=0
QUERY_RESULT=""
QUERY_NOT_FOUND=0

fail() {
  echo "FAIL: $*"
  FAILED=1
}

warn() {
  echo "WARN: $*"
  FAILED=1
}

ok() {
  echo "OK: $*"
}

is_not_found() {
  case "$1" in
    *NotFound*|*not\ found*|*the\ server\ doesn\'t\ have\ a\ resource\ type*) return 0 ;;
    *) return 1 ;;
  esac
}

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    fail "$cmd CLI is required but not installed"
    return 1
  fi
}

check_api_group() {
  local group="$1"
  local resources

  if ! resources=$(oc api-resources --api-group="$group" --verbs=list -o name 2>&1); then
    fail "$group API resource discovery failed: $resources"
    return
  fi

  if [ -n "$resources" ]; then
    warn "$group API resources still exist:"
    echo "$resources"
  else
    ok "no $group API resources found"
  fi
}

check_absent_resource() {
  local label="$1"
  local ok_message="$2"
  shift 2

  local output
  if output=$(oc get "$@" 2>&1); then
    warn "$label still exists"
    [ -n "$output" ] && echo "$output"
  elif is_not_found "$output"; then
    ok "$ok_message"
  else
    fail "$label lookup failed: $output"
  fi

  return 0
}

query_json() {
  local label="$1"
  local jq_filter="$2"
  shift 2

  local json
  local output
  QUERY_RESULT=""
  QUERY_NOT_FOUND=0

  if ! json=$("$@" -o json 2>&1); then
    if is_not_found "$json"; then
      QUERY_NOT_FOUND=1
      return 0
    fi
    fail "$label query failed: $json"
    return 1
  fi

  if ! output=$(jq -r "$jq_filter" <<<"$json" 2>&1); then
    fail "$label jq filter failed: $output"
    return 1
  fi

  QUERY_RESULT="$output"
}

check_json_list() {
  local label="$1"
  local ok_message="$2"
  local jq_filter="$3"
  shift 3

  if query_json "$label" "$jq_filter" "$@"; then
    if [ "$QUERY_NOT_FOUND" -eq 1 ] || [ -z "$QUERY_RESULT" ]; then
      ok "$ok_message"
    else
      warn "$label still exist:"
      echo "$QUERY_RESULT"
    fi
  fi
}

count_nonempty_lines() {
  local value="$1"
  local count=0
  local line

  while IFS= read -r line; do
    if [ -n "$line" ]; then
      count=$((count + 1))
    fi
  done <<<"$value"

  echo "$count"
}

echo "=== ODF Post-Uninstall Audit ==="

require_command oc || exit 1
require_command jq || exit 1

if ! OC_USER=$(oc whoami 2>&1); then
  fail "unable to contact the cluster with oc whoami: $OC_USER"
  exit 1
fi

check_absent_resource \
  "openshift-storage namespace" \
  "openshift-storage namespace absent" \
  namespace openshift-storage

check_absent_resource \
  "rook-ceph namespace" \
  "rook-ceph namespace absent" \
  namespace rook-ceph

echo
check_api_group ocs.openshift.io
check_api_group ceph.rook.io
check_api_group noobaa.io
check_api_group csi.ceph.io
check_api_group local.storage.openshift.io

echo
check_json_list \
  "ODF StorageClasses" \
  "no ODF StorageClasses found" \
  '.items[] | select(.provisioner == "openshift-storage.rbd.csi.ceph.com" or .provisioner == "openshift-storage.cephfs.csi.ceph.com" or .provisioner == "openshift-storage.noobaa.io/obc" or .provisioner == "openshift-storage.ceph.rook.io/bucket") | .metadata.name' \
  oc get sc

echo
check_json_list \
  "ODF PVs" \
  "no ODF PVs found" \
  '.items[] | select((.spec.csi // {} | .driver == "openshift-storage.rbd.csi.ceph.com" or .driver == "openshift-storage.cephfs.csi.ceph.com") or ((.spec.storageClassName // "") | contains("ocs-storagecluster"))) | .metadata.name' \
  oc get pv

echo
check_json_list \
  "ODF PVCs" \
  "no ODF PVCs found" \
  '.items[] | select((.spec.storageClassName // "") | contains("ocs-storagecluster")) | .metadata.namespace + "/" + .metadata.name' \
  oc get pvc -A

echo
check_json_list \
  "Terminating PVCs" \
  "no Terminating PVCs found" \
  '.items[] | select(.status.phase == "Terminating") | .metadata.namespace + "/" + .metadata.name' \
  oc get pvc -A

echo
check_json_list \
  "Terminating PVs" \
  "no Terminating PVs found" \
  '.items[] | select(.status.phase == "Terminating") | .metadata.name' \
  oc get pv

echo
check_json_list \
  "ObjectBucketClaims" \
  "no ObjectBucketClaims found" \
  '.items[] | .metadata.namespace + "/" + .metadata.name' \
  oc get obc -A

echo
check_json_list \
  "ObjectBuckets" \
  "no ObjectBuckets found" \
  '.items[] | .metadata.name' \
  oc get objectbucket

echo
check_json_list \
  "ODF CSIDrivers" \
  "no ODF CSIDrivers found" \
  '.items[] | select(.metadata.name == "openshift-storage.rbd.csi.ceph.com" or .metadata.name == "openshift-storage.cephfs.csi.ceph.com") | .metadata.name' \
  oc get csidriver

echo
check_json_list \
  "ODF SCCs" \
  "no ODF SCCs found" \
  '.items[] | select((.metadata.name | contains("rook-ceph")) or (.metadata.name | contains("noobaa"))) | .metadata.name' \
  oc get scc

echo
if query_json \
  "default StorageClasses" \
  '.items[] | select((.metadata.annotations?["storageclass.kubernetes.io/is-default-class"] == "true") or (.metadata.annotations?["storageclass.beta.kubernetes.io/is-default-class"] == "true")) | .metadata.name' \
  oc get sc; then
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    fail "default StorageClasses could not be queried because StorageClass is unavailable"
  else
    DEFAULT_SCS="$QUERY_RESULT"
    COUNT=$(count_nonempty_lines "$DEFAULT_SCS")
    if [ "$COUNT" -eq 1 ]; then
      ok "exactly one default StorageClass: $DEFAULT_SCS"
    elif [ "$COUNT" -eq 0 ]; then
      warn "no default StorageClass found"
    else
      warn "multiple default StorageClasses found:"
      echo "$DEFAULT_SCS"
    fi
  fi
fi

echo "=== Audit Complete ==="
exit "$FAILED"
