#!/usr/bin/env bash
set -euo pipefail

# Read-only post-uninstall audit for OpenShift Data Foundation (ODF).
# A warning marks the audit as failed: any ODF residue needs an operator decision.

FAILED=0
QUERY_RESULT=""
QUERY_NOT_FOUND=0
OC_GLOBAL_ARGS=()
# Reported in the banner. `oc config current-context` keeps printing the
# kubeconfig's current context even when --context overrides the request target,
# so it cannot be trusted to name the cluster actually being audited.
OC_CONTEXT_LABEL=""

# printf, not `cat <<EOF`: usage must still work when PATH holds nothing but oc
# and jq, which is how this script is invoked in constrained environments.
usage() {
  printf '%s\n' \
    'Usage: post_uninstall_audit.sh [--context NAME] [--kubeconfig PATH]' \
    '' \
    'Read-only audit for ODF residue after an uninstall.' \
    '' \
    '  --context NAME       kubeconfig context to audit (default: the current one)' \
    '  --kubeconfig PATH    kubeconfig file to use' \
    '  -h, --help           show this help' \
    '' \
    'Unknown arguments are rejected. This script previously ignored them' \
    'silently, so a "--context other-cluster" that looked accepted actually' \
    'audited whichever context was current, and reported the result as if it' \
    'were the requested one.'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --context)
      [ "$#" -ge 2 ] || { echo "--context requires a value" >&2; exit 2; }
      OC_GLOBAL_ARGS+=("--context=$2"); OC_CONTEXT_LABEL="$2"; shift 2 ;;
    --context=*)
      OC_CONTEXT_LABEL="${1#*=}"
      # An empty suffix would otherwise reach oc as `--context=`, which silently
      # means "no override" rather than failing the way a missing value does.
      [ -n "$OC_CONTEXT_LABEL" ] || { echo "--context requires a value" >&2; exit 2; }
      OC_GLOBAL_ARGS+=("--context=$OC_CONTEXT_LABEL"); shift ;;
    --kubeconfig)
      [ "$#" -ge 2 ] || { echo "--kubeconfig requires a value" >&2; exit 2; }
      OC_GLOBAL_ARGS+=("--kubeconfig=$2"); shift 2 ;;
    --kubeconfig=*)
      kubeconfig_value="${1#*=}"
      [ -n "$kubeconfig_value" ] || { echo "--kubeconfig requires a value" >&2; exit 2; }
      OC_GLOBAL_ARGS+=("--kubeconfig=$kubeconfig_value"); shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2 ;;
  esac
done

fail() {
  echo "FAIL: $*"
  FAILED=1
}

warn() {
  echo "WARN: $*"
  FAILED=1
}

ok() {
  echo "OK: $*"
}

is_not_found() {
  case "$1" in
    *NotFound*|*not\ found*|*the\ server\ doesn\'t\ have\ a\ resource\ type*) return 0 ;;
    *) return 1 ;;
  esac
}

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    fail "$cmd CLI is required but not installed"
    return 1
  fi
}

check_api_group() {
  local group="$1"
  local resources

  if ! resources=$(oc api-resources --api-group="$group" --verbs=list -o name 2>&1); then
    fail "$group API resource discovery failed: $resources"
    return
  fi

  if [ -n "$resources" ]; then
    warn "$group API resources still exist:"
    echo "$resources"
  else
    ok "no $group API resources found"
  fi
}

check_absent_resource() {
  local label="$1"
  local ok_message="$2"
  shift 2

  local output
  if output=$(oc get "$@" 2>&1); then
    warn "$label still exists"
    [ -n "$output" ] && echo "$output"
  elif is_not_found "$output"; then
    ok "$ok_message"
  else
    fail "$label lookup failed: $output"
  fi

  return 0
}

query_json() {
  local label="$1"
  local jq_filter="$2"
  shift 2

  local json
  local output
  QUERY_RESULT=""
  QUERY_NOT_FOUND=0

  if ! json=$("$@" -o json 2>&1); then
    if is_not_found "$json"; then
      QUERY_NOT_FOUND=1
      return 0
    fi
    fail "$label query failed: $json"
    return 1
  fi

  if ! output=$(jq -r "$jq_filter" <<<"$json" 2>&1); then
    fail "$label jq filter failed: $output"
    return 1
  fi

  QUERY_RESULT="$output"
}

