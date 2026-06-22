# Journal: 2026-06-22 Longhorn Deprovision Lessons

This note records observations from deprovisioning Longhorn v1.12.0 on the
single-node OpenShift cluster `htz2.all-it.tech`. It is intentionally a journal
entry, not an authoritative runbook. Use it as input for a later skill update.

## Context

- Cluster: OpenShift 4.22.1 SNO.
- Longhorn install shape: OKD manifest install, not Helm.
- Longhorn version: v1.12.0.
- Longhorn mode at start: V2 Data Engine enabled, one smoke-test PVC.
- User-confirmed destructive scope: delete `longhorn-v2-smoke` data, uninstall
  Longhorn, and make `lvms-vg1` the default StorageClass.

## What The Skill Covered Well

- Required read-only discovery before destructive actions.
- Required explicit destructive confirmation before deleting the smoke PVC and
  uninstalling Longhorn.
- Correctly routed uninstall work to the same install method: OKD manifest plus
  Longhorn uninstall job.
- Required the documented `deleting-confirmation-flag` before uninstall.
- Kept host cleanup separate from Longhorn app uninstall because MachineConfig
  cleanup can reboot a single-node cluster.

## Missing Or Weak Guidance

- Add an uninstall StorageClass handoff step:
  - unset Longhorn as default;
  - set the replacement class as default;
  - verify exactly one default StorageClass before deleting Longhorn.
- Add an explicit post-uninstall audit checklist:
  - `longhorn-system` namespace absent;
  - no `longhorn.io` API resources/CRDs;
  - no Longhorn validating or mutating webhooks;
  - no `driver.longhorn.io` CSI driver;
  - no Longhorn RBAC or `longhorn-critical` priority class;
  - no Longhorn StorageClasses;
  - no PV/PVC uses `driver.longhorn.io`;
  - expected replacement StorageClass remains default.
- Call out leftover `driver.longhorn.io` StorageClasses. In this run,
  `longhorn-static` survived the manifest delete and needed separate removal
  after confirming no PV/PVC used it.
- Document that `oc delete -f longhorn-okd.yaml` may return `NotFound` for
  DaemonSets or Deployments already removed by the uninstall job. This can be
  acceptable when final validation is clean.
- Add a smoke namespace cleanup pattern:
  - delete the smoke namespace/PVC;
  - wait for namespace deletion;
  - verify Longhorn volume, replica, and engine CRs are gone before uninstall.
- Expand host cleanup guidance with examples for Longhorn MachineConfigs such
  as `80-longhorn-prereqs-*` and `81-longhorn-v2-spdk-*`. Keep the existing
  separate reboot safety gate.

## Operational Friction

- Several `oc` calls failed inside the sandbox with transient DNS lookup errors
  for `api.ocp1.htz2.all-it.tech` or `raw.githubusercontent.com`.
- The practical recovery was to rerun the same confirmed action outside the
  sandbox after the failure, with the same command and a narrow approval scope.

## Candidate Skill Update Shape

- Update `references/maintenance-uninstall.md` with a concise uninstall
  sequence that includes StorageClass handoff, workload/PVC deletion, uninstall
  job, OKD manifest cleanup, optional leftover StorageClass cleanup, and final
  audit.
- Update `references/validation-hardening.md` with a post-uninstall validation
  subsection.
- Add a host-cleanup subsection for identifying Longhorn MachineConfigs and
  explaining why their deletion is a separate operation on SNO.
