#!/usr/bin/env bash
set -euo pipefail

echo "Post-uninstall audit for OpenShift Data Foundation (ODF)..."

echo "Namespace:"
oc get namespace openshift-storage 2>/dev/null || echo "  openshift-storage namespace: absent (OK)"

echo ""
echo "ODF/Ceph CRDs in use:"
oc api-resources --api-group=ocs.openshift.io 2>/dev/null || echo "  ocs.openshift.io API resources: absent (OK)"
oc api-resources --api-group=ceph.rook.io 2>/dev/null || echo "  ceph.rook.io API resources: absent (OK)"

echo ""
echo "StorageClasses:"
oc get sc | grep -E 'openshift-storage|ocs-storagecluster' || echo "  ODF StorageClasses: absent (OK)"

echo ""
echo "PVs/PVCs:"
oc get pv,pvc -A -o wide | grep -E 'openshift-storage|ocs-storagecluster' || echo "  ODF PV/PVC: absent (OK)"

echo ""
echo "CSIDrivers:"
oc get csidriver | grep openshift-storage || echo "  ODF CSIDrivers: absent (OK)"

echo ""
echo "SecurityContextConstraints:"
oc get scc | grep -E 'rook-ceph|noobaa' || echo "  ODF SCCs: absent (OK)"

echo ""
echo "Default StorageClass:"
oc get sc -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}'
echo ""

echo ""
echo "Audit complete."
