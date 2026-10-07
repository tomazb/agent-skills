# shellcheck shell=bash
# shellcheck disable=SC2034 # the constants are used by the scripts that source this file
#
# Shared definitions for the ODF helper scripts. Definitions only: no shell
# options, no exit, no oc wrapper. The uninstall runbook also sources this file
# into an interactive shell to reuse the same package list.
#
# Known limitation: everything here assumes ODF runs in the default
# openshift-storage namespace (its CSI driver and provisioner names carry that
# prefix). An ODF install in another namespace is not recognised.

# ODF component OLM packages, as one alternation. Every package match derives
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
ODF_PROVISIONER_RE='^openshift-storage[.]((rbd|cephfs)[.]csi[.]ceph[.]com|noobaa[.]io/obc|ceph[.]rook[.]io/bucket)$'

# Who runs Ceph. Input: the `oc get cephclusters.ceph.rook.io -A -o json` and
# `oc get deployments -A -o json` documents, slurped in that order. Output, one
# tab-separated line each:
#   upstream <namespace> <CephCluster names, or "none">
#   residue  <namespace>/<name> <reason>
# A namespace runs upstream Rook when it holds a rook-ceph-operator Deployment
# that OLM did not install (no olm.owner label, no operators.coreos.com/ label),
# that is not being deleted, outside openshift-storage. Existence, not readiness,
# is the test: an operator scaled to zero for maintenance still owns its cluster.
# A CephCluster is upstream Rook only in such a namespace, and only when it is not
# being deleted, has no StorageCluster owner, and does not carry ODF's name; any
# other CephCluster is residue. Known limitations: upstream Rook installed inside
# openshift-storage, and a Rook operator installed through OLM, read as ODF residue.
# shellcheck disable=SC2016 # $clusters, $operators, $ns are jq variables
ODF_CEPH_OWNERSHIP_JQ='
def olm_installed: (.metadata.labels // {}) | has("olm.owner") or any(keys[]; startswith("operators.coreos.com/"));
(.[0].items // []) as $clusters
| [(.[1].items // [])[]
   | select(.metadata.name == "rook-ceph-operator")
   | select(.metadata.namespace != "openshift-storage")
   | select(.metadata.deletionTimestamp == null)
   | select(olm_installed | not)
   | .metadata.namespace] | unique as $operators
| def residue_reason:
    if .metadata.namespace == "openshift-storage" then "in openshift-storage"
    elif any(.metadata.ownerReferences[]?; .kind == "StorageCluster") then "owned by a StorageCluster"
    elif (.metadata.name | test("^ocs-(external-)?storagecluster-cephcluster$")) then "carries the ODF CephCluster name"
    elif .metadata.deletionTimestamp != null then "being deleted"
    elif (.metadata.namespace as $ns | $operators | index($ns)) == null then "no upstream rook-ceph-operator Deployment in its namespace"
    else empty end;
  ($operators[] as $ns
   | [$clusters[] | select(.metadata.namespace == $ns) | select([residue_reason] | length == 0) | .metadata.name] as $names
   | ["upstream", $ns, (if ($names | length) > 0 then $names | join(",") else "none" end)] | @tsv),
  ($clusters[] | [residue_reason] as $why | select(($why | length) > 0)
   | ["residue", "\(.metadata.namespace)/\(.metadata.name)", $why[0]] | @tsv)
'

is_not_found() {
  case "$1" in
    *NotFound*|*not\ found*|*the\ server\ doesn\'t\ have\ a\ resource\ type*) return 0 ;;
    *) return 1 ;;
  esac
}

is_forbidden() {
  case "$1" in
    *Forbidden*|*forbidden*) return 0 ;;
    *) return 1 ;;
  esac
}

# Run a command and keep its stdout, stderr, and exit status apart in RUN_OUT,
# RUN_ERR, and RUN_RC. Bash builtins only (no mktemp, no temp file): stderr is
# written first, then a NUL-separated record of stdout and the status follows on
# the same stream. A warning on stderr (client throttling, API deprecation) must
# not be read as part of the JSON on stdout.
run_split() {
  RUN_OUT=""
  RUN_ERR=""
  RUN_RC=""
  {
    IFS= read -r -d '' RUN_ERR || true
    IFS= read -r -d '' RUN_OUT || true
    IFS= read -r -d '' RUN_RC || true
  } < <( (printf '\0%s\0%d\0' "$("$@")" "$?" 1>&2) 2>&1 )
  RUN_RC="${RUN_RC:-1}"
}

# Run a jq filter over several JSON documents slurped into one array (.[0], .[1],
# ...). They go through stdin because cluster-wide lists exceed the per-argument
# size limit that --argjson would hit.
jq_slurp() {
  local jq_filter="$1"
  shift
  printf '%s\n' "$@" | jq -r -s "$jq_filter"
}

# Parse --context/--kubeconfig/--help into OC_GLOBAL_ARGS and OC_CONTEXT_LABEL.
# The caller defines usage(). Exits 2 on a bad argument.
parse_oc_args() {
  local value
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
        value="${1#*=}"
        [ -n "$value" ] || { echo "--kubeconfig requires a value" >&2; exit 2; }
        OC_GLOBAL_ARGS+=("--kubeconfig=$value"); shift ;;
      -h|--help)
        usage; exit 0 ;;
      *)
        echo "unknown argument: $1" >&2
        usage >&2
        exit 2 ;;
    esac
  done
}
