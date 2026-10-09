#!/usr/bin/env bash
set -euo pipefail

# Read-only post-uninstall audit for upstream Rook Ceph.
# A warning marks the audit as failed: any Rook residue needs an operator decision.
#
# Objects are matched by CSI driver, provisioner, StorageClass, and ownership, never
# by a "rook-ceph" name alone: ODF creates objects with such names too. When ODF is
# present (see ROOK_CEPH_OWNERSHIP_JQ in rook_common.sh) the ceph.rook.io,
# csi.ceph.io, and objectbucket.io CRDs are ODF's to keep, and only their instances
# that are provably this Rook's are residue.

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
    '                               [--namespace NAME] [--csi-prefix PREFIX]' \
    '' \
    'Read-only audit for Rook Ceph residue after an uninstall. Exits nonzero on' \
    'any WARN or FAIL line.' \
    '' \
    '  --context NAME       kubeconfig context to audit (default: the current one)' \
    '  --kubeconfig PATH    kubeconfig file to use' \
    '  --namespace NAME     namespace Rook ran in (default: rook-ceph)' \
    '  --csi-prefix PREFIX  CSI_DRIVER_NAME_PREFIX Rook used (default: the namespace)' \
    '  -h, --help           show this help' \
    '' \
    'PRIOR_DEFAULT_STORAGE_CLASS, when set, is the default StorageClass recorded' \
    'before uninstall (empty means there was none). The audit then warns only when' \
    'that policy changed. When the variable is unset, exactly one default is required.'
}

