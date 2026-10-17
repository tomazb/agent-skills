#!/usr/bin/env bash
# Delete one finished ODF smoke namespace and fail if any of it remains: the
# namespace itself, a PV that still claims it, or (with --object) an
# ObjectBucket whose claimRef.namespace is exactly that namespace. The PV check polls for
# CLEANUP_PV_WAIT_SECONDS (default 120) because a Delete reclaim can lag.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: cleanup_smoke_namespace.sh --namespace NAME [--object]' \
    '' \
    'Delete a finished smoke namespace and fail closed if the delete did not' \
    'finish. NAME must be a *-smoke namespace.' \
    '' \
    '  --namespace NAME  namespace to delete' \
    '  --object          also fail if an ObjectBucket claimRef.namespace is NAME' \
    '  -h, --help        show this help' \
    '' \
    'Environment:' \
    '  CLEANUP_PV_WAIT_SECONDS  seconds to wait for PVs that claim NAME to' \
    '                           disappear (default 120, 0 = one check)'
}

namespace=""
check_object=0
while [ $# -gt 0 ]; do
  case "$1" in
    --namespace)
      if [ $# -lt 2 ]; then
        echo "missing value for --namespace" >&2
        exit 2
      fi
      namespace=$2
      shift 2
      ;;
    --namespace=*)
      namespace=${1#--namespace=}
      shift
      ;;
    --object)
      check_object=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$namespace" ]; then
  echo "missing --namespace" >&2
  exit 2
fi
namespace_re='^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
if [ "${#namespace}" -gt 63 ] || [[ ! "$namespace" =~ $namespace_re ]]; then
  echo "invalid namespace: $namespace" >&2
  exit 2
fi
case "$namespace" in
  *-smoke) ;;
  *)
    echo "refusing to delete ${namespace}: only a *-smoke namespace" >&2
    exit 2
    ;;
esac

pv_wait=${CLEANUP_PV_WAIT_SECONDS:-120}
pv_wait_re='^[0-9]+$'
if [[ ! "$pv_wait" =~ $pv_wait_re ]]; then
  echo "invalid CLEANUP_PV_WAIT_SECONDS: ${pv_wait}" >&2
  exit 2
fi

if ! oc delete namespace "$namespace" --ignore-not-found --wait=true --timeout=5m; then
  echo "failed to delete ${namespace}" >&2
  exit 1
fi

if ! namespaces=$(oc get namespaces -o name); then
  echo "could not list namespaces - cleanup unverified" >&2
  exit 1
fi
if [ -z "$namespaces" ]; then
  echo "could not list namespaces - cleanup unverified" >&2
  exit 1
fi
if printf '%s\n' "$namespaces" | grep -Fx "namespace/${namespace}" >/dev/null; then
  echo "${namespace} still exists" >&2
  exit 1
fi

# Delete-policy PVs can outlive the namespace for a short while, so poll the
# claim check until the deadline instead of reading once.
pv_interval=5
pv_deadline=$((SECONDS + pv_wait))
while true; do
  if ! pv_json=$(oc get pv -o json); then
    echo "could not inspect PVs - cleanup unverified" >&2
    exit 1
  fi
  if ! pv_claims=$(printf '%s' "$pv_json" | python3 -c '
import json, sys
ns = sys.argv[1]
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.stderr.write("could not parse PV list - cleanup unverified\n")
    sys.exit(1)
items = data.get("items")
if items is None:
    items = [data] if data.get("kind") == "PersistentVolume" else []
for item in items:
    claim = (item.get("spec") or {}).get("claimRef") or {}
    if claim.get("namespace") == ns:
        name = (item.get("metadata") or {}).get("name") or "unnamed"
        policy = (item.get("spec") or {}).get("persistentVolumeReclaimPolicy") or ""
        print(name + "\t" + policy)
' "$namespace"); then
    echo "could not inspect PVs - cleanup unverified" >&2
    exit 1
  fi
  if [ -z "$pv_claims" ]; then
    break
  fi
  pv_remaining=$((pv_deadline - SECONDS))
  if [ "$pv_remaining" -le 0 ]; then
    pv_names=$(printf '%s\n' "$pv_claims" | cut -f1)
    printf 'leftover PVs still claim %s:\n%s\n' "$namespace" "$pv_names" >&2
    pv_retained=$(printf '%s\n' "$pv_claims" | awk -F '\t' '$2 == "Retain" { print $1 }')
    if [ -n "$pv_retained" ]; then
      printf 'persistentVolumeReclaimPolicy is Retain for:\n%s\n' "$pv_retained" >&2
    fi
    exit 1
  fi
  if [ "$pv_remaining" -lt "$pv_interval" ]; then
    sleep "$pv_remaining"
  else
    sleep "$pv_interval"
  fi
done

if [ "$check_object" -eq 1 ]; then
  if ! bucket_json=$(oc get objectbucket -o json); then
    echo "could not inspect ObjectBuckets - cleanup unverified" >&2
    exit 1
  fi
  if ! leftovers=$(printf '%s' "$bucket_json" | python3 -c '
import json, sys
ns = sys.argv[1]
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.stderr.write("could not parse ObjectBucket list - cleanup unverified\n")
    sys.exit(1)
items = data.get("items")
if items is None:
    items = [data] if data.get("kind") == "ObjectBucket" else []
for item in items:
    claim = (item.get("spec") or {}).get("claimRef") or {}
    if claim.get("namespace") == ns:
        print((item.get("metadata") or {}).get("name") or "unnamed")
' "$namespace"); then
    echo "could not inspect ObjectBuckets - cleanup unverified" >&2
    exit 1
  fi
  if [ -n "$leftovers" ]; then
    printf 'leftover ObjectBuckets after deleting the claim:\n%s\n' "$leftovers" >&2
    exit 1
  fi
fi

echo "deleted smoke namespace ${namespace}"
