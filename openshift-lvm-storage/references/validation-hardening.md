# Validation Hardening And Troubleshooting

Use this runbook after install, upgrade, reboot, maintenance, or incident response.

## Core Validation

```bash
oc get nodes -o wide
oc get mcp -o wide
oc get sc
oc -n openshift-storage get pods -o wide
oc -n openshift-storage get lvmcluster -o wide
oc -n openshift-storage get logicalvolumes.topolvm.io -o wide
oc get csidriver
```

Confirm exactly one default StorageClass when defaulting is expected.

## Node-Level LVM Validation

```bash
NODE="<node>"
oc debug "node/${NODE}" -- chroot /host bash -c "
  pvs
  vgs
  lvs
  lvs -o lv_name,vg_name,pool_lv,origin,size,data_percent,metadata_percent
"
```

Check that:
- VGs exist with expected names.
- Thin pools are within capacity (`data_percent` < 80, `metadata_percent` < 80).
- Physical volumes are the expected disks.

## Smoke Test

Create a namespace, PVC, and writer pod using the intended StorageClass. Validate:

- PVC is `Bound`.
- Pod reaches `Ready`.
- Write/read succeeds.
- TopoLVM volume is healthy (`LogicalVolume` CR status).
- `volumeBindingMode: WaitForFirstConsumer` is respected (pod scheduled before PV bound).
- `oc get sc` shows exactly one default StorageClass.

Use unique smoke namespaces per mode, for example `lvms-fs-smoke` and `lvms-block-smoke`, so cleanup and audit commands are unambiguous.

Minimum smoke flow for filesystem:

```bash
python3 scripts/render_smoke_manifest.py \
  --mode fs \
  --namespace lvms-fs-smoke \
  --storage-class lvms-vg1 \
  --output /tmp/lvms-fs-smoke.yaml

oc apply -f /tmp/lvms-fs-smoke.yaml
oc -n lvms-fs-smoke wait pod/lvms-smoke-writer --for=condition=Ready --timeout=5m
oc -n lvms-fs-smoke exec lvms-smoke-writer -- sh -c 'echo ok > /data/probe && cat /data/probe'
oc -n openshift-storage get logicalvolumes.topolvm.io -o wide
```

Minimum smoke flow for block:

```bash
python3 scripts/render_smoke_manifest.py \
  --mode block \
  --namespace lvms-block-smoke \
  --storage-class lvms-vg1-block \
  --output /tmp/lvms-block-smoke.yaml

oc apply -f /tmp/lvms-block-smoke.yaml
oc -n lvms-block-smoke wait pod/lvms-smoke-writer --for=condition=Ready --timeout=5m
oc -n lvms-block-smoke exec lvms-smoke-writer -- sh -c 'test -b /dev/block-device && echo "block device present"'
oc -n openshift-storage get logicalvolumes.topolvm.io -o wide
```

If the helper is unavailable, adapt `assets/smoke-pvc-writer.yaml` and replace every placeholder before applying it.

On OpenShift, make smoke pods compatible with restricted PodSecurity by setting `allowPrivilegeEscalation: false`, dropping all capabilities, setting `runAsNonRoot: true` when the image supports it, and setting `seccompProfile.type: RuntimeDefault`.

## Post-Reboot Drift

After a node reboot, check:

- `LVMCluster` is `Ready`.
- TopoLVM CSI node pods are running on all nodes.
- VGs and thin pools exist (`vgs`, `lvs`).
- Thin pool capacity is within bounds.
- `LogicalVolume` CRs are `Healthy`.
- One default StorageClass remains.
- MachineConfigs have been applied and MCP is `Updated`.
- `topolvm.io/capacity` extended resource is reported on each node.

## Post-Uninstall Validation

After uninstall, confirm:

- `openshift-storage` namespace is absent (or empty if reused).
- `oc api-resources --api-group=topolvm.io` and `oc api-resources --api-group=lvm.topolvm.io` return no resources.
- `csidriver/topolvm.io` is absent.
- No StorageClass uses `provisioner: topolvm.io`.
- No PV/PVC uses a TopoLVM StorageClass.
- TopoLVM SCCs are absent.
- Exactly one intended default StorageClass remains.

## Hardening

- Configure application-level backup (Velero/OADP) for workloads using LVMS volumes.
- Integrate TopoLVM metrics with OpenShift monitoring.
- Alert on:
  - Thin pool capacity pressure (`data_percent`, `metadata_percent`).
  - Node failures affecting LVMS volumes.
  - `LogicalVolume` CRs not in `Healthy` state.
  - CSI driver pod failures or restarts.
  - VG capacity exhaustion (`topolvm.io/capacity` near zero).
- For multi-node production, spread workloads across nodes to avoid single-node bottleneck.
- For SNO, document that all storage is local and not redundant.
- Avoid thin pool over-provisioning ratios that exceed realistic usage patterns.

## Troubleshooting Shape

For incidents, answer with:

- Symptom and impact.
- Current health evidence (`LVMCluster`, `LogicalVolume`, `lvs`, `vgs`, pods).
- Likely layer: Kubernetes scheduling, TopoLVM CSI, LVM, node hardware, network, or OpenShift host/MachineConfig.
- Commands already run.
- Next read-only checks.
- Safest remediation and stop conditions.

Collect support data when needed:

```bash
oc -n openshift-storage get events --sort-by=.lastTimestamp
# Workload names vary by LVMS version. Discover them first, then tail logs by the observed names:
oc -n openshift-storage get deployment,daemonset -o wide
oc -n openshift-storage logs deployment/<controller-deployment> --tail=200
oc -n openshift-storage logs daemonset/<node-daemonset> --tail=200
oc -n openshift-storage get logicalvolumes.topolvm.io -o yaml
oc get node <node> -o yaml | grep -A 20 "topolvm.io/capacity"
```
