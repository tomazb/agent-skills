#!/usr/bin/env bash
# Delete one finished LVM Storage smoke namespace and fail if it remains,
# or if a PV or VolumeSnapshotContent still references it.
# Poll PV and snapshot cleanup for
# CLEANUP_PV_WAIT_SECONDS (default 120) because Delete reclaim can lag.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: cleanup_smoke_namespace.sh --namespace NAME [--context NAME]' \
    '' \
    'Delete a finished smoke namespace and fail closed if the delete did not' \
    'finish. NAME must be a *-smoke namespace.' \
    '' \
    '  --namespace NAME  namespace to delete' \
    '  --context NAME    use this oc context for all cleanup commands' \
    '  -h, --help        show this help' \
    '' \
    'Environment:' \
    '  CLEANUP_PV_WAIT_SECONDS  seconds to wait for PVs that claim NAME to' \
    '                           disappear; also wait this long for snapshot' \
    '                           contents (default 120, 0 = one check)'
}

namespace=""
context_args=()
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
    --context)
      if [ $# -lt 2 ] || [ -z "$2" ] || [[ "$2" == --* ]]; then
        echo "missing value for --context" >&2
        exit 2
      fi
      context_args=(--context "$2")
      shift 2
      ;;
    --context=*)
      if [ -z "${1#--context=}" ]; then
        echo "missing value for --context" >&2
        exit 2
      fi
      context_args=(--context "${1#--context=}")
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

if ! oc "${context_args[@]}" delete namespace "$namespace" --ignore-not-found --wait=true --timeout=5m; then
  echo "failed to delete ${namespace}" >&2
  exit 1
fi

if ! namespaces=$(oc "${context_args[@]}" get namespaces -o name); then
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
  if ! pv_json=$(oc "${context_args[@]}" get pv -o json); then
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

# Snapshot contents are cluster-scoped and may outlive the deleted namespace.
# Only successful empty discovery establishes that this optional API is absent.
if ! snapshot_apis=$(oc "${context_args[@]}" api-resources --api-group=snapshot.storage.k8s.io -o name); then
  echo "could not discover snapshot APIs - cleanup unverified" >&2
  exit 1
fi
if ! snapshot_served=$(printf '%s' "$snapshot_apis" | python3 -c '
import re, sys
resources = sys.stdin.read().split()
if any(not re.fullmatch(r"[a-z][a-z0-9]*\.snapshot\.storage\.k8s\.io", name) for name in resources):
    sys.stderr.write("could not parse snapshot API discovery - cleanup unverified\n")
    sys.exit(1)
if resources and "volumesnapshotcontents.snapshot.storage.k8s.io" not in resources:
    sys.stderr.write("snapshot content API is unavailable - cleanup unverified\n")
    sys.exit(1)
print("yes" if resources else "no")
'); then
  exit 1
fi
if [ "$snapshot_served" = yes ]; then
  snapshot_deadline=$((SECONDS + pv_wait))
  while true; do
    if ! snapshot_json=$(oc "${context_args[@]}" get volumesnapshotcontents.snapshot.storage.k8s.io -o json); then
      echo "could not inspect VolumeSnapshotContents - cleanup unverified" >&2
      exit 1
    fi
    if ! snapshot_claims=$(printf '%s' "$snapshot_json" | python3 -c '
import json, sys
ns = sys.argv[1]
try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("expected an items list")
    for item in data["items"]:
        if not isinstance(item, dict):
            raise ValueError("invalid snapshot content")
        spec = item.get("spec")
        metadata = item.get("metadata")
        if not isinstance(spec, dict) or not isinstance(metadata, dict):
            raise ValueError("invalid snapshot content spec or metadata")
        ref = spec.get("volumeSnapshotRef")
        if not isinstance(ref, dict) or not isinstance(ref.get("namespace"), str):
            raise ValueError("invalid snapshot namespace reference")
        name = metadata.get("name")
        policy = spec.get("deletionPolicy")
        if not isinstance(name, str) or not name or policy not in ("Delete", "Retain"):
            raise ValueError("invalid snapshot content name or deletion policy")
        if ref["namespace"] == ns:
            print(name + "\t" + policy)
except (ValueError, TypeError):
    sys.stderr.write("could not parse VolumeSnapshotContent list - cleanup unverified\n")
    sys.exit(1)
' "$namespace"); then
      echo "could not inspect VolumeSnapshotContents - cleanup unverified" >&2
      exit 1
    fi
    if [ -z "$snapshot_claims" ]; then
      break
    fi
    snapshot_remaining=$((snapshot_deadline - SECONDS))
    if [ "$snapshot_remaining" -le 0 ]; then
      snapshot_names=$(printf '%s\n' "$snapshot_claims" | cut -f1)
      printf 'leftover VolumeSnapshotContents still reference %s:\n%s\n' "$namespace" "$snapshot_names" >&2
      snapshot_retained=$(printf '%s\n' "$snapshot_claims" | awk -F '\t' '$2 == "Retain" { print $1 }')
      if [ -n "$snapshot_retained" ]; then
        printf 'deletionPolicy is Retain for:\n%s\n' "$snapshot_retained" >&2
      fi
      exit 1
    fi
    if [ "$snapshot_remaining" -lt "$pv_interval" ]; then
      sleep "$snapshot_remaining"
    else
      sleep "$pv_interval"
    fi
  done
fi

echo "deleted smoke namespace ${namespace}"
