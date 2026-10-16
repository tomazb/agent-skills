#!/usr/bin/env bash
# Delete one finished ODF smoke namespace and fail if any of it remains: the
# namespace itself, a PV that still claims it, or (with --object) an
# ObjectBucket whose name contains it.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: cleanup_smoke_namespace.sh --namespace NAME [--object]' \
    '' \
    'Delete a finished smoke namespace and fail closed if the delete did not' \
    'finish. NAME must be a *-smoke namespace.' \
    '' \
    '  --namespace NAME  namespace to delete' \
    '  --object          also fail if an ObjectBucket name contains NAME' \
    '  -h, --help        show this help'
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

if ! pv_json=$(oc get pv -o json); then
  echo "could not inspect PVs - cleanup unverified" >&2
  exit 1
fi
if ! pv_names=$(printf '%s' "$pv_json" | python3 -c '
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
        print((item.get("metadata") or {}).get("name") or "unnamed")
' "$namespace"); then
  echo "could not inspect PVs - cleanup unverified" >&2
  exit 1
fi
if [ -n "$pv_names" ]; then
  printf 'leftover PVs still claim %s:\n%s\n' "$namespace" "$pv_names" >&2
  exit 1
fi

if [ "$check_object" -eq 1 ]; then
  if ! buckets=$(oc get objectbucket -o name); then
    echo "could not inspect ObjectBuckets - cleanup unverified" >&2
    exit 1
  fi
  leftovers=$(printf '%s\n' "$buckets" | grep -F "$namespace" || true)
  if [ -n "$leftovers" ]; then
    printf 'leftover ObjectBuckets after deleting the claim:\n%s\n' "$leftovers" >&2
    exit 1
  fi
fi

echo "deleted smoke namespace ${namespace}"
