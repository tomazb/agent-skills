#!/usr/bin/env bash
set -euo pipefail

FAILED=0

warn() {
  echo "WARN: $*"
  FAILED=1
}

ns_exists() {
  oc get namespace "$1" >/dev/null 2>&1
}

echo "Post-uninstall audit for Rook Ceph..."

echo "Namespace:"
oc get namespace rook-ceph 2>/dev/null || echo "  rook-ceph namespace: absent (OK)"

echo ""
echo "Ceph CRDs:"
oc api-resources --api-group=ceph.rook.io 2>/dev/null || echo "  ceph.rook.io API resources: absent (OK)"

echo ""
echo "StorageClasses:"
oc get sc | grep rook-ceph || echo "  rook-ceph StorageClasses: absent (OK)"

echo ""
echo "PVs/PVCs:"
oc get pv,pvc -A -o wide | grep rook-ceph || echo "  rook-ceph PV/PVC: absent (OK)"

echo ""
echo "ClusterRoles/ClusterRoleBindings:"
# rook-ceph-metrics is bound to openshift-monitoring/prometheus-k8s, which exists
# on every OpenShift cluster. That binding is still in use while rook-ceph or
# openshift-storage remains. Once both namespaces are gone it is residue.
rbac=$(oc get clusterrole,clusterrolebinding 2>/dev/null | grep -i rook-ceph || true)
if [ -n "$rbac" ]; then
  if ns_exists rook-ceph || ns_exists openshift-storage; then
    echo "  OK: rook-ceph RBAC retained: a Ceph operator namespace is still present"
    printf '%s\n' "$rbac"
  else
    warn "rook-ceph RBAC still exists after both Rook and ODF are gone:"
    printf '%s\n' "$rbac"
  fi
else
  echo "  rook-ceph RBAC: absent (OK)"
fi

echo ""
echo "PriorityClass:"
oc get priorityclass rook-ceph-default 2>/dev/null || echo "  rook-ceph-default priorityclass: absent (OK)"

echo ""
echo "CSIDrivers:"
oc get csidriver | grep rook-ceph || echo "  rook-ceph CSIDrivers: absent (OK)"

echo ""
echo "Default StorageClass:"
# PRIOR_DEFAULT_STORAGE_CLASS is recorded before uninstall. Unset keeps the
# historical printout. An empty value means the cluster had no default.
default_text=$(oc get sc -o jsonpath='{range .items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
found=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  found="${found:+$found,}$line"
done <<<"$default_text"
if [ -z "${PRIOR_DEFAULT_STORAGE_CLASS+x}" ]; then
  printf '%s\n' "$default_text"
elif [ -z "$PRIOR_DEFAULT_STORAGE_CLASS" ]; then
  if [ -z "$found" ]; then
    echo "  OK: no default StorageClass, matching the pre-install policy"
  else
    warn "default StorageClass is '$found', pre-install policy had none"
  fi
elif [ "$found" = "$PRIOR_DEFAULT_STORAGE_CLASS" ]; then
  echo "  OK: default StorageClass still $found"
else
  warn "default StorageClass is '${found:-none}', pre-install policy was $PRIOR_DEFAULT_STORAGE_CLASS"
fi
echo ""

echo ""
echo "Audit complete."
exit "$FAILED"