check_json_list() {
  local label="$1"
  local ok_message="$2"
  local jq_filter="$3"
  shift 3

  if query_json "$label" "$jq_filter" "$@"; then
    if [ "$QUERY_NOT_FOUND" -eq 1 ] || [ -z "$QUERY_RESULT" ]; then
      ok "$ok_message"
    else
      warn "$label still exist:"
      echo "$QUERY_RESULT"
    fi
  fi
}

count_nonempty_lines() {
  local value="$1"
  local count=0
  local line

  while IFS= read -r line; do
    if [ -n "$line" ]; then
      count=$((count + 1))
    fi
  done <<<"$value"

  echo "$count"
}

# ODF component OLM packages, as one alternation. Every package match below derives
# from it, so a package added here is recognised in subscriptions, CSVs, and labels.
ODF_PACKAGES='odf-operator|odf-dependencies|ocs-operator|ocs-client-operator|rook-ceph-operator|cephcsi-operator|mcg-operator|odf-csi-addons-operator|odf-external-snapshotter-operator|odf-prometheus-operator|ocs-tls-profiles|recipe'
# Anything else in openshift-storage marks the namespace as shared.
ODF_PACKAGES_RE="^($ODF_PACKAGES)\$"
# CSV names are "<package>.v<version>", so match the same packages by prefix.
# The literal dot is written [.] rather than \. : these strings are interpolated into
# jq string literals, where \. is an invalid escape and aborts the filter.
ODF_CSV_PREFIX_RE="^($ODF_PACKAGES)[.]"
# OLM labels what it installs "operators.coreos.com/<package>.<namespace>".
ODF_PACKAGE_LABEL_RE="^operators[.]coreos[.]com/($ODF_PACKAGES)[.]"
# Object names ODF creates in openshift-storage.
ODF_NAME_RE='rook|ceph|noobaa|ocs-|odf'
ODF_CSI_DRIVER_RE='^openshift-storage[.](rbd|cephfs)[.]csi[.]ceph[.]com$'
ODF_BUCKET_PROVISIONER_RE='^openshift-storage[.](noobaa[.]io/obc|ceph[.]rook[.]io/bucket)$'

# Namespaces holding an upstream (non-OLM) Rook CephCluster, one per line, and the
# same list as a JSON array for jq filters. Empty when there is none.
ROOK_NAMESPACES=""
ROOK_NAMESPACES_JSON="[]"

# Comma-joined resources the API serves, set by find_served_resources.
SERVED_RESOURCES=""

join_lines() {
  local value="$1"
  local joined=""
  local line

  while IFS= read -r line; do
    if [ -n "$line" ]; then
      joined="${joined:+$joined,}$line"
    fi
  done <<<"$value"

  printf '%s' "$joined"
}

# Set SERVED_RESOURCES to those of the named resources that $group serves, so an
# optional CRD can join a combined `oc get` without failing the whole query.
find_served_resources() {
  local group="$1"
  shift

  local available
  local wanted
  local line
  SERVED_RESOURCES=""

  if ! available=$(oc api-resources --api-group="$group" --verbs=list -o name 2>&1); then
    fail "$group API resource discovery failed: $available"
    return 1
  fi

  for wanted in "$@"; do
    while IFS= read -r line; do
      if [ "$line" = "$wanted" ]; then
        SERVED_RESOURCES="${SERVED_RESOURCES:+$SERVED_RESOURCES,}$wanted"
      fi
    done <<<"$available"
  done
}

# Fetch an oc list reduced by $jq_filter (which must produce an array) into
# QUERY_RESULT. An absent kind reads as an empty array.
fetch_array() {
  local label="$1"
  local jq_filter="$2"
  shift 2

  query_json "$label" "$jq_filter" "$@" || return 1
  if [ "$QUERY_NOT_FOUND" -eq 1 ] || [ -z "$QUERY_RESULT" ]; then
    QUERY_RESULT="[]"
  fi
}

# Like check_json_list, but the filter runs over several JSON documents slurped
# into one array (.[0], .[1], ...). They go through stdin because cluster-wide
# lists exceed the per-argument size limit that --argjson would hit.
check_docs_list() {
  local label="$1"
  local ok_message="$2"
  local jq_filter="$3"
  shift 3

  local output
  if ! output=$(printf '%s\n' "$@" | jq -r -s "$jq_filter" 2>&1); then
    fail "$label jq filter failed: $output"
    return 0
  fi

  if [ -z "$output" ]; then
    ok "$ok_message"
  else
    warn "$label still exist:"
    echo "$output"
  fi
}