case "${BASH_SOURCE[0]}" in
  */*) SCRIPT_DIR="${BASH_SOURCE[0]%/*}" ;;
  *) SCRIPT_DIR="." ;;
esac
# shellcheck source-path=SCRIPTDIR
# shellcheck source=rook_common.sh
source "$SCRIPT_DIR/rook_common.sh"

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
# a successful call does not break the filter. "No such resource" sets
# QUERY_NOT_FOUND and is not an error; a success that printed nothing is one,
# because `-o json` always prints a document and "nothing" must not read as "none".
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

# A kind the API does not serve (its CRD is not installed) is reported as such, so
# an OK line never reads as a claim about a kind that was never listed.
check_json_list() {
  local label="$1"
  local ok_message="$2"
  local jq_filter="$3"
  shift 3

  if query_json "$label" "$jq_filter" "$@"; then
    if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
      ok "$ok_message (resource type not served)"
    else
      report_list "$label" "$ok_message" "$QUERY_RESULT"
    fi
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

# Names and finalizers of one kind in one namespace, as "name<TAB>finalizers" lines
# in NAMES_OUT. jsonpath keeps Secret data out of this script (oc itself still
# receives the full objects). A missing namespace reads as empty; any other failure
# records a FAIL and returns 1.
NAMES_OUT=""
list_names() {
  local resource="$1"
  local ns="$2"
  local purpose="$3"

  NAMES_OUT=""
  run_split oc get "$resource" -n "$ns" \
    -o 'jsonpath={range .items[*]}{.metadata.name}{"\t"}{.metadata.finalizers[*]}{"\n"}{end}'
  if [ "$RUN_RC" -ne 0 ]; then
    if is_not_found "$RUN_ERR"; then
      return 0
    elif is_forbidden "$RUN_ERR"; then
      fail "could not check $resource in $ns for $purpose: listing $resource is forbidden for this user; rerun with a role that can list $resource there"
    else
      fail "could not check $resource in $ns for $purpose: $RUN_ERR"
    fi
    return 1
  fi
  NAMES_OUT="$RUN_OUT"
}

# Who runs Ceph, by the rule in rook_common.sh (ROOK_CEPH_OWNERSHIP_JQ). A failed
# lookup leaves CEPH_CLASSIFIED at 0 and no ODF signal, so the shared groups are
# then judged as if no ODF ran: they WARN rather than being excused.
ROOK_LIVE=""
ODF_SIGNALS=""
CEPH_UNKNOWN=""
CEPH_CLASSIFIED=0
CSVS_JSON="[]"
SUBSCRIPTIONS_JSON="[]"

# Fetch a CRD-backed list into QUERY_RESULT only when its group serves it. An
# absent group is read from a successful, empty discovery, never from an error.
fetch_if_served() {
  local label="$1"
  local group="$2"
  local resource="$3"
  shift 3

  local line
  api_resources "$group" || return 1
  while IFS= read -r line; do
    if [ "$line" = "$resource" ]; then
      query_json "$label" '.' oc get "$resource" "$@" || return 1
      strict_lookup "$label" || return 1
      return 0
    fi
  done <<<"$API_RESOURCES"
  QUERY_RESULT='{"items":[]}'
}

# The ownership lookups are as strict as the classifier's: "no such resource" is a
# failure for every kind except the CephCluster CRD, and there only "the server
# doesn't have a resource type" reads as none.
strict_lookup() {
  local label="$1"

  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    fail "$label lookup failed: $RUN_ERR"
    return 1
  fi
}

detect_ownership() {
  local clusters
  local deployments
  local storageclusters
  local subscriptions
  local csvs
  local csi_drivers
  local csidrivers
  local pvs
  local kind
  local subject
  local detail

  query_json "CephClusters" '.' oc get cephclusters.ceph.rook.io -A || return 0
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    if ! is_missing_resource_type "$RUN_ERR"; then
      fail "CephClusters lookup failed: $RUN_ERR"
      return 0
    fi
    QUERY_RESULT='{"items":[]}'
  fi
  clusters="$QUERY_RESULT"
  query_json "rook-ceph-operator Deployments" '.' \
    oc get deployments -A --field-selector metadata.name=rook-ceph-operator || return 0
  strict_lookup "rook-ceph-operator Deployments" || return 0
  deployments="$QUERY_RESULT"
  fetch_if_served "StorageClusters" ocs.openshift.io storageclusters.ocs.openshift.io -A || return 0
  storageclusters="$QUERY_RESULT"
  query_json "Subscriptions" '.' oc get subscriptions.operators.coreos.com -A || return 0
  strict_lookup "Subscriptions" || return 0
  subscriptions="$QUERY_RESULT"
  query_json "ClusterServiceVersions" '.' oc get clusterserviceversions.operators.coreos.com -A || return 0
  strict_lookup "ClusterServiceVersions" || return 0
  csvs="$QUERY_RESULT"
  # A Ceph CSI can outlive its operator and CephCluster while it still serves volumes.
  fetch_if_served "Ceph CSI Drivers" csi.ceph.io drivers.csi.ceph.io -A || return 0
  csi_drivers="$QUERY_RESULT"
  query_json "CSIDrivers" '.' oc get csidrivers || return 0
  strict_lookup "CSIDrivers" || return 0
  csidrivers="$QUERY_RESULT"
  query_json "PersistentVolumes" '.' oc get pv || return 0
  strict_lookup "PersistentVolumes" || return 0
  pvs="$QUERY_RESULT"

  run_split jq_slurp "$ROOK_CEPH_OWNERSHIP_JQ" "$clusters" "$deployments" "$storageclusters" \
    "$subscriptions" "$csvs" "$csi_drivers" "$csidrivers" "$pvs" "\"$ROOK_CSI_DRIVER_RE\""
  if [ "$RUN_RC" -ne 0 ]; then
    fail "Ceph ownership jq filter failed: $RUN_ERR"
    return 0
  fi

  while IFS=$'\t' read -r kind subject detail; do
    case "$kind" in
      rook) ROOK_LIVE="${ROOK_LIVE:+$ROOK_LIVE$'\n'}$subject (CephCluster: $detail)" ;;
      odf) ODF_SIGNALS="${ODF_SIGNALS:+$ODF_SIGNALS$'\n'}$subject ($detail)" ;;
      unknown) CEPH_UNKNOWN="${CEPH_UNKNOWN:+$CEPH_UNKNOWN$'\n'}$subject ($detail)" ;;
    esac
  done <<<"$RUN_OUT"
  CEPH_CLASSIFIED=1

  # For the RBAC check: which OLM operators are installed.
  # shellcheck disable=SC2016 # jq, not shell, expressions
  if ! CSVS_JSON=$(jq -c '[.items[] | "\(.metadata.namespace)/\(.metadata.name)"]' <<<"$csvs" 2>&1) ||
     ! SUBSCRIPTIONS_JSON=$(jq -c '[.items[] | "\(.metadata.namespace)/\(.spec.name // "")"]' <<<"$subscriptions" 2>&1); then
    fail "OLM operator list jq filter failed"
    CSVS_JSON="[]"
    SUBSCRIPTIONS_JSON="[]"
  fi
}

odf_present() {
  [ -n "$ODF_SIGNALS" ]
}

# After an uninstall nothing may still run Rook. ODF is another product and stays.
check_ownership() {
  [ "$CEPH_CLASSIFIED" -eq 1 ] || return 0
  report_list \
    "upstream Rook operators or CephClusters" \
    "no upstream Rook operator or CephCluster runs" \
    "$ROOK_LIVE"
  report_list \
    "Ceph objects whose owner cannot be classified (decide by hand; see Orphans After An Interrupted Uninstall)" \
    "every CephCluster, rook-ceph-operator, and Ceph CSI driver has a classified owner" \
    "$CEPH_UNKNOWN"
  if odf_present; then
    ok "ODF present; its objects are not Rook residue (openshift-odf manages them):"
    echo "$ODF_SIGNALS"
  else
    ok "no ODF present"
  fi
}

# The Rook namespace must be gone. While it exists (kept, or stuck deleting), list
# what is still in it: pods, and objects named for Rook, Ceph, or its CSI.
check_rook_namespace() {
  local ns="$ROOK_NAMESPACE"
  local name_re='rook|ceph|csi|objectbucket|rbd'
  local complete=1
  local resource
  local kind
  local name
  local finalizers

  query_json \
    "namespace $ns" \
    "$STUCK_JQ if .metadata.deletionTimestamp == null then \"active\" elif stuck then \"stuck \" + .metadata.deletionTimestamp else \"deleting \" + .metadata.deletionTimestamp end" \
    oc get namespaces "$ns" || return 0
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    ok "namespace $ns absent"
    return 0
  fi
  case "$QUERY_RESULT" in
    active) warn "namespace $ns still exists" ;;
    stuck*) warn "namespace $ns Terminating since ${QUERY_RESULT#stuck } ($STUCK_NOTE)" ;;
    *) warn "namespace $ns is being deleted (since ${QUERY_RESULT#deleting }); rerun the audit once it is gone" ;;
  esac

  check_json_list \
    "pods in $ns" \
    "no pods in $ns" \
    "$STUCK_JQ .items[] | .metadata.name + \" (\" + (.status.phase // \"unknown\") + (if stuck then \", deleting since \" + .metadata.deletionTimestamp else \"\" end) + \")\"" \
    oc get pods -n "$ns"

  collect_per_kind \
    "Rook objects in $ns" \
    ".items[] | select(.metadata.name | test(\"$name_re\")) | (.kind // \"object\") + \"/\" + .metadata.name" \
    $'deployments\ndaemonsets\nstatefulsets\nservices\nserviceaccounts\nroles\nrolebindings\npoddisruptionbudgets\njobs\ncronjobs' \
    -n "$ns" || complete=0

  # ConfigMaps and Secrets by name only, never their data.
  for resource in configmaps secrets; do
    case "$resource" in
      configmaps) kind=ConfigMap ;;
      *) kind=Secret ;;
    esac
    if ! list_names "$resource" "$ns" "Rook residue"; then
      complete=0
      continue
    fi
    while IFS=$'\t' read -r name finalizers; do
      if [ -n "$name" ] && [[ $name =~ $name_re ]]; then
        COLLECTED="${COLLECTED:+$COLLECTED$'\n'}$kind/$name${finalizers:+ (finalizers: $finalizers)}"
      fi
    done <<<"$NAMES_OUT"
  done
  report_collected "Rook objects in $ns" "no Rook objects in $ns" "$complete"
}

# Namespace is the one kind with a real Terminating phase. A consumer namespace that
# held Rook bucket claims stays there while its objects keep objectbucket.io/finalizer.
# Every Terminating namespace is remembered for check_bucket_finalizers; only those
# deleting for longer than the threshold are reported.
TERMINATING_NAMESPACES=""
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

# ceph.rook.io, csi.ceph.io and objectbucket.io are shared with ODF. With ODF present
# their CRDs stay, and only instances in the Rook namespace (or, for cluster-scoped
# kinds, named with the Rook driver prefix) are Rook residue. Without ODF the CRDs
# themselves are residue, and every instance left holds them. Bucket claims and
# buckets are decided by their StorageClass instead (check_object_buckets).
check_shared_group() {
  local group="$1"
  local all_kinds
  local namespaced
  local kind
  local ns_kinds=""
  local cluster_kinds=""
  local found
  local complete=1
  local describe='(.kind // "object") + "/" + (if .metadata.namespace then .metadata.namespace + "/" else "" end) + .metadata.name + (if .metadata.deletionTimestamp then " (deleting, finalizers: " + ((.metadata.finalizers // []) | join(",")) + ")" else "" end)'

  api_resources "$group" || return 0
  if [ -z "$API_RESOURCES" ]; then
    ok "no $group API resources found"
    return 0
  fi
  all_kinds="$API_RESOURCES"
  api_resources "$group" --namespaced=true || return 0
  namespaced=$'\n'"$API_RESOURCES"$'\n'
  while IFS= read -r kind; do
    case "$kind" in
      ""|objectbucketclaims.objectbucket.io|objectbuckets.objectbucket.io) continue ;;
    esac
    if [[ $namespaced == *$'\n'"$kind"$'\n'* ]]; then
      ns_kinds="${ns_kinds:+$ns_kinds$'\n'}$kind"
    else
      cluster_kinds="${cluster_kinds:+$cluster_kinds$'\n'}$kind"
    fi
  done <<<"$all_kinds"

  if odf_present; then
    ok "$group API resources retained: ODF uses them"
    collect_per_kind "$group objects" ".items[] | $describe" "$ns_kinds" -n "$ROOK_NAMESPACE" || complete=0
    found="$COLLECTED"
    collect_per_kind "$group objects" \
      ".items[] | select(.metadata.name | startswith(\"$ROOK_CSI_PREFIX.\") or startswith(\"$ROOK_CSI_PREFIX-\")) | $describe" \
      "$cluster_kinds" || complete=0
    COLLECTED="${found:+$found${COLLECTED:+$'\n'}}$COLLECTED"
    report_collected \
      "$group objects of Rook (in $ROOK_NAMESPACE, or cluster-scoped and named $ROOK_CSI_PREFIX.*)" \
      "no $group objects of Rook" \
      "$complete"
    return 0
  fi

  warn "$group API resources still exist:"
  echo "$all_kinds"
  collect_per_kind "$group objects" ".items[] | $describe" "$ns_kinds"$'\n'"$cluster_kinds" -A || complete=0
  report_collected \
    "$group objects (they keep the CRDs; see Orphans After An Interrupted Uninstall)" \
    "no $group objects in any namespace" \
    "$complete"
}

# jq: whose the bucket object (its storage class name in .sc) is: "rook" when its
# class uses the Rook bucket provisioner, "odf" when an ODF one, "other" for any
# other provisioner. A class that is gone is "rook" when no ODF runs; next to ODF
# an ODF claim may have outlived its class too, so it is "unknown". $classes maps
# StorageClass name to provisioner.
ROOK_BUCKET_JQ="def bucket_owner(\$classes; \$odf): (\$classes[.sc // \"\"] // null) as \$p
  | if \$p == null then (if \$odf then \"unknown\" else \"rook\" end)
    elif (\$p | test(\"$ROOK_BUCKET_PROVISIONER_RE\")) then \"rook\"
    elif (\$p | test(\"$ODF_BUCKET_PROVISIONER_RE\")) then \"odf\" else \"other\" end;
def describe(\$classes): \"(class \(.sc // \"none\"): \(\$classes[.sc // \"\"] // \"missing\"))\";"

BUCKET_CLASSES=""
BUCKET_CLAIMS=""
check_object_buckets() {
  local buckets
  local odf=false

  if odf_present; then
    odf=true
  fi
  fetch_array "StorageClasses" \
    '[[.items[] | {key: .metadata.name, value: .provisioner}] | from_entries]' \
    oc get sc || return 0
  BUCKET_CLASSES="$QUERY_RESULT"
  fetch_array "ObjectBucketClaims" \
    '[.items[] | {ns: .metadata.namespace, name: .metadata.name, sc: .spec.storageClassName}]' \
    oc get objectbucketclaims.objectbucket.io -A || return 0
  BUCKET_CLAIMS="$QUERY_RESULT"
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    # check_bucket_finalizers still runs: a claim's ConfigMap and Secret keep
    # objectbucket.io/finalizer after the CRDs are gone, with no claim left at all.
    ok "no ObjectBucketClaims or ObjectBuckets (resource type not served)"
    return 0
  fi
  fetch_array "ObjectBuckets" \
    '[.items[] | {name: .metadata.name, sc: .spec.storageClassName}]' \
    oc get objectbuckets.objectbucket.io || return 0
  buckets="$QUERY_RESULT"

  check_docs_list \
    "Rook ObjectBucketClaims" \
    "no Rook ObjectBucketClaims found" \
    "$ROOK_BUCKET_JQ (.[0][0] // {}) as \$classes | .[1][] | select(bucket_owner(\$classes; $odf) == \"rook\") | \"\(.ns)/\(.name) \" + describe(\$classes)" \
    "$BUCKET_CLASSES" "$BUCKET_CLAIMS"

  echo
  check_docs_list \
    "Rook ObjectBuckets" \
    "no Rook ObjectBuckets found" \
    "$ROOK_BUCKET_JQ (.[0][0] // {}) as \$classes | .[1][] | select(bucket_owner(\$classes; $odf) == \"rook\") | \"\(.name) \" + describe(\$classes)" \
    "$BUCKET_CLASSES" "$buckets"

  echo
  check_docs_list \
    "bucket claims and buckets of unknown owner (StorageClass gone while ODF is present; review by hand)" \
    "no bucket claims or buckets of unknown owner" \
    "$ROOK_BUCKET_JQ (.[0][0] // {}) as \$classes
      | (.[1][] | select(bucket_owner(\$classes; $odf) == \"unknown\") | \"ObjectBucketClaim \(.ns)/\(.name) \" + describe(\$classes)),
        (.[2][] | select(bucket_owner(\$classes; $odf) == \"unknown\") | \"ObjectBucket \(.name) \" + describe(\$classes))" \
    "$BUCKET_CLASSES" "$BUCKET_CLAIMS" "$buckets"
}

# A claim's ConfigMap and Secret carry objectbucket.io/finalizer too; once the
# provisioner is gone they hold their namespace in Terminating. Every claim that is
# not Rook's (ODF's, another provisioner's, or of unknown owner) counts as live.
# Only the Rook namespace and Terminating namespaces are read, and only names and
# finalizers (list_names).
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
  local odf=false

  if [ -z "$BUCKET_CLASSES" ] || [ -z "$BUCKET_CLAIMS" ]; then
    return 0
  fi
  if odf_present; then
    odf=true
  fi
  run_split jq_slurp \
    "$ROOK_BUCKET_JQ (.[0][0] // {}) as \$classes | .[1][] | select(bucket_owner(\$classes; $odf) != \"rook\") | \"\(.ns)/\(.name)\"" \
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
      if ! list_names "$resource" "$ns" "objectbucket.io/finalizer"; then
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
      done <<<"$NAMES_OUT"
    done
  done <<<"$ROOK_NAMESPACE"$'\n'"$TERMINATING_NAMESPACES"

  if [ -n "$found" ]; then
    warn "ConfigMaps and Secrets held by objectbucket.io/finalizer without a live claim still exist:"
    echo "$found"
  elif [ "$incomplete" -eq 0 ]; then
    ok "no ConfigMaps or Secrets held by objectbucket.io/finalizer without a live claim (checked $ROOK_NAMESPACE and Terminating namespaces)"
  fi
}

# The rook-ceph and rook-ceph-csi SCCs are judged by who may use them, not by name:
# ODF ships SCCs with the same names. Every user a service account of the Rook
# namespace (and every group its service-account group) is Rook's, residue; every
# one in openshift-storage is ODF's, retained; anything else needs a decision.
check_sccs() {
  local name
  local owner
  local who

  query_json \
    "SCCs" \
    "def who: if test(\"^system:serviceaccount:$ROOK_NAMESPACE:[^:]+\$\") or . == \"system:serviceaccounts:$ROOK_NAMESPACE\" then \"rook\"
       elif test(\"^system:serviceaccount:openshift-storage:[^:]+\$\") or . == \"system:serviceaccounts:openshift-storage\" then \"odf\"
       else \"other\" end;
     .items[] | select(.metadata.name == \"rook-ceph\" or .metadata.name == \"rook-ceph-csi\")
     | ((.users // []) + (.groups // [])) as \$all
     | ([\$all[] | who] | unique) as \$owners
     | [.metadata.name,
        (if (\$all | length) == 0 then \"empty\" elif \$owners == [\"rook\"] then \"rook\" elif \$owners == [\"odf\"] then \"odf\" else \"mixed\" end),
        (\$all | join(\" \"))]
     | @tsv" \
    oc get scc || return 0
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    ok "no rook-ceph or rook-ceph-csi SCC (resource type not served)"
    return 0
  fi
  if [ -z "$QUERY_RESULT" ]; then
    ok "no rook-ceph or rook-ceph-csi SCC found"
    return 0
  fi
  while IFS=$'\t' read -r name owner who; do
    case "$owner" in
      rook) warn "SCC $name is Rook residue: every user is a service account in $ROOK_NAMESPACE ($who)" ;;
      odf) ok "SCC $name retained: every user is a service account in openshift-storage, so it is ODF's" ;;
      empty) warn "SCC $name has no users or groups, so its owner cannot be told from the SCC - decide by hand" ;;
      *) warn "SCC $name has users outside $ROOK_NAMESPACE - decide by hand before removing it: $who" ;;
    esac
  done <<<"$QUERY_RESULT"
}

# Cluster RBAC from the Rook install: ClusterRoles and ClusterRoleBindings named like
# Rook's, plus ClusterRoleBindings with a ServiceAccount subject in the Rook
# namespace. Upstream Rook is not installed by OLM, so a candidate carrying
# olm.owner or operators.coreos.com/* labels is not Rook's (ODF names some of its
# objects rook-ceph-*): it is reported with that operator, installed or not. Every
# other candidate is classified by liveness, because a name proves nothing:
# - a ClusterRoleBinding is dead when its ClusterRole is missing (even with a
#   User/Group subject), or when it has no User/Group subject (those cannot be
#   proven absent) and none of its ServiceAccount subjects exists. A binding of
#   rook-ceph-metrics whose only live subject is openshift-monitoring/prometheus-k8s
#   is dead too once no Ceph runs: that ServiceAccount exists on every OpenShift
#   cluster, so it proves nothing. While upstream Rook, ODF, or a Ceph object of
#   unknown owner remains (or ownership could not be classified), it is kept;
# - a ClusterRole is dead when no live ClusterRoleBinding or RoleBinding references
#   it (a dead binding does not keep its role alive) and no other ClusterRole's
#   aggregationRule selects it. A selector is evaluated in full, matchLabels and
#   matchExpressions (In, NotIn, Exists, DoesNotExist). An empty one ({}) selects
#   every ClusterRole: Kubernetes reads a non-nil empty label selector as
#   "everything". One that cannot be evaluated keeps the role, never kills it.
# shellcheck disable=SC2016 # jq variables
ROOK_RBAC_JQ='
def expr_result($labels):
  . as $e
  | if ($e | type) != "object" or ($e.key | type) != "string" then "error"
    elif $e.operator == "Exists" then ($labels | has($e.key))
    elif $e.operator == "DoesNotExist" then ($labels | has($e.key) | not)
    elif ($e.values | type) != "array" then "error"
    elif $e.operator == "In" then (($labels | has($e.key)) and any($e.values[]; . == $labels[$e.key]))
    elif $e.operator == "NotIn" then (($labels | has($e.key) | not) or all($e.values[]; . != $labels[$e.key]))
    else "error" end;
def selector_result($labels):
  if type != "object" then "error"
  else (.matchLabels // {}) as $ml | (.matchExpressions // []) as $me
    | if ($ml | type) != "object" or ($me | type) != "array" then "error"
      elif ($ml | length) == 0 and ($me | length) == 0 then "all"
      else [($ml | to_entries[] | $labels[.key] == .value), ($me[] | expr_result($labels))]
        | if any(.[]; . == "error") then "error" else all(.[]; . == true) end
      end
  end;
def rook_named: .name | test("^(rook-ceph|rbd-csi|rbd-external|cephfs-csi|cephfs-external|ceph-csi|objectstorage-provisioner)");
def olm_owner($csvs; $subs):
  .labels as $l
  | if ($l["olm.owner"] // null) != null then
      ($l["olm.owner.namespace"] // "") as $ns | $l["olm.owner"] as $csv
      | {by: "CSV \($csv)", installed: any($csvs[]; . == "\($ns)/\($csv)" or ($ns == "" and endswith("/\($csv)")))}
    elif any($l | keys[]; startswith("operators.coreos.com/")) then
      ([$l | keys[] | select(startswith("operators.coreos.com/")) | ltrimstr("operators.coreos.com/")][0]) as $k
      | (($k | capture("^(?<pkg>.+)[.](?<ns>[^.]+)$")) // {pkg: $k, ns: ""}) as $p
      | {by: "package \($p.pkg)", installed: any($subs[]; . == "\($p.ns)/\($p.pkg)")}
    else null end;
def olm_line($ref; $csvs; $subs):
  olm_owner($csvs; $subs) as $o
  | if $o.installed then ["kept", $ref, "carries OLM labels of installed operator \($o.by); not Rook residue"]
    else ["notrook", $ref, "carries OLM labels of \($o.by), which is not installed; not Rook residue (another operator left it)"] end;
def live_sas($sas):
  [.subjects[] | select(.kind == "ServiceAccount") | "\(.namespace)/\(.name)" | select($sas[.] // false)];
def verdict($roles; $sas; $ceph_runs):
  if ($roles[.role] // false) | not then {live: false, why: "its ClusterRole \(.role) is missing"}
  elif any(.subjects[]; .kind == "User" or .kind == "Group") then {live: true, why: "has a User/Group subject, which cannot be proven absent"}
  elif ($ceph_runs | not) and .role == "rook-ceph-metrics" and live_sas($sas) == ["openshift-monitoring/prometheus-k8s"]
    then {live: false, why: "only the platform ServiceAccount openshift-monitoring/prometheus-k8s remains, which is not a Ceph consumer"}
  elif (live_sas($sas) | length) > 0 then {live: true, why: "bound to live ServiceAccount \(live_sas($sas) | join(", "))"}
  else {live: false, why: "none of its ServiceAccount subjects exists"} end;
.[0] as $crs | .[1] as $crbs | .[2] as $rbs | .[4] as $csvs | .[5] as $subs | .[6] as $rookns | .[7] as $ceph_runs
| (.[3] | map({key: ., value: true}) | from_entries) as $sas
| ($crs | map({key: .name, value: true}) | from_entries) as $roles
| ([$crbs[] | . + {ref: "ClusterRoleBinding/\(.name)",
                   candidate: (rook_named or any(.subjects[]; .kind == "ServiceAccount" and .namespace == $rookns)),
                   olm: (olm_owner($csvs; $subs) != null)}]
   + [$rbs[] | . + {ref: "RoleBinding \(.ns)/\(.name)", candidate: false, olm: false}]
   | map(. + verdict($roles; $sas; $ceph_runs))) as $bindings
| ($bindings[] | select(.candidate)
   | if .olm then olm_line(.ref; $csvs; $subs)
     else [(if .live then "kept" else "dead" end), .ref, .why] end
   | @tsv),
  ($crs[] | select(rook_named) | . as $role
   | if olm_owner($csvs; $subs) != null then olm_line("ClusterRole/\(.name)"; $csvs; $subs)
     else
       [$bindings[] | select(.role == $role.name)] as $refs
       | [$refs[] | select(.live) | .ref] as $live_refs
       | [$crs[] | select(.name != $role.name) | .name as $into | .selectors[]
          | {into: $into, result: selector_result($role.labels)}] as $selected
       | [$selected[] | select(.result == "all") | .into] as $all_rules
       | if ($live_refs | length) > 0 then ["kept", "ClusterRole/\(.name)", "referenced by live \($live_refs | join(", "))"]
         elif ($all_rules | length) > 0 then ["kept", "ClusterRole/\(.name)", "aggregated by a select-all rule into \($all_rules | join(", "))"]
         elif any($selected[]; .result == true) then ["kept", "ClusterRole/\(.name)", "aggregated into \([$selected[] | select(.result == true) | .into] | join(", "))"]
         elif any($selected[]; .result == "error") then ["kept", "ClusterRole/\(.name)", "aggregation selector could not be evaluated"]
         elif ($refs | length) > 0 then ["dead", "ClusterRole/\(.name)", "referenced only by dead \([$refs[].ref] | join(", "))"]
         else ["dead", "ClusterRole/\(.name)", "no binding references it"] end
     end
   | @tsv)
'

check_cluster_rbac() {
  local roles
  local cluster_bindings
  local bindings
  local accounts
  local ceph_runs
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

  ceph_runs=true
  if [ "$CEPH_CLASSIFIED" -eq 1 ] && [ -z "$ROOK_LIVE" ] && [ -z "$CEPH_UNKNOWN" ] && ! odf_present; then
    ceph_runs=false
  fi
  run_split jq_slurp "$ROOK_RBAC_JQ" "$roles" "$cluster_bindings" "$bindings" "$accounts" \
    "$CSVS_JSON" "$SUBSCRIPTIONS_JSON" "\"$ROOK_NAMESPACE\"" "$ceph_runs"
  if [ "$RUN_RC" -ne 0 ]; then
    fail "Rook cluster RBAC jq filter failed: $RUN_ERR"
    return 0
  fi

  while IFS=$'\t' read -r verdict object reason; do
    case "$verdict" in
      kept) ok "$object retained: $reason" ;;
      notrook) ok "$object: $reason" ;;
      dead) dead="${dead}${object}: ${reason}"$'\n' ;;
    esac
  done <<<"$RUN_OUT"

  if [ -n "$dead" ]; then
    warn "dead Rook cluster RBAC still exists:"
    printf '%s' "$dead"
  else
    ok "no dead Rook ClusterRoles or ClusterRoleBindings found"
  fi
}

# MachineConfigs are reported, never judged: removing one reboots nodes, and
# whether a Rook-era one is still needed is a decision (MachineConfig Cleanup).
check_machineconfigs() {
  local name

  query_json "MachineConfigs" '.items[] | select(.metadata.name | test("rook"; "i")) | .metadata.name' \
    oc get machineconfigs || return 0
  if [ "$QUERY_NOT_FOUND" -eq 1 ]; then
    ok "no MachineConfigs named for Rook (resource type not served)"
  elif [ -z "$QUERY_RESULT" ]; then
    ok "no MachineConfigs named for Rook"
  else
    while IFS= read -r name; do
      if [ -n "$name" ]; then
        ok "MachineConfig $name is named for Rook: report only; decide by hand (see MachineConfig Cleanup)"
      fi
    done <<<"$QUERY_RESULT"
  fi
}

echo "=== Rook Ceph Post-Uninstall Audit ==="

require_command oc || exit 1
require_command jq || exit 1

# Route every `oc` below through the parsed global args. Defined after
# require_command so that check still tests for the binary, not this function.
# shellcheck disable=SC2317,SC2329 # invoked through run_split, query_json, and collect_per_kind
oc() { command oc "${OC_GLOBAL_ARGS[@]}" "$@"; }

run_split oc whoami
if [ "$RUN_RC" -ne 0 ]; then
  fail "unable to contact the cluster with oc whoami: $RUN_ERR"
  exit 1
fi

# Name the cluster that was audited. Without this an audit of the wrong context
# reads exactly like an audit of the right one. The server URL is authoritative;
# the context label is only what was asked for.
run_split oc whoami --show-server
echo "auditing ${RUN_OUT:-unknown server}${OC_CONTEXT_LABEL:+ (context: $OC_CONTEXT_LABEL)}" \
  "for Rook in $ROOK_NAMESPACE, CSI driver prefix $ROOK_CSI_PREFIX"

detect_ownership
check_ownership

echo
check_rook_namespace

echo
check_terminating_namespaces

echo
check_shared_group ceph.rook.io
check_shared_group csi.ceph.io
check_shared_group objectbucket.io

echo
check_json_list \
  "Rook StorageClasses" \
  "no Rook StorageClasses found" \
  ".items[] | select((.provisioner // \"\") | test(\"$ROOK_PROVISIONER_RE\")) | .metadata.name + \" (\" + .provisioner + \")\"" \
  oc get sc

echo
check_json_list \
  "Rook PVs" \
  "no Rook PVs found" \
  ".items[] | select((.spec.csi.driver // \"\") | test(\"$ROOK_CSI_DRIVER_RE\")) | .metadata.name + \" (class \" + (.spec.storageClassName // \"none\") + \", phase \" + (.status.phase // \"unknown\") + \")\"" \
  oc get pv

# A PVC is Rook's when its class uses a Rook provisioner or it is bound to a Rook
# PV; the class name itself proves nothing.
echo
if fetch_array "Rook StorageClasses" \
     "[[.items[] | select((.provisioner // \"\") | test(\"$ROOK_PROVISIONER_RE\")) | {key: .metadata.name, value: true}] | from_entries]" \
     oc get sc; then
  ROOK_CLASSES="$QUERY_RESULT"
  if fetch_array "Rook PVs" \
       "[[.items[] | select((.spec.csi.driver // \"\") | test(\"$ROOK_CSI_DRIVER_RE\")) | {key: .metadata.name, value: true}] | from_entries]" \
       oc get pv; then
    ROOK_VOLUMES="$QUERY_RESULT"
    if fetch_array "PersistentVolumeClaims" '[.items[]]' oc get pvc -A; then
      # shellcheck disable=SC2016 # jq variables
      check_docs_list \
        "Rook PVCs" \
        "no Rook PVCs found" \
        '(.[0][0] // {}) as $sc | (.[1][0] // {}) as $pv | .[2][]
          | select(($sc[.spec.storageClassName // ""] // false) or ($pv[.spec.volumeName // ""] // false))
          | .metadata.namespace + "/" + .metadata.name' \
        "$ROOK_CLASSES" "$ROOK_VOLUMES" "$QUERY_RESULT"
    fi
  fi
fi

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
  "Rook VolumeSnapshotClasses" \
  "no Rook VolumeSnapshotClasses found" \
  ".items[] | select((.driver // \"\") | test(\"$ROOK_CSI_DRIVER_RE\")) | .metadata.name + \" (\" + .driver + \")\"" \
  oc get volumesnapshotclasses

echo
check_json_list \
  "Rook VolumeAttachments" \
  "no Rook VolumeAttachments found" \
  ".items[] | select((.spec.attacher // \"\") | test(\"$ROOK_CSI_DRIVER_RE\")) | .metadata.name + \" (pv \" + (.spec.source.persistentVolumeName // \"none\") + \", attached \" + (.status.attached // false | tostring) + \", finalizers: \" + ((.metadata.finalizers // []) | join(\",\")) + \")\"" \
  oc get volumeattachments

echo
check_json_list \
  "Rook CSIDrivers" \
  "no Rook CSIDrivers found" \
  ".items[] | select(.metadata.name | test(\"$ROOK_CSI_DRIVER_RE\")) | .metadata.name" \
  oc get csidrivers

echo
check_json_list \
  "Rook CSI drivers registered on nodes (CSINode)" \
  "no node registers a Rook CSI driver" \
  ".items[] | .metadata.name as \$node | .spec.drivers[]? | select(.name | test(\"$ROOK_CSI_DRIVER_RE\")) | \$node + \": \" + .name" \
  oc get csinodes

# A Pod whose CSI driver was removed first can never be unmounted, so the kubelet
# keeps it (and, through pvc-protection, its PVC) with deletionTimestamp set forever.
echo
check_json_list \
  "pods deleting $STUCK_NOTE (any namespace)" \
  "no pods deleting $STUCK_NOTE" \
  "$STUCK_JQ .items[] | select(stuck) | .metadata.namespace + \"/\" + .metadata.name + \" (\" + (.status.phase // \"unknown\") + \", node \" + (.spec.nodeName // \"none\") + \", deleting since \" + .metadata.deletionTimestamp + \")\"" \
  oc get pods -A

echo
check_object_buckets

echo
check_bucket_finalizers

echo
check_sccs

echo
check_absent_resource \
  "PriorityClass rook-ceph-default" \
  "PriorityClass rook-ceph-default absent" \
  priorityclasses rook-ceph-default

echo
check_cluster_rbac

echo
check_machineconfigs

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
