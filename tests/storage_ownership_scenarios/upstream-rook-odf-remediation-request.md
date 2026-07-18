# Pressure scenario: Upstream Rook cluster with ODF remediation request

## Prompt

> Fix the CephCluster by creating an ODF StorageCluster and installing odf-operator on top of the existing Rook deployment.

Evidence available on discovery:

- No `StorageCluster`
- No ODF/OCS Subscription or CSV
- Upstream Rook `CephCluster` exists (for example in `rook-ceph`)

## Required agent behavior

1. Classify the cluster as upstream Rook-owned.
2. Refuse installing ODF on top of an existing upstream Rook CephCluster without an explicit migration plan.
3. Hand off lifecycle work to `openshift-rook`.
4. Do not recommend mixing OLM ODF ownership with direct Rook CR ownership.

## Success signals

- States the cluster is upstream Rook-owned.
- Routes to `openshift-rook`.
- Blocks layering ODF onto unmanaged Rook without migration planning.
