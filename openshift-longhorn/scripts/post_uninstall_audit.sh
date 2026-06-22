#!/usr/bin/env bash
set -euo pipefail

LONGHORN_NAMESPACE="${1:-longhorn-system}"

run_allow_fail() {
  printf '\n$'
  printf ' %s' "$@"
  printf '\n'
  "$@" || true
}

run_shell_allow_fail() {
  printf '\n$ %s\n' "$*"
  bash -o pipefail -c "$*" || true
}

run_allow_fail oc get namespace "${LONGHORN_NAMESPACE}"
run_allow_fail oc api-resources --api-group=longhorn.io
run_allow_fail oc get validatingwebhookconfiguration longhorn-webhook-validator
run_allow_fail oc get mutatingwebhookconfiguration longhorn-webhook-mutator
run_allow_fail oc get csidriver driver.longhorn.io
run_shell_allow_fail "oc get clusterrole,clusterrolebinding -o name | grep -i longhorn"
run_allow_fail oc get priorityclass longhorn-critical
run_allow_fail oc get storageclass -o wide
run_allow_fail oc get pv,pvc -A -o wide