# LVMS and LSO install into openshift-storage by default. A kept namespace is only
# acceptable when a non-ODF operator still lives there; then it must hold no ODF residue.
check_storage_namespace() {
  local output
  if ! output=$(oc get namespace openshift-storage 2>&1); then
    if is_not_found "$output"; then
      ok "openshift-storage namespace absent"
    else
      fail "openshift-storage namespace lookup failed: $output"
    fi
    return 0
  fi

  if ! query_json \
    "openshift-storage subscriptions" \
    ".items[].spec.name | select(test(\"$ODF_PACKAGES_RE\") | not)" \
    oc get subscription -n openshift-storage; then
    return 0
  fi

  local non_odf="$QUERY_RESULT"
  if [ -z "$non_odf" ]; then
    warn "openshift-storage namespace still exists"
    return 0
  fi

  ok "openshift-storage namespace kept for non-ODF operators: ${non_odf//$'\n'/ }"

  # A kept namespace does not excuse a surviving ODF subscription: OLM would
  # re-create its CSV and workloads, so the namespace looks clean only until the
  # next reconcile.
  check_json_list \
    "ODF subscriptions still in openshift-storage" \
    "no ODF subscriptions left in openshift-storage" \
    ".items[].spec.name | select(test(\"$ODF_PACKAGES_RE\"))" \
    oc get subscription -n openshift-storage

  check_json_list \
    "ODF CSVs still in openshift-storage" \
    "no ODF CSVs left in openshift-storage" \
    ".items[].metadata.name | select(test(\"$ODF_CSV_PREFIX_RE\"))" \
    oc get csv -n openshift-storage

  # The ODF install also leaves RBAC, a mon PDB, and PrometheusRules here, all
  # unowned, so removing the operators never collects them.
  local kinds='secrets,configmaps,services,deployments,daemonsets,statefulsets,serviceaccounts,roles,rolebindings,poddisruptionbudgets,jobs,cronjobs'
  find_served_resources monitoring.coreos.com \
    servicemonitors.monitoring.coreos.com prometheusrules.monitoring.coreos.com || return 0
  if [ -n "$SERVED_RESOURCES" ]; then
    kinds="$kinds,$SERVED_RESOURCES"
  fi

  check_json_list \
    "ODF residue objects in openshift-storage" \
    "no ODF residue objects in openshift-storage" \
    ".items[] | select(.metadata.name | test(\"$ODF_NAME_RE\"; \"i\")) | (.kind // \"object\") + \"/\" + .metadata.name" \
    oc get "$kinds" -n openshift-storage
}

# A Pod whose CSI driver was removed first can never be unmounted, so the kubelet
# keeps it (and, through pvc-protection, its PVC) with deletionTimestamp set forever.
check_storage_namespace_pods() {
  check_json_list \
    "ODF pods in openshift-storage" \
    "no ODF pods in openshift-storage" \
    ".items[] | select(.metadata.name | test(\"$ODF_NAME_RE\"; \"i\")) | .metadata.name + \" (\" + (.status.phase // \"unknown\") + \")\"" \
    oc get pods -n openshift-storage

  check_json_list \
    "Terminating pods in openshift-storage" \
    "no Terminating pods in openshift-storage" \
    '.items[] | select(.metadata.deletionTimestamp != null) | .metadata.name + " (" + (.status.phase // "unknown") + ", deleting since " + .metadata.deletionTimestamp + ")"' \
    oc get pods -n openshift-storage
}

lso_retained() {
  if query_json \
    "LSO subscriptions" \
    '.items[] | select(.spec.name == "local-storage-operator") | .metadata.name' \
    oc get subscription -A; then
    [ -n "$QUERY_RESULT" ] && return 0
  fi
  return 1
}

# An upstream Rook CephCluster is one not owned by a StorageCluster. One left in
# openshift-storage without that owner is ODF's own, orphaned by an interrupted
# uninstall, so that namespace never counts.
detect_upstream_rook() {
  local ns

  query_json \
    "CephClusters" \
    '[.items[] | select(.metadata.namespace != "openshift-storage") | select(any(.metadata.ownerReferences[]?; .kind == "StorageCluster") | not) | .metadata.namespace] | unique | .[]' \
    oc get cephclusters.ceph.rook.io -A || return 0
  ROOK_NAMESPACES="$QUERY_RESULT"

  # Namespace names are DNS labels, so quoting them is enough to make JSON.
  ROOK_NAMESPACES_JSON=""
  while IFS= read -r ns; do
    if [ -n "$ns" ]; then
      ROOK_NAMESPACES_JSON="${ROOK_NAMESPACES_JSON:+$ROOK_NAMESPACES_JSON,}\"$ns\""
    fi
  done <<<"$ROOK_NAMESPACES"
  ROOK_NAMESPACES_JSON="[$ROOK_NAMESPACES_JSON]"
}

