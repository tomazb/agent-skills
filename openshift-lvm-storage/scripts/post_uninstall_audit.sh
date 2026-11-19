#!/usr/bin/env bash
set -euo pipefail

# Read-only post-uninstall audit for LVMS / TopoLVM on OpenShift/OKD.
# This script checks for leftover resources after an LVMS uninstall.

FAILED=0
QUERY_RESULT=""

case "$#" in
  0) namespaces=(openshift-lvm-storage openshift-storage) ;;
  1)
    if [[ "$1" == "--help" || "$1" == "-h" ]]; then
      echo "Usage: post_uninstall_audit.sh [--namespace NAME]"
      echo "By default, checks openshift-lvm-storage and openshift-storage."
      exit 0
    fi
    echo "Expected --namespace NAME" >&2
    exit 2
    ;;
  2)
    if [[ "$1" != "--namespace" || ! "$2" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ || ${#2} -gt 63 ]]; then
      echo "Expected --namespace NAME with a valid namespace name" >&2
      exit 2
    fi
    namespaces=("$2")
    ;;
  *) echo "Expected --namespace NAME" >&2; exit 2 ;;
esac

fail() {
  echo "FAIL: $*"
  FAILED=1
}

warn() {
  echo "WARN: $*"
}

ok() {
  echo "OK: $*"
}

is_not_found() {
  case "$1" in
    *NotFound*|*not\ found*) return 0 ;;
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
}

query_json() {
  local label="$1"
  local jq_filter="$2"
  shift 2

  local json
  local output
  QUERY_RESULT=""

  if ! json=$("$@" -o json 2>&1); then
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
    if [ -n "$QUERY_RESULT" ]; then
      warn "$label still exist:"
      echo "$QUERY_RESULT"
    else
      ok "$ok_message"
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

echo "=== LVMS Post-Uninstall Audit ==="

require_command oc || exit 1
require_command jq || exit 1

if ! OC_USER=$(oc whoami 2>&1); then
  fail "unable to contact the cluster with oc whoami: $OC_USER"
  exit 1
fi

check_api_group topolvm.io
check_api_group lvm.topolvm.io

echo
check_absent_resource "csidriver/topolvm.io" "csidriver/topolvm.io absent" csidriver topolvm.io

echo
check_json_list \
  "TopoLVM StorageClasses" \
  "no TopoLVM StorageClasses found" \
  '.items[] | select(.provisioner == "topolvm.io") | .metadata.name' \
  oc get sc

echo
check_json_list \
  "TopoLVM PVs" \
  "no TopoLVM PVs found" \
  '.items[] | select(.spec.csi // {} | .driver == "topolvm.io") | .metadata.name' \
  oc get pv

echo
check_json_list \
  "LVMS PVCs" \
  "no LVMS PVCs found" \
  '.items[] | select(((.spec.storageClassName // "") | contains("lvms")) or ((.spec.storageClassName // "") | contains("topolvm"))) | .metadata.namespace + "/" + .metadata.name' \
  oc get pvc -A

echo
check_json_list \
  "TopoLVM/LVMS SCCs" \
  "no TopoLVM/LVMS SCCs found" \
  '.items[] | select((.metadata.name | contains("topolvm")) or (.metadata.name | contains("lvms"))) | .metadata.name' \
  oc get scc

echo
for namespace in "${namespaces[@]}"; do
  if NAMESPACE_OUTPUT=$(oc get namespace "$namespace" 2>&1); then
    warn "$namespace namespace still exists"
    echo "$NAMESPACE_OUTPUT"
    if ! STORAGE_OUTPUT=$(oc -n "$namespace" get all 2>&1); then
      fail "$namespace workload listing failed: $STORAGE_OUTPUT"
    elif [ -n "$STORAGE_OUTPUT" ]; then
      echo "$STORAGE_OUTPUT"
    fi
  elif is_not_found "$NAMESPACE_OUTPUT"; then
    ok "$namespace namespace absent"
  else
    fail "$namespace namespace lookup failed: $NAMESPACE_OUTPUT"
  fi
done

echo
check_json_list \
  "LVMS CSVs" \
  "no LVMS CSVs found" \
  '.items[] | select(.metadata.name | contains("lvms")) | .metadata.namespace + "/" + .metadata.name' \
  oc get csv -A

echo
check_json_list \
  "LVMS Subscriptions" \
  "no LVMS Subscriptions found" \
  '.items[] | select(.metadata.name | contains("lvms")) | .metadata.namespace + "/" + .metadata.name' \
  oc get subscription -A

echo
if query_json \
  "default StorageClasses" \
  '.items[] | select((.metadata.annotations?["storageclass.kubernetes.io/is-default-class"] == "true") or (.metadata.annotations?["storageclass.beta.kubernetes.io/is-default-class"] == "true")) | .metadata.name' \
  oc get sc; then
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

echo "=== Audit Complete ==="
exit "$FAILED"
