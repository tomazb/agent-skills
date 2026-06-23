#!/usr/bin/env bash
set -euo pipefail

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
oc get clusterrole,clusterrolebinding | grep -i rook-ceph || echo "  rook-ceph RBAC: absent (OK)"

echo ""
echo "PriorityClass:"
oc get priorityclass rook-ceph-default 2>/dev/null || echo "  rook-ceph-default priorityclass: absent (OK)"

echo ""
echo "CSIDrivers:"
oc get csidriver | grep rook-ceph || echo "  rook-ceph CSIDrivers: absent (OK)"

echo ""
echo "Default StorageClass:"
oc get sc -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}'
echo ""

echo ""
echo "Audit complete."