upstream_rook_present() {
  [ -n "$ROOK_NAMESPACES" ]
}

is_rook_namespace() {
  local wanted="$1"
  local ns

  while IFS= read -r ns; do
    if [ -n "$ns" ] && [ "$ns" = "$wanted" ]; then
      return 0
    fi
  done <<<"$ROOK_NAMESPACES"
  return 1
}

check_rook_namespaces() {
  local ns

  while IFS= read -r ns; do
    if [ -n "$ns" ]; then
      ok "namespace $ns retained: an upstream Rook CephCluster runs there"
    fi
  done <<<"$ROOK_NAMESPACES"

  if ! is_rook_namespace rook-ceph; then
    check_absent_resource \
      "rook-ceph namespace" \
      "rook-ceph namespace absent" \
      namespace rook-ceph
  fi
}

# ceph.rook.io, csi.ceph.io and objectbucket.io are shared with upstream Rook. While
# a Rook cluster runs its CRDs stay; only instances inside openshift-storage are ODF's.
check_rook_shared_group() {
  local group="$1"

  if ! upstream_rook_present; then
    check_api_group "$group"
    return 0
  fi

  ok "$group API resources retained for upstream Rook in: ${ROOK_NAMESPACES//$'\n'/ }"

  local kinds
  if ! kinds=$(oc api-resources --api-group="$group" --namespaced=true --verbs=list -o name 2>&1); then
    fail "$group API resource discovery failed: $kinds"
    return 0
  fi
  if [ -z "$kinds" ]; then
    ok "no $group objects in openshift-storage"
    return 0
  fi

  check_json_list \
    "$group objects in openshift-storage" \
    "no $group objects in openshift-storage" \
    '.items[] | (.kind // "object") + "/" + .metadata.name' \
    oc get "$(join_lines "$kinds")" -n openshift-storage
}

# groupsnapshot.storage.openshift.io is residue only when it is provably ODF's and
# unused: every CRD in the group carries an ODF package OLM label and no
# release-payload annotation, no instance of any of its kinds exists, and the
# VolumeGroupSnapshot feature gate is not enabled. Anything else may be
# platform-owned or in use and is reported for review. Whether another snapshotter
# relies on the group cannot be read from the API; the runbook checks that by hand.
check_groupsnapshot_group() {
  local group="groupsnapshot.storage.openshift.io"
  local kinds
  local reason=""

  if ! kinds=$(oc api-resources --api-group="$group" --verbs=list -o name 2>&1); then
    fail "$group API resource discovery failed: $kinds"
    return 0
  fi
  if [ -z "$kinds" ]; then
    ok "no $group API resources found"
    return 0
  fi

  query_json \
    "$group CRDs" \
    "[.items[] | select(.spec.group == \"$group\")] | all(.[]; any(.metadata.labels // {} | keys[]; test(\"$ODF_PACKAGE_LABEL_RE\")) and (any(.metadata.annotations // {} | keys[]; test(\"release[.]openshift[.]io\")) | not))" \
    oc get crd || return 0
  if [ "$QUERY_RESULT" != "true" ]; then
    reason="its CRDs are not all ODF-labelled, or carry release-payload annotations"
  fi

  if [ -z "$reason" ]; then
    query_json "$group instances" '.items | length' oc get "$(join_lines "$kinds")" -A || return 0
    if [ "${QUERY_RESULT:-0}" != "0" ]; then
      reason="$QUERY_RESULT instances exist"
    fi
  fi

  if [ -z "$reason" ]; then
    query_json \
      "feature gates" \
      '.status.featureGates[]?.enabled[]?.name | select(. == "VolumeGroupSnapshot")' \
      oc get featuregate cluster || return 0
    if [ -n "$QUERY_RESULT" ]; then
      reason="the VolumeGroupSnapshot feature gate is enabled"
    fi
  fi

  if [ -n "$reason" ]; then
    ok "$group API resources retained: $reason; review before removing"
  else
    warn "$group API resources are ODF residue (ODF-labelled, no instances, feature gate off):"
    echo "$kinds"
  fi
}

