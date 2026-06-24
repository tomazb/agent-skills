#!/usr/bin/env bash
set -euo pipefail

# Read-only post-uninstall audit for LVMS / TopoLVM on OpenShift/OKD.
# This script checks for leftover resources after an LVMS uninstall.

echo "=== LVMS Post-Uninstall Audit ==="

LVM_RESOURCES=$(oc api-resources --api-group=topolvm.io --verbs=list -o name 2>/dev/null || true)
if [ -n "$LVM_RESOURCES" ]; then
  echo "WARN: topolvm.io API resources still exist:"
  echo "$LVM_RESOURCES"
else
  echo "OK: no topolvm.io API resources found"
fi

echo
if oc get csidriver topolvm.io &>/dev/null; then
  echo "WARN: csidriver/topolvm.io still exists"
else
  echo "OK: csidriver/topolvm.io absent"
fi

echo
SCS=$(oc get sc -o json | jq -r '.items[] | select(.provisioner == "topolvm.io") | .metadata.name' 2>/dev/null || true)
if [ -n "$SCS" ]; then
  echo "WARN: TopoLVM StorageClasses still exist:"
  echo "$SCS"
else
  echo "OK: no TopoLVM StorageClasses found"
fi

echo
PVS=$(oc get pv -o json | jq -r '.items[] | select(.spec.csi // {} | .driver == "topolvm.io") | .metadata.name' 2>/dev/null || true)
if [ -n "$PVS" ]; then
  echo "WARN: TopoLVM PVs still exist:"
  echo "$PVS"
else
  echo "OK: no TopoLVM PVs found"
fi

echo
PVCS=$(oc get pvc -A -o json | jq -r '.items[] | select((.spec.storageClassName // "") | contains("lvms") or contains("topolvm")) | .metadata.namespace + "/" + .metadata.name' 2>/dev/null || true)
if [ -n "$PVCS" ]; then
  echo "WARN: LVMS PVCs still exist:"
  echo "$PVCS"
else
  echo "OK: no LVMS PVCs found"
fi

echo
SCCS=$(oc get scc -o json | jq -r '.items[] | select(.metadata.name | contains("topolvm") or contains("lvms")) | .metadata.name' 2>/dev/null || true)
if [ -n "$SCCS" ]; then
  echo "WARN: TopoLVM/LVMS SCCs still exist:"
  echo "$SCCS"
else
  echo "OK: no TopoLVM/LVMS SCCs found"
fi

echo
if oc get namespace openshift-storage &>/dev/null; then
  echo "WARN: openshift-storage namespace still exists"
  oc -n openshift-storage get all 2>/dev/null || true
else
  echo "OK: openshift-storage namespace absent"
fi

echo
CSVS=$(oc get csv -A -o json | jq -r '.items[] | select(.metadata.name | contains("lvms")) | .metadata.namespace + "/" + .metadata.name' 2>/dev/null || true)
if [ -n "$CSVS" ]; then
  echo "WARN: LVMS CSVs still exist:"
  echo "$CSVS"
else
  echo "OK: no LVMS CSVs found"
fi

echo
SUBS=$(oc get subscription -A -o json | jq -r '.items[] | select(.metadata.name | contains("lvms")) | .metadata.namespace + "/" + .metadata.name' 2>/dev/null || true)
if [ -n "$SUBS" ]; then
  echo "WARN: LVMS Subscriptions still exist:"
  echo "$SUBS"
else
  echo "OK: no LVMS Subscriptions found"
fi

echo
DEFAULT_SCS=$(oc get sc -o json | jq -r '.items[] | select(.metadata.annotations."storageclass.kubernetes.io/is-default-class" == "true") | .metadata.name' 2>/dev/null || true)
COUNT=$(echo "$DEFAULT_SCS" | grep -c . || true)
if [ "$COUNT" -eq 1 ]; then
  echo "OK: exactly one default StorageClass: $DEFAULT_SCS"
elif [ "$COUNT" -eq 0 ]; then
  echo "WARN: no default StorageClass found"
else
  echo "WARN: multiple default StorageClasses found:"
  echo "$DEFAULT_SCS"
fi

echo "=== Audit Complete ==="
