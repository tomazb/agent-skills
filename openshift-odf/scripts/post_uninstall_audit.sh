#!/usr/bin/env bash
set -euo pipefail

# Read-only post-uninstall audit for OpenShift Data Foundation (ODF).
# A warning marks the audit as failed: any ODF residue needs an operator decision.
#
# Known limitation: ODF is assumed to run in the default openshift-storage
# namespace (see odf_common.sh); an install in another namespace is not recognised.

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
    'PRIOR_DEFAULT_STORAGE_CLASS, when set, is the default StorageClass recorded' \
    'before uninstall (empty means there was none). The audit then warns only when' \
    'that policy changed. When the variable is unset, exactly one default is required.' \
    '' \
    'Unknown arguments are rejected. This script previously ignored them' \
    'silently, so a "--context other-cluster" that looked accepted actually' \
    'audited whichever context was current, and reported the result as if it' \
    'were the requested one.'
}

case "${BASH_SOURCE[0]}" in
  */*) SCRIPT_DIR="${BASH_SOURCE[0]%/*}" ;;
  *) SCRIPT_DIR="." ;;
esac
# shellcheck source-path=SCRIPTDIR
# shellcheck source=odf_common.sh
source "$SCRIPT_DIR/odf_common.sh"

parse_oc_args "$@"

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

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    fail "$cmd CLI is required but not installed"
    return 1
  fi
}

# Deletions younger than this are in progress, not stuck.
STUCK_AFTER_SECONDS=600
STUCK_JQ="def stuck: .metadata.deletionTimestamp != null and ((.metadata.deletionTimestamp | fromdateiso8601) < (now - $STUCK_AFTER_SECONDS));"
STUCK_NOTE="for over 10 minutes (younger deletions ignored)"

# Set API_RESOURCES to the list-able resources of a group (extra args such as
# --namespaced=true pass through to oc).
API_RESOURCES=""
api_resources() {
  local group="$1"
  shift

  API_RESOURCES=""
  run_split oc api-resources --api-group="$group" --verbs=list -o name "$@"
  if [ "$RUN_RC" -ne 0 ]; then
    fail "$group API resource discovery failed: $RUN_ERR"
    return 1
  fi
  API_RESOURCES="$RUN_OUT"
}

check_api_group() {
  local group="$1"

  api_resources "$group" || return 0
  if [ -n "$API_RESOURCES" ]; then
    warn "$group API resources still exist:"
    echo "$API_RESOURCES"
  else
    ok "no $group API resources found"
  fi
}

check_absent_resource() {
  local label="$1"
  local ok_message="$2"
  shift 2

  run_split oc get "$@"
  if [ "$RUN_RC" -eq 0 ]; then
    warn "$label still exists"
    [ -n "$RUN_OUT" ] && echo "$RUN_OUT"
  elif is_not_found "$RUN_ERR"; then
    ok "$ok_message"
  else
    fail "$label lookup failed: $RUN_ERR"
  fi

  return 0
}

# Run `<command> -o json` and filter it. stderr is kept apart from the JSON and
# only reported when the command fails, so a throttling or deprecation warning on
# a successful call does not break the filter.
query_json() {
  local label="$1"
  local jq_filter="$2"
  shift 2

  local output
  QUERY_RESULT=""
  QUERY_NOT_FOUND=0

  run_split "$@" -o json
  if [ "$RUN_RC" -ne 0 ]; then
    if is_not_found "$RUN_ERR"; then
      QUERY_NOT_FOUND=1
      return 0
    fi
    fail "$label query failed: $RUN_ERR"
    return 1
  fi
  # `-o json` always prints a document: a success that printed nothing must not
  # read as "none found".
  if [ -z "$RUN_OUT" ]; then
    fail "$label query returned nothing"
    return 1
  fi

  if ! output=$(jq -r "$jq_filter" <<<"$RUN_OUT" 2>&1); then
    fail "$label jq filter failed: $output"
    return 1
  fi

  QUERY_RESULT="$output"
}

report_list() {
  local label="$1"
  local ok_message="$2"
  local found="$3"

  if [ -z "$found" ]; then
    ok "$ok_message"
  else
    warn "$label still exist:"
    echo "$found"
  fi
}

check_json_list() {
  local label="$1"
  local ok_message="$2"
  local jq_filter="$3"
  shift 3

  if query_json "$label" "$jq_filter" "$@"; then
    report_list "$label" "$ok_message" "$QUERY_RESULT"
  fi
}

# Run the same filtered `oc get <kind> <args>` for each kind (one per line) and
# collect the output in COLLECTED. One kind at a time: oc fails a comma-joined get
# outright when any one kind is unknown, and that error reads as "not found",
# which would hide the residue of every other kind. An unknown kind is skipped;
# any other failure records a FAIL, the remaining kinds are still read, and the
# function returns 1.
COLLECTED=""
collect_per_kind() {
  local label="$1"
  local jq_filter="$2"
  local kinds="$3"
  shift 3

  local kind
  local failed=0
  COLLECTED=""
  while IFS= read -r kind; do
    [ -n "$kind" ] || continue
    if ! query_json "$label ($kind)" "$jq_filter" oc get "$kind" "$@"; then
      failed=1
      continue
    fi
    if [ -n "$QUERY_RESULT" ]; then
      COLLECTED="${COLLECTED:+$COLLECTED$'\n'}$QUERY_RESULT"
    fi
  done <<<"$kinds"
  return "$failed"
}

# Report what collect_per_kind found. After a failed kind there is no OK line:
# "none found" would be a claim about a kind that was never read.
report_collected() {
  local label="$1"
  local ok_message="$2"
  local complete="$3"

  if [ "$complete" -eq 1 ] || [ -n "$COLLECTED" ]; then
    report_list "$label" "$ok_message" "$COLLECTED"
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

# Like check_json_list, but the filter runs over several JSON documents (jq_slurp).
check_docs_list() {
  local label="$1"
  local ok_message="$2"
  local jq_filter="$3"
  shift 3

  run_split jq_slurp "$jq_filter" "$@"
  if [ "$RUN_RC" -ne 0 ]; then
    fail "$label jq filter failed: $RUN_ERR"
    return 0
  fi
  report_list "$label" "$ok_message" "$RUN_OUT"
}

# Namespaces holding an upstream (non-OLM) Rook cluster, one per line, the same
# list as a JSON array for jq filters, the CephClusters that are residue, and the
# objects whose owner the rule cannot tell.
ROOK_NAMESPACES=""
ROOK_NAMESPACES_JSON="[]"
CEPH_RESIDUE=""
CEPH_UNKNOWN=""
CEPH_CLASSIFIED=0

# Resources the API serves, one per line, set by find_served_resources.
SERVED_RESOURCES=""

# Set SERVED_RESOURCES to those of the named resources that $group serves.
find_served_resources() {
  local group="$1"
  shift

  local wanted
  local line
  SERVED_RESOURCES=""

  api_resources "$group" || return 1
  for wanted in "$@"; do
    while IFS= read -r line; do
      if [ "$line" = "$wanted" ]; then
        SERVED_RESOURCES="${SERVED_RESOURCES:+$SERVED_RESOURCES$'\n'}$wanted"
      fi
    done <<<"$API_RESOURCES"
  done
}

# LVMS and LSO install into openshift-storage by default. A kept namespace is only
# acceptable when a non-ODF operator still lives there; then it must hold no ODF residue.
check_storage_namespace() {
  run_split oc get namespace openshift-storage
  if [ "$RUN_RC" -ne 0 ]; then
    if is_not_found "$RUN_ERR"; then
      ok "openshift-storage namespace absent"
    else
      fail "openshift-storage namespace lookup failed: $RUN_ERR"
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
  local kinds
  kinds=$'secrets\nconfigmaps\nservices\ndeployments\ndaemonsets\nstatefulsets\nserviceaccounts\nroles\nrolebindings\npoddisruptionbudgets\njobs\ncronjobs'
  find_served_resources monitoring.coreos.com \
    servicemonitors.monitoring.coreos.com prometheusrules.monitoring.coreos.com || return 0
  if [ -n "$SERVED_RESOURCES" ]; then
    kinds="$kinds"$'\n'"$SERVED_RESOURCES"
  fi

  local complete=1
  collect_per_kind \
    "ODF residue objects in openshift-storage" \
    ".items[] | select(.metadata.name | test(\"$ODF_NAME_RE\"; \"i\")) | (.kind // \"object\") + \"/\" + .metadata.name" \
    "$kinds" -n openshift-storage || complete=0
  report_collected \
    "ODF residue objects in openshift-storage" \
    "no ODF residue objects in openshift-storage" \
    "$complete"
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
    "pods in openshift-storage deleting $STUCK_NOTE" \
    "no pods in openshift-storage deleting $STUCK_NOTE" \
    "$STUCK_JQ .items[] | select(stuck) | .metadata.name + \" (\" + (.status.phase // \"unknown\") + \", deleting since \" + .metadata.deletionTimestamp + \")\"" \
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

# Who runs Ceph, by the rule in odf_common.sh (ODF_CEPH_OWNERSHIP_JQ). A failed
# lookup leaves ROOK_NAMESPACES empty, so the shared groups then WARN rather than
# being excused. The whoami check at startup has already rejected an unusable
# --context, so a NotFound here can only come from the server.
detect_upstream_rook() {
  local clusters
  local deployments
  local csi_drivers
  local csidrivers
  local pvs
  local kind
  local subject
  local detail
  local ns

  query_json "CephClusters" '.' oc get cephclusters.ceph.rook.io -A || return 0
  clusters="${QUERY_RESULT:-"{\"items\":[]}"}"
  query_json "rook-ceph-operator Deployments" '.' \
    oc get deployments -A --field-selector metadata.name=rook-ceph-operator || return 0
  deployments="${QUERY_RESULT:-"{\"items\":[]}"}"
  # A Ceph CSI can outlive its operator and CephCluster while it still serves volumes.
  query_json "Ceph CSI Drivers" '.' oc get drivers.csi.ceph.io -A || return 0
  csi_drivers="${QUERY_RESULT:-"{\"items\":[]}"}"
  query_json "CSIDrivers" '.' oc get csidrivers || return 0
  csidrivers="${QUERY_RESULT:-"{\"items\":[]}"}"
  query_json "PersistentVolumes" '.' oc get pv || return 0
  pvs="${QUERY_RESULT:-"{\"items\":[]}"}"

  run_split jq_slurp "$ODF_CEPH_OWNERSHIP_JQ" "$clusters" "$deployments" "$csi_drivers" "$csidrivers" "$pvs"
  if [ "$RUN_RC" -ne 0 ]; then
    fail "CephCluster ownership jq filter failed: $RUN_ERR"
    return 0
  fi

  while IFS=$'\t' read -r kind subject detail; do
    case "$kind" in
      upstream) ROOK_NAMESPACES="${ROOK_NAMESPACES:+$ROOK_NAMESPACES$'\n'}$subject" ;;
      residue) CEPH_RESIDUE="${CEPH_RESIDUE:+$CEPH_RESIDUE$'\n'}$subject ($detail)" ;;
      unknown) CEPH_UNKNOWN="${CEPH_UNKNOWN:+$CEPH_UNKNOWN$'\n'}$subject ($detail)" ;;
    esac
  done <<<"$RUN_OUT"
  CEPH_CLASSIFIED=1

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
      ok "namespace $ns retained: part of an upstream (non-OLM) Rook cluster"
    fi
  done <<<"$ROOK_NAMESPACES"

  if ! is_rook_namespace rook-ceph; then
    check_absent_resource \
      "rook-ceph namespace" \
      "rook-ceph namespace absent" \
      namespace rook-ceph
  fi
}

# CephClusters ODF left behind (in openshift-storage, owned by a StorageCluster,
# or carrying ODF's name) or that are being deleted; then everything whose owner
# the rule cannot tell (an OLM-installed rook-ceph-operator, or a CephCluster with
# no non-OLM operator anywhere), which needs a decision before anything shared
# with Rook is removed. A CephCluster whose operator runs in another namespace is
# upstream Rook, not residue.
check_ceph_clusters() {
  [ "$CEPH_CLASSIFIED" -eq 1 ] || return 0
  report_list \
    "CephClusters left by ODF or being deleted" \
    "no CephClusters left by ODF or being deleted" \
    "$CEPH_RESIDUE"
  report_list \
    "Rook objects whose owner cannot be classified" \
    "every CephCluster and rook-ceph-operator has a classified owner" \
    "$CEPH_UNKNOWN"
}

# ceph.rook.io, csi.ceph.io and objectbucket.io are shared with upstream Rook. While
# a Rook cluster runs its CRDs stay; instances outside its namespaces are not its own.
check_rook_shared_group() {
  local group="$1"

  if ! upstream_rook_present; then
    check_api_group "$group"
    return 0
  fi

  api_resources "$group" || return 0
  if [ -z "$API_RESOURCES" ]; then
    ok "no $group API resources found"
    return 0
  fi
  ok "$group API resources retained for upstream Rook in: ${ROOK_NAMESPACES//$'\n'/ }"

  api_resources "$group" --namespaced=true || return 0
  # Bucket claims live in application namespaces by design; their StorageClass
  # decides whose they are (check_object_buckets), not their namespace.
  local kinds=""
  local kind
  while IFS= read -r kind; do
    if [ -n "$kind" ] && [ "$kind" != "objectbucketclaims.objectbucket.io" ]; then
      kinds="${kinds:+$kinds$'\n'}$kind"
    fi
  done <<<"$API_RESOURCES"

  local complete=1
  collect_per_kind \
    "$group objects outside upstream Rook namespaces" \
    "$ROOK_NAMESPACES_JSON as \$rook | .items[] | select(.metadata.namespace as \$ns | any(\$rook[]; . == \$ns) | not) | (.kind // \"object\") + \"/\" + .metadata.namespace + \"/\" + .metadata.name" \
    "$kinds" -A || complete=0
  report_collected \
    "$group objects outside upstream Rook namespaces" \
    "no $group objects outside upstream Rook namespaces" \
    "$complete"
}

# groupsnapshot.storage.openshift.io is residue only when it is provably ODF's and
# unused: every CRD in the group carries an ODF package OLM label and no
# release-payload annotation, no instance of any of its kinds exists, and the
# VolumeGroupSnapshot feature gate is not enabled. Anything else may be
# platform-owned or in use and is reported for review. Whether another snapshotter
# relies on the group cannot be read from the API; the runbook checks that by hand.
check_groupsnapshot_group() {
  local group="groupsnapshot.storage.openshift.io"
  local reason=""
  local kinds
  local count

  api_resources "$group" || return 0
  kinds="$API_RESOURCES"
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
    collect_per_kind "$group instances" '.items[] | .metadata.name' "$kinds" -A || return 0
    count=$(count_nonempty_lines "$COLLECTED")
    if [ "$count" -ne 0 ]; then
      reason="$count instances exist"
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

# jq: whose the object (its storage class name in .sc) is: "odf" when its class
# names an ODF provisioner, "other" for any other provisioner. A class that is gone
# is "odf" only when no upstream Rook runs ($rook empty); next to upstream Rook a
# Rook claim may have outlived its class too, so it is "unknown". $classes maps
# StorageClass name to provisioner.
ODF_BUCKET_JQ="def bucket_owner(\$classes; \$rook): (\$classes[.sc // \"\"] // null) as \$p
  | if \$p == null then (if (\$rook | length) > 0 then \"unknown\" else \"odf\" end)
    elif (\$p | test(\"$ODF_BUCKET_PROVISIONER_RE\")) then \"odf\" else \"other\" end;
def describe(\$classes): \"(class \(.sc // \"none\"): \(\$classes[.sc // \"\"] // \"missing\"))\";"

# Bucket claims and buckets are ODF's only when their class uses an ODF provisioner,
# or is gone while no upstream Rook runs; a running upstream Rook serves its own
# through the same CRDs. One that lost its class next to upstream Rook needs review.
BUCKET_CLASSES=""
BUCKET_CLAIMS=""
check_object_buckets() {
  local buckets

  fetch_array "StorageClasses" \
    '[[.items[] | {key: .metadata.name, value: .provisioner}] | from_entries]' \
    oc get sc || return 0
  BUCKET_CLASSES="$QUERY_RESULT"
  fetch_array "ObjectBucketClaims" \
    '[.items[] | {ns: .metadata.namespace, name: .metadata.name, sc: .spec.storageClassName}]' \
    oc get obc -A || return 0
  BUCKET_CLAIMS="$QUERY_RESULT"
  fetch_array "ObjectBuckets" \
    '[.items[] | {name: .metadata.name, sc: .spec.storageClassName}]' \
    oc get objectbucket || return 0
  buckets="$QUERY_RESULT"

  check_docs_list \
    "ODF ObjectBucketClaims" \
    "no ODF ObjectBucketClaims found" \
    "$ODF_BUCKET_JQ $ROOK_NAMESPACES_JSON as \$rook | (.[0][0] // {}) as \$classes | .[1][] | select(bucket_owner(\$classes; \$rook) == \"odf\") | \"\(.ns)/\(.name) \" + describe(\$classes)" \
    "$BUCKET_CLASSES" "$BUCKET_CLAIMS"

  echo
  check_docs_list \
    "ODF ObjectBuckets" \
    "no ODF ObjectBuckets found" \
    "$ODF_BUCKET_JQ $ROOK_NAMESPACES_JSON as \$rook | (.[0][0] // {}) as \$classes | .[1][] | select(bucket_owner(\$classes; \$rook) == \"odf\") | \"\(.name) \" + describe(\$classes)" \
    "$BUCKET_CLASSES" "$buckets"

  echo
  check_docs_list \
    "bucket claims and buckets of unknown owner (StorageClass gone while upstream Rook runs; review by hand)" \
    "no bucket claims or buckets of unknown owner" \
    "$ODF_BUCKET_JQ $ROOK_NAMESPACES_JSON as \$rook | (.[0][0] // {}) as \$classes
      | (.[1][] | select(bucket_owner(\$classes; \$rook) == \"unknown\") | \"ObjectBucketClaim \(.ns)/\(.name) \" + describe(\$classes)),
        (.[2][] | select(bucket_owner(\$classes; \$rook) == \"unknown\") | \"ObjectBucket \(.name) \" + describe(\$classes))" \
    "$BUCKET_CLASSES" "$BUCKET_CLAIMS" "$buckets"
}

# A claim's ConfigMap and Secret carry objectbucket.io/finalizer too; once the
# provisioner is gone they hold their namespace in Terminating. Every claim that is
# not provably ODF's (another provisioner's, or of unknown owner) counts as live. Only openshift-storage
# and Terminating namespaces are read, and only names and finalizers: jsonpath keeps
# Secret data out of this script (oc itself still receives the full objects).
TERMINATING_NAMESPACES=""
check_bucket_finalizers() {
  local live
  local ns
  local resource
  local kind
  local name
  local finalizers
  local key
  local found=""
  local incomplete=0

  if [ -z "$BUCKET_CLASSES" ] || [ -z "$BUCKET_CLAIMS" ]; then
    return 0
  fi
  run_split jq_slurp \
    "$ODF_BUCKET_JQ $ROOK_NAMESPACES_JSON as \$rook | (.[0][0] // {}) as \$classes | .[1][] | select(bucket_owner(\$classes; \$rook) != \"odf\") | \"\(.ns)/\(.name)\"" \
    "$BUCKET_CLASSES" "$BUCKET_CLAIMS"
  if [ "$RUN_RC" -ne 0 ]; then
    fail "live bucket claims jq filter failed: $RUN_ERR"
    return 0
  fi
  live=$'\n'"$RUN_OUT"$'\n'

  while IFS= read -r ns; do
    [ -n "$ns" ] || continue
    for resource in configmaps secrets; do
      case "$resource" in
        configmaps) kind=ConfigMap ;;
        *) kind=Secret ;;
      esac
      run_split oc get "$resource" -n "$ns" \
        -o 'jsonpath={range .items[*]}{.metadata.name}{"\t"}{.metadata.finalizers[*]}{"\n"}{end}'
      if [ "$RUN_RC" -ne 0 ]; then
        if is_not_found "$RUN_ERR"; then
          continue
        elif is_forbidden "$RUN_ERR"; then
          fail "could not check $resource in $ns for objectbucket.io/finalizer: listing $resource is forbidden for this user; rerun with a role that can list $resource there"
        else
          fail "could not check $resource in $ns for objectbucket.io/finalizer: $RUN_ERR"
        fi
        incomplete=1
        continue
      fi
      while IFS=$'\t' read -r name finalizers; do
        [ -n "$name" ] || continue
        case " $finalizers " in
          *" objectbucket.io/finalizer "*) ;;
          *) continue ;;
        esac
        key="$ns/$name"
        case "$live" in
          *$'\n'"$key"$'\n'*) continue ;;
        esac
        found="${found:+$found$'\n'}$kind/$key"
      done <<<"$RUN_OUT"
    done
  done <<<"openshift-storage"$'\n'"$TERMINATING_NAMESPACES"

  if [ -n "$found" ]; then
    warn "ConfigMaps and Secrets held by objectbucket.io/finalizer without a live claim still exist:"
    echo "$found"
  elif [ "$incomplete" -eq 0 ]; then
    ok "no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim (checked openshift-storage and Terminating namespaces)"
  fi
}

# Namespace is the one kind with a real Terminating phase. A consumer namespace that
# held ODF bucket claims stays there while its objects keep objectbucket.io/finalizer.
# Every Terminating namespace is remembered for check_bucket_finalizers; only those
# deleting for longer than the threshold are reported.
check_terminating_namespaces() {
  query_json \
    "Terminating namespaces" \
    "[.items[] | select(.status.phase == \"Terminating\")] | (.[] | \"all\t\" + .metadata.name), ($STUCK_JQ .[] | select(stuck) | \"stuck\t\" + .metadata.name)" \
    oc get namespaces || return 0

  local state
  local name
  local stuck=""
  while IFS=$'\t' read -r state name; do
    case "$state" in
      all) TERMINATING_NAMESPACES="${TERMINATING_NAMESPACES:+$TERMINATING_NAMESPACES$'\n'}$name" ;;
      stuck) stuck="${stuck:+$stuck$'\n'}$name" ;;
    esac
  done <<<"$QUERY_RESULT"

  report_list \
    "namespaces Terminating $STUCK_NOTE" \
    "no namespaces Terminating $STUCK_NOTE" \
    "$stuck"
}

# SCCs named for Rook, NooBaa, or ceph-csi. With upstream Rook running, an SCC whose
# every user is a service account of a Rook namespace (and whose groups, if any,
# are the service-account groups of those namespaces) belongs to that Rook.
check_sccs() {
  local rook_scc_jq="def rook_scc(\$rook): (\$rook | length) > 0 and ((.users // []) | length) > 0 and all((.users // [])[]; split(\":\") as \$p | ((\$p | length) == 4) and \$p[0] == \"system\" and \$p[1] == \"serviceaccount\" and any(\$rook[]; . == \$p[2])) and all((.groups // [])[]; split(\":\") as \$p | ((\$p | length) == 3) and \$p[0] == \"system\" and \$p[1] == \"serviceaccounts\" and any(\$rook[]; . == \$p[2]));"
  local name_jq='select((.metadata.name | contains("rook-ceph")) or (.metadata.name | contains("noobaa")) or (.metadata.name | contains("ceph-csi")) or (.metadata.name | contains("odf-blackbox")))'
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
# - a ClusterRoleBinding is dead when its ClusterRole is missing (even with a
#   User/Group subject), or when it has no User/Group subject (those cannot be
#   proven absent) and none of its ServiceAccount subjects exists;
# - rook-ceph-metrics and ocs-metrics-reader are also dead when the only live
#   ServiceAccount is openshift-monitoring/prometheus-k8s. That account exists on
#   every OpenShift cluster, so it is not evidence that Ceph is still scraped.
#   rook-ceph-metrics stays live while upstream Rook is present; ocs-metrics-reader
#   does not, because the ODF metrics exporter is already gone;
# - a ClusterRole is dead when no live ClusterRoleBinding or RoleBinding references
#   it (a dead binding does not keep its role alive) and no other ClusterRole's
#   aggregationRule selects it. A selector is evaluated in full, matchLabels and
#   matchExpressions (In, NotIn, Exists, DoesNotExist). An empty one ({}) selects
#   every ClusterRole: Kubernetes reads a non-nil empty label selector as
#   "everything". One that cannot be evaluated keeps the role, never kills it.
# RoleBindings are judged by the same subject rule.
ODF_RBAC_JQ="
def expr_result(\$labels):
  . as \$e
  | if (\$e | type) != \"object\" or (\$e.key | type) != \"string\" then \"error\"
    elif \$e.operator == \"Exists\" then (\$labels | has(\$e.key))
    elif \$e.operator == \"DoesNotExist\" then (\$labels | has(\$e.key) | not)
    elif (\$e.values | type) != \"array\" then \"error\"
    elif \$e.operator == \"In\" then ((\$labels | has(\$e.key)) and any(\$e.values[]; . == \$labels[\$e.key]))
    elif \$e.operator == \"NotIn\" then ((\$labels | has(\$e.key) | not) or all(\$e.values[]; . != \$labels[\$e.key]))
    else \"error\" end;
def selector_result(\$labels):
  if type != \"object\" then \"error\"
  else (.matchLabels // {}) as \$ml | (.matchExpressions // []) as \$me
    | if (\$ml | type) != \"object\" or (\$me | type) != \"array\" then \"error\"
      elif (\$ml | length) == 0 and (\$me | length) == 0 then \"all\"
      else [(\$ml | to_entries[] | \$labels[.key] == .value), (\$me[] | expr_result(\$labels))]
        | if any(.[]; . == \"error\") then \"error\" else all(.[]; . == true) end
      end
  end;
def odf_owned(\$names):
  ((.labels[\"olm.owner\"] // \"\") | test(\"$ODF_CSV_PREFIX_RE\"))
  or any(.labels | keys[]; test(\"$ODF_PACKAGE_LABEL_RE\"))
  or (.name as \$n | any(\$names[]; . == \$n));
def live_sas(\$sas):
  [.subjects[] | select(.kind == \"ServiceAccount\") | \"\(.namespace)/\(.name)\" | select(\$sas[.] // false)];
def platform_prometheus_only(\$sas):
  (any(.subjects[]; .kind == \"User\" or .kind == \"Group\") | not)
  and ((live_sas(\$sas) | length) > 0)
  and all(live_sas(\$sas)[]; . == \"openshift-monitoring/prometheus-k8s\");
def verdict(\$roles; \$sas; \$rook_up):
  if (\$roles[.role] // false) | not then {live: false, why: \"its ClusterRole \(.role) is missing\"}
  elif any(.subjects[]; .kind == \"User\" or .kind == \"Group\") then {live: true, why: \"has a User/Group subject, which cannot be proven absent\"}
  elif platform_prometheus_only(\$sas) and ((.role == \"ocs-metrics-reader\") or (.role == \"rook-ceph-metrics\" and (\$rook_up | not))) then {live: false, why: \"only the platform ServiceAccount openshift-monitoring/prometheus-k8s remains, which is not a Ceph consumer\"}
  elif (live_sas(\$sas) | length) > 0 then {live: true, why: \"bound to live ServiceAccount \(live_sas(\$sas) | join(\", \"))\"}
  else {live: false, why: \"none of its ServiceAccount subjects exists\"} end;
.[0] as \$crs | .[1] as \$crbs | .[2] as \$rbs
| (.[3] | map({key: ., value: true}) | from_entries) as \$sas
| .[4] as \$rook_up
| (\$crs | map({key: .name, value: true}) | from_entries) as \$roles
| ([\$crbs[] | . + {ref: \"ClusterRoleBinding/\(.name)\", odf: odf_owned([\"ocs-metrics-exporter\", \"ocs-metrics-reader\", \"rook-ceph-metrics\"])}]
   + [\$rbs[] | . + {ref: \"RoleBinding \(.ns)/\(.name)\", odf: false}]
   | map(. + verdict(\$roles; \$sas; \$rook_up))) as \$bindings
| (\$bindings[] | select(.odf) | [(if .live then \"kept\" else \"dead\" end), .ref, .why] | @tsv),
  (\$crs[] | select(odf_owned([\"ocs-metrics-exporter\", \"ocs-metrics-reader\"])) | . as \$role
   | [\$bindings[] | select(.role == \$role.name)] as \$refs
   | [\$refs[] | select(.live) | .ref] as \$live_refs
   | [\$crs[] | select(.name != \$role.name) | .name as \$into | .selectors[]
      | {into: \$into, result: selector_result(\$role.labels)}] as \$selected
   | [\$selected[] | select(.result == \"all\") | .into] as \$all_rules
   | if (\$live_refs | length) > 0 then [\"kept\", \"ClusterRole/\(.name)\", \"referenced by live \(\$live_refs | join(\", \"))\"]
     elif (\$all_rules | length) > 0 then [\"kept\", \"ClusterRole/\(.name)\", \"aggregated by a select-all rule into \(\$all_rules | join(\", \"))\"]
     elif any(\$selected[]; .result == true) then [\"kept\", \"ClusterRole/\(.name)\", \"aggregated into another ClusterRole\"]
     elif any(\$selected[]; .result == \"error\") then [\"kept\", \"ClusterRole/\(.name)\", \"aggregation selector could not be evaluated\"]
     elif (\$refs | length) > 0 then [\"dead\", \"ClusterRole/\(.name)\", \"referenced only by dead \([\$refs[].ref] | join(\", \"))\"]
     else [\"dead\", \"ClusterRole/\(.name)\", \"no binding references it\"] end
   | @tsv)
"

check_cluster_rbac() {
  local roles
  local cluster_bindings
  local bindings
  local accounts
  local verdict
  local object
  local reason
  local dead=""

  fetch_array "ClusterRoles" \
    '[.items[] | {name: .metadata.name, labels: (.metadata.labels // {}), selectors: [.aggregationRule.clusterRoleSelectors[]?]}]' \
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

  local rook_up=false
  if upstream_rook_present; then
    rook_up=true
  fi
  run_split jq_slurp "$ODF_RBAC_JQ" "$roles" "$cluster_bindings" "$bindings" "$accounts" "$rook_up"
  if [ "$RUN_RC" -ne 0 ]; then
    fail "ODF cluster RBAC jq filter failed: $RUN_ERR"
    return 0
  fi

  while IFS=$'\t' read -r verdict object reason; do
    case "$verdict" in
      kept) ok "$object retained: $reason" ;;
      dead) dead="${dead}${object}: ${reason}"$'\n' ;;
    esac
  done <<<"$RUN_OUT"

  if [ -n "$dead" ]; then
    warn "dead ODF cluster RBAC still exists:"
    printf '%s' "$dead"
  else
    ok "no dead ODF ClusterRoles or ClusterRoleBindings found"
  fi
}

# NooBaa and the CloudNativePG manager leave RoleBindings in kube-system on the
# platform Role extension-apiserver-authentication-reader. The Role is
# bootstrapped by the cluster and other operators bind it; delete only the
# storage bindings whose ServiceAccounts are gone.
check_storage_extension_auth_bindings() {
  local bindings
  local accounts
  local verdict
  local object
  local reason
  local dead=""

  fetch_array "NooBaa and CNPG extension-apiserver RoleBindings" \
    '[.items[] | select(.roleRef.kind == "Role" and .roleRef.name == "extension-apiserver-authentication-reader" and (.metadata.name | test("noobaa|cnpg"))) | {ns: .metadata.namespace, name: .metadata.name, subjects: (.subjects // [])}]' \
    oc get rolebindings -A || return 0
  bindings="$QUERY_RESULT"
  fetch_array "ServiceAccounts" \
    '[.items[] | .metadata.namespace + "/" + .metadata.name]' \
    oc get serviceaccounts -A || return 0
  accounts="$QUERY_RESULT"

  run_split jq_slurp \
    '. [1] as $sas
     | ([$sas[] | {key: ., value: true}] | from_entries) as $live
     | .[0][]
     | [.subjects[]? | select(.kind == "ServiceAccount") | ((.namespace // "") + "/" + .name)] as $wanted
     | if (($wanted | length) > 0) and any($wanted[]; $live[.] // false) then
         ["kept", "RoleBinding \(.ns)/\(.name)", "bound to a live ServiceAccount"]
       else
         ["dead", "RoleBinding \(.ns)/\(.name)", "delete the RoleBinding and keep Role extension-apiserver-authentication-reader"]
       end
     | @tsv' \
    "$bindings" "$accounts"
  if [ "$RUN_RC" -ne 0 ]; then
    fail "extension-apiserver RoleBinding jq filter failed: $RUN_ERR"
    return 0
  fi

  while IFS=$'\t' read -r verdict object reason; do
    [ -n "$verdict" ] || continue
    case "$verdict" in
      kept) ok "$object retained: $reason" ;;
      dead) dead="${dead}${object}: ${reason}"$'\n' ;;
    esac
  done <<<"$RUN_OUT"

  if [ -n "$dead" ]; then
    warn "dead NooBaa or CNPG extension-apiserver RoleBindings still exist:"
    printf '%s' "$dead"
  else
    ok "no dead NooBaa or CNPG extension-apiserver RoleBindings found"
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
check_terminating_namespaces

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
check_ceph_clusters

echo
check_json_list \
  "ODF StorageClasses" \
  "no ODF StorageClasses found" \
  ".items[] | select((.provisioner // \"\") | test(\"$ODF_PROVISIONER_RE\")) | .metadata.name" \
  oc get sc

echo
check_json_list \
  "ODF PVs" \
  "no ODF PVs found" \
  ".items[] | select(((.spec.csi.driver // \"\") | test(\"$ODF_CSI_DRIVER_RE\")) or ((.spec.storageClassName // \"\") | contains(\"ocs-storagecluster\"))) | .metadata.name" \
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
  "PVCs Terminating $STUCK_NOTE" \
  "no PVCs Terminating $STUCK_NOTE" \
  "$STUCK_JQ .items[] | select(stuck) | .metadata.namespace + \"/\" + .metadata.name + \" (phase \" + (.status.phase // \"unknown\") + \", finalizers: \" + ((.metadata.finalizers // []) | join(\",\")) + \")\"" \
  oc get pvc -A

echo
check_json_list \
  "PVs Terminating $STUCK_NOTE" \
  "no PVs Terminating $STUCK_NOTE" \
  "$STUCK_JQ .items[] | select(stuck) | .metadata.name + \" (phase \" + (.status.phase // \"unknown\") + \", finalizers: \" + ((.metadata.finalizers // []) | join(\",\")) + \")\"" \
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
check_bucket_finalizers

echo
check_json_list \
  "ODF CSIDrivers" \
  "no ODF CSIDrivers found" \
  ".items[] | select(.metadata.name | test(\"$ODF_CSI_DRIVER_RE\")) | .metadata.name" \
  oc get csidriver

echo
check_sccs

echo
check_cluster_rbac

echo
check_storage_extension_auth_bindings

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
    STALE=""
    while IFS= read -r plugin; do
      case "$plugin" in
        odf-console|odf-client-console) STALE="${STALE:+$STALE$'\n'}$plugin" ;;
      esac
    done <<<"$QUERY_RESULT"
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
    found=""
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      found="${found:+$found,}$line"
    done <<<"$DEFAULT_SCS"
    [ -n "$found" ] || found=none
    # PRIOR_DEFAULT_STORAGE_CLASS is recorded before uninstall. Unset keeps the
    # historical check (exactly one default). An empty value means the cluster
    # had no default, which is a valid end state.
    if [ -z "${PRIOR_DEFAULT_STORAGE_CLASS+x}" ]; then
      if [ "$COUNT" -eq 1 ]; then
        ok "exactly one default StorageClass: $DEFAULT_SCS"
      elif [ "$COUNT" -eq 0 ]; then
        warn "no default StorageClass found"
      else
        warn "multiple default StorageClasses found:"
        echo "$DEFAULT_SCS"
      fi
    elif [ -z "$PRIOR_DEFAULT_STORAGE_CLASS" ]; then
      if [ "$COUNT" -eq 0 ]; then
        ok "no default StorageClass, matching the pre-install policy"
      else
        warn "default StorageClass is '$found', pre-install policy had none"
      fi
    elif [ "$found" = "$PRIOR_DEFAULT_STORAGE_CLASS" ]; then
      ok "exactly one default StorageClass: $DEFAULT_SCS"
    else
      warn "default StorageClass is '$found', pre-install policy was $PRIOR_DEFAULT_STORAGE_CLASS"
    fi
  fi
fi

echo "=== Audit Complete ==="
exit "$FAILED"