# jq: true when the object (its storage class name in .sc) is an ODF bucket or has
# lost its class. $classes maps StorageClass name to provisioner.
ODF_BUCKET_JQ="def odf_bucket(\$classes): (\$classes[.sc // \"\"] // null) as \$p | \$p == null or (\$p | test(\"$ODF_BUCKET_PROVISIONER_RE\"));"

# Bucket claims and buckets are ODF's only when their class uses an ODF provisioner
# or is gone; a running upstream Rook serves its own through the same CRDs. The
# claim's ConfigMap and Secret carry objectbucket.io/finalizer too, and once the
# provisioner is gone they hold the consumer namespace in Terminating.
check_object_buckets() {
  local classes
  local claims
  local buckets
  local held

  fetch_array "StorageClasses" \
    '[[.items[] | {key: .metadata.name, value: .provisioner}] | from_entries]' \
    oc get sc || return 0
  classes="$QUERY_RESULT"
  fetch_array "ObjectBucketClaims" \
    '[.items[] | {ns: .metadata.namespace, name: .metadata.name, sc: .spec.storageClassName}]' \
    oc get obc -A || return 0
  claims="$QUERY_RESULT"
  fetch_array "ObjectBuckets" \
    '[.items[] | {name: .metadata.name, sc: .spec.storageClassName}]' \
    oc get objectbucket || return 0
  buckets="$QUERY_RESULT"
  fetch_array "objectbucket.io finalizer holders" \
    '[.items[] | select(any(.metadata.finalizers[]?; . == "objectbucket.io/finalizer")) | {kind: .kind, ns: .metadata.namespace, name: .metadata.name}]' \
    oc get configmaps,secrets -A || return 0
  held="$QUERY_RESULT"

  check_docs_list \
    "ODF ObjectBucketClaims" \
    "no ODF ObjectBucketClaims found" \
    "$ODF_BUCKET_JQ (.[0][0] // {}) as \$classes | .[1][] | select(odf_bucket(\$classes)) | \"\(.ns)/\(.name) (class \(.sc // \"none\"): \(\$classes[.sc // \"\"] // \"missing\"))\"" \
    "$classes" "$claims"

  echo
  check_docs_list \
    "ODF ObjectBuckets" \
    "no ODF ObjectBuckets found" \
    "$ODF_BUCKET_JQ (.[0][0] // {}) as \$classes | .[1][] | select(odf_bucket(\$classes)) | \"\(.name) (class \(.sc // \"none\"): \(\$classes[.sc // \"\"] // \"missing\"))\"" \
    "$classes" "$buckets"

  echo
  check_docs_list \
    "ConfigMaps and Secrets held by objectbucket.io/finalizer without a live claim" \
    "no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim" \
    "$ODF_BUCKET_JQ (.[0][0] // {}) as \$classes | [.[1][] | select(odf_bucket(\$classes) | not) | \"\(.ns)/\(.name)\"] as \$live | .[2][] | \"\(.ns)/\(.name)\" as \$key | select(any(\$live[]; . == \$key) | not) | \"\(.kind)/\(.ns)/\(.name)\"" \
    "$classes" "$claims" "$held"
}

# SCCs named for Rook, NooBaa, or ceph-csi. With upstream Rook running, an SCC whose
# every user is a service account of a Rook namespace (and whose groups, if any,
# are the service-account groups of those namespaces) belongs to that Rook.
check_sccs() {
  local rook_scc_jq="def rook_scc(\$rook): (\$rook | length) > 0 and ((.users // []) | length) > 0 and all((.users // [])[]; split(\":\") as \$p | ((\$p | length) == 4) and \$p[0] == \"system\" and \$p[1] == \"serviceaccount\" and any(\$rook[]; . == \$p[2])) and all((.groups // [])[]; split(\":\") as \$p | ((\$p | length) == 3) and \$p[0] == \"system\" and \$p[1] == \"serviceaccounts\" and any(\$rook[]; . == \$p[2]));"
  local name_jq='select((.metadata.name | contains("rook-ceph")) or (.metadata.name | contains("noobaa")) or (.metadata.name | contains("ceph-csi")))'
  local name

  if upstream_rook_present && query_json \
    "upstream Rook SCCs" \
    "$rook_scc_jq $ROOK_NAMESPACES_JSON as \$rook | .items[] | $name_jq | select(rook_scc(\$rook)) | .metadata.name" \
    oc get scc; then
    while IFS= read -r name; do
      if [ -n "$name" ]; then
        ok "SCC $name retained: every user is a service account in an upstream Rook namespace"
      fi
    done <<<"$QUERY_RESULT"
  fi

  check_json_list \
    "ODF SCCs" \
    "no ODF SCCs found" \
    "$rook_scc_jq $ROOK_NAMESPACES_JSON as \$rook | .items[] | $name_jq | select(rook_scc(\$rook) | not) | .metadata.name" \
    oc get scc
}

# Cluster RBAC from the ODF install: labelled by OLM for an ODF CSV or package, or
# one of the names ODF creates unlabelled. A stale label proves ODF created the
# object, not that nothing uses it, so each one is classified by liveness:
# - a ClusterRoleBinding is dead when its ClusterRole is missing, or when it has no
#   User/Group subject (those cannot be proven absent) and none of its
#   ServiceAccount subjects exists;
# - a ClusterRole is dead when no live ClusterRoleBinding or RoleBinding references
#   it (a dead binding does not keep its role alive) and no other ClusterRole's
#   aggregationRule selects it (matchLabels only).
# RoleBindings are judged by the same subject rule.
ODF_RBAC_JQ="
def odf_owned(\$names):
  ((.labels[\"olm.owner\"] // \"\") | test(\"$ODF_CSV_PREFIX_RE\"))
  or any(.labels | keys[]; test(\"$ODF_PACKAGE_LABEL_RE\"))
  or (.name as \$n | any(\$names[]; . == \$n));
def live_sas(\$sas):
  [.subjects[] | select(.kind == \"ServiceAccount\") | \"\(.namespace)/\(.name)\" | select(\$sas[.] // false)];
def verdict(\$roles; \$sas):
  if (\$roles[.role] // false) | not then {live: false, why: \"its ClusterRole \(.role) is missing\"}
  elif any(.subjects[]; .kind == \"User\" or .kind == \"Group\") then {live: true, why: \"has a User/Group subject, which cannot be proven absent\"}
  elif (live_sas(\$sas) | length) > 0 then {live: true, why: \"bound to live ServiceAccount \(live_sas(\$sas) | join(\", \"))\"}
  else {live: false, why: \"none of its ServiceAccount subjects exists\"} end;
.[0] as \$crs | .[1] as \$crbs | .[2] as \$rbs
| (.[3] | map({key: ., value: true}) | from_entries) as \$sas
| (\$crs | map({key: .name, value: true}) | from_entries) as \$roles
| ([\$crbs[] | . + {ref: \"ClusterRoleBinding/\(.name)\", odf: odf_owned([\"ocs-metrics-exporter\"])}]
   + [\$rbs[] | . + {ref: \"RoleBinding \(.ns)/\(.name)\", odf: false}]
   | map(. + verdict(\$roles; \$sas))) as \$bindings
| (\$bindings[] | select(.odf) | [(if .live then \"kept\" else \"dead\" end), .ref, .why] | @tsv),
  (\$crs[] | select(odf_owned([\"ocs-metrics-exporter\", \"ocs-metrics-reader\"])) | . as \$role
   | [\$bindings[] | select(.role == \$role.name)] as \$refs
   | [\$refs[] | select(.live) | .ref] as \$live_refs
   | any(\$crs[]; .name != \$role.name and any(.selectors[]; length > 0 and all(to_entries[]; \$role.labels[.key] == .value))) as \$aggregated
   | if (\$live_refs | length) > 0 then [\"kept\", \"ClusterRole/\(.name)\", \"referenced by live \(\$live_refs | join(\", \"))\"]
     elif \$aggregated then [\"kept\", \"ClusterRole/\(.name)\", \"aggregated into another ClusterRole\"]
     elif (\$refs | length) > 0 then [\"dead\", \"ClusterRole/\(.name)\", \"referenced only by dead \([\$refs[].ref] | join(\", \"))\"]
     else [\"dead\", \"ClusterRole/\(.name)\", \"no binding references it\"] end
   | @tsv)
"

check_cluster_rbac() {
  local roles
  local cluster_bindings
  local bindings
  local accounts
  local output
  local verdict
  local object
  local reason
  local dead=""

  fetch_array "ClusterRoles" \
    '[.items[] | {name: .metadata.name, labels: (.metadata.labels // {}), selectors: [.aggregationRule.clusterRoleSelectors[]? | .matchLabels // {}]}]' \
    oc get clusterroles || return 0
  roles="$QUERY_RESULT"
  fetch_array "ClusterRoleBindings" \
    '[.items[] | {name: .metadata.name, labels: (.metadata.labels // {}), role: .roleRef.name, subjects: (.subjects // [])}]' \
    oc get clusterrolebindings || return 0
  cluster_bindings="$QUERY_RESULT"
  # shellcheck disable=SC2016 # $ns is a jq variable
  fetch_array "RoleBindings" \
    '[.items[] | select(.roleRef.kind == "ClusterRole") | .metadata.namespace as $ns | {ns: $ns, name: .metadata.name, role: .roleRef.name, subjects: [(.subjects // [])[] | .namespace = (.namespace // $ns)]}]' \
    oc get rolebindings -A || return 0
  bindings="$QUERY_RESULT"
  fetch_array "ServiceAccounts" \
    '[.items[] | .metadata.namespace + "/" + .metadata.name]' \
    oc get serviceaccounts -A || return 0
  accounts="$QUERY_RESULT"

  if ! output=$(printf '%s\n' "$roles" "$cluster_bindings" "$bindings" "$accounts" | jq -r -s "$ODF_RBAC_JQ" 2>&1); then
    fail "ODF cluster RBAC jq filter failed: $output"
    return 0
  fi

  while IFS=$'\t' read -r verdict object reason; do
    case "$verdict" in
      kept) ok "$object retained: $reason" ;;
      dead) dead="${dead}${object}: ${reason}"$'\n' ;;
    esac
  done <<<"$output"

  if [ -n "$dead" ]; then
    warn "dead ODF cluster RBAC still exists:"
    printf '%s' "$dead"
  else
    ok "no dead ODF ClusterRoles or ClusterRoleBindings found"
  fi
}

echo "=== ODF Post-Uninstall Audit ==="

require_command oc || exit 1
require_command jq || exit 1

# Route every `oc` below through the parsed global args. A function is used so
# the 20-odd existing call sites (including those inside command substitutions,
# which inherit it) need no changes. Defined after require_command so that check
# still tests for the binary instead of finding this function.
oc() { command oc "${OC_GLOBAL_ARGS[@]}" "$@"; }

if ! OC_USER=$(oc whoami 2>&1); then
  fail "unable to contact the cluster with oc whoami: $OC_USER"
  exit 1
fi

# Name the cluster that was audited. Without this an audit of the wrong context
# reads exactly like an audit of the right one. The server URL is authoritative;
# the context label is only what was asked for.
if [ -z "$OC_CONTEXT_LABEL" ]; then
  OC_CONTEXT_LABEL=$(oc config current-context 2>/dev/null || echo unknown)
fi
echo "auditing $(oc whoami --show-server 2>/dev/null || echo unknown)" \
  "(context: ${OC_CONTEXT_LABEL:-unknown})"

detect_upstream_rook

check_storage_namespace
check_storage_namespace_pods
check_rook_namespaces

echo
# Namespace is the one kind with a real Terminating phase. A consumer namespace that
# held ODF bucket claims stays there while its objects keep objectbucket.io/finalizer.
check_json_list \
  "Terminating namespaces" \
  "no Terminating namespaces found" \
  '.items[] | select(.status.phase == "Terminating") | .metadata.name' \
  oc get namespaces

echo
check_api_group ocs.openshift.io
check_api_group odf.openshift.io
check_rook_shared_group ceph.rook.io
check_api_group noobaa.io
check_api_group postgresql.cnpg.noobaa.io
check_rook_shared_group csi.ceph.io
check_api_group csiaddons.openshift.io
check_rook_shared_group objectbucket.io
check_api_group replication.storage.openshift.io
check_api_group ramendr.openshift.io
check_groupsnapshot_group
if lso_retained; then
  ok "local.storage.openshift.io CRDs retained: LSO still installed"
else
  check_api_group local.storage.openshift.io
fi

echo
check_json_list \
  "ODF CephClusters" \
  "no ODF CephClusters found" \
  '.items[] | select(.metadata.namespace == "openshift-storage" or any(.metadata.ownerReferences[]?; .kind == "StorageCluster")) | .metadata.namespace + "/" + .metadata.name' \
  oc get cephclusters.ceph.rook.io -A

echo
check_json_list \
  "ODF StorageClasses" \
  "no ODF StorageClasses found" \
  '.items[] | select(.provisioner == "openshift-storage.rbd.csi.ceph.com" or .provisioner == "openshift-storage.cephfs.csi.ceph.com" or .provisioner == "openshift-storage.noobaa.io/obc" or .provisioner == "openshift-storage.ceph.rook.io/bucket") | .metadata.name' \
  oc get sc

echo
check_json_list \
  "ODF PVs" \
  "no ODF PVs found" \
  '.items[] | select((.spec.csi // {} | .driver == "openshift-storage.rbd.csi.ceph.com" or .driver == "openshift-storage.cephfs.csi.ceph.com") or ((.spec.storageClassName // "") | contains("ocs-storagecluster"))) | .metadata.name' \
  oc get pv

echo
check_json_list \
  "ODF PVCs" \
  "no ODF PVCs found" \
  '.items[] | select((.spec.storageClassName // "") | contains("ocs-storagecluster")) | .metadata.namespace + "/" + .metadata.name' \
  oc get pvc -A

# "Terminating" is only how `oc get` prints a deleting claim or volume. There is no
# such phase: it stays Bound or Released and the deletion shows in
# metadata.deletionTimestamp.
echo
check_json_list \
  "Terminating PVCs" \
  "no Terminating PVCs found" \
  '.items[] | select(.metadata.deletionTimestamp != null) | .metadata.namespace + "/" + .metadata.name + " (phase " + (.status.phase // "unknown") + ", finalizers: " + ((.metadata.finalizers // []) | join(",")) + ")"' \
  oc get pvc -A

echo
check_json_list \
  "Terminating PVs" \
  "no Terminating PVs found" \
  '.items[] | select(.metadata.deletionTimestamp != null) | .metadata.name + " (phase " + (.status.phase // "unknown") + ", finalizers: " + ((.metadata.finalizers // []) | join(",")) + ")"' \
  oc get pv

echo
check_json_list \
  "ODF VolumeAttachments" \
  "no ODF VolumeAttachments found" \
  ".items[] | select((.spec.attacher // \"\") | test(\"$ODF_CSI_DRIVER_RE\")) | .metadata.name + \" (pv \" + (.spec.source.persistentVolumeName // \"none\") + \", attached \" + (.status.attached // false | tostring) + \")\"" \
  oc get volumeattachment

echo
check_object_buckets

echo
check_json_list \
  "ODF CSIDrivers" \
  "no ODF CSIDrivers found" \
  '.items[] | select(.metadata.name == "openshift-storage.rbd.csi.ceph.com" or .metadata.name == "openshift-storage.cephfs.csi.ceph.com") | .metadata.name' \
  oc get csidriver

echo
check_sccs

echo
check_cluster_rbac

echo
check_json_list \
  "ODF mutating webhooks" \
  "no ODF mutating webhooks found" \
  '.items[] | select(.metadata.name == "csv.odf.openshift.io") | .metadata.name' \
  oc get mutatingwebhookconfiguration

echo
check_json_list \
  "ODF console plugins" \
  "no ODF console plugins found" \
  '.items[] | select(.metadata.name == "odf-console" or .metadata.name == "odf-client-console") | .metadata.name' \
  oc get consoleplugin

echo
# Cluster-scoped enable list survives ConsolePlugin CR deletion and namespace
# removal. Stale odf-* names here are undeploy residue.
if query_json \
  "console.operator enabled plugins" \
  '.spec.plugins // [] | .[]' \
  oc get console.operator.openshift.io cluster; then
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    fail "console.operator.openshift.io/cluster could not be queried"
  else
    STALE=$(printf '%s\n' "$QUERY_RESULT" | grep -E '^(odf-console|odf-client-console)$' || true)
    if [ -n "$STALE" ]; then
      fail "stale ODF names still in console.operator spec.plugins:"
      echo "$STALE"
    else
      ok "no ODF names in console.operator spec.plugins"
    fi
  fi
fi

echo
if query_json \
  "default StorageClasses" \
  '.items[] | select((.metadata.annotations?["storageclass.kubernetes.io/is-default-class"] == "true") or (.metadata.annotations?["storageclass.beta.kubernetes.io/is-default-class"] == "true")) | .metadata.name' \
  oc get sc; then
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    fail "default StorageClasses could not be queried because StorageClass is unavailable"
  else
    DEFAULT_SCS="$QUERY_RESULT"
    COUNT=$(count_nonempty_lines "$DEFAULT_SCS")
    if [ "$COUNT" -eq 1 ]; then
      ok "exactly one default StorageClass: $DEFAULT_SCS"
    elif [ "$COUNT" -eq 0 ]; then
      warn "no default StorageClass found"
    else
      warn "multiple default StorageClasses found:"
      echo "$DEFAULT_SCS"
    fi
  fi
fi

echo "=== Audit Complete ==="
exit "$FAILED"
