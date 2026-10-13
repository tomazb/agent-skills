# shellcheck shell=bash
# shellcheck disable=SC2034 # the constants are used by the scripts that source this file
#
# Shared definitions for the Rook helper scripts. Definitions only: no shell
# options, no exit, no oc wrapper. The uninstall runbook also sources this file
# into an interactive shell to reuse the same patterns.
#
# Rook objects are matched by CSI driver, provisioner, and ownership, never by a
# "rook-ceph" name alone: ODF creates objects named rook-ceph-* as well.

# The Rook namespace and the CSI driver name prefix. Rook's CSI_DRIVER_NAME_PREFIX
# defaults to the operator namespace, so the prefix defaults to ROOK_NAMESPACE.
ROOK_NAMESPACE="rook-ceph"
ROOK_CSI_PREFIX=""

# ODF component OLM packages, as one alternation (the same list as openshift-odf).
# Known limitation: an OLM-installed Rook bundle whose package is named
# rook-ceph-operator reads as ODF; either way the classifier refuses.
ODF_PACKAGES='odf-operator|odf-dependencies|ocs-operator|ocs-client-operator|rook-ceph-operator|cephcsi-operator|mcg-operator|odf-csi-addons-operator|odf-external-snapshotter-operator|odf-prometheus-operator|ocs-tls-profiles|recipe'
ODF_PACKAGES_RE="^($ODF_PACKAGES)\$"
# CSV names are "<package>.v<version>". The literal dot is written [.] rather than
# \. : these strings are interpolated into jq string literals, where \. is an
# invalid escape and aborts the filter.
ODF_CSV_PREFIX_RE="^($ODF_PACKAGES)[.]"
ODF_BUCKET_PROVISIONER_RE='^openshift-storage[.](noobaa[.]io/obc|ceph[.]rook[.]io/bucket)$'

# Set the Rook driver and provisioner patterns from ROOK_NAMESPACE and
# ROOK_CSI_PREFIX. Both are interpolated into jq filters, so they are validated
# here: a namespace is a DNS label, a prefix a DNS subdomain. openshift-storage is
# refused for both: it is ODF's namespace and driver prefix, and accepting it would
# claim ODF's drivers, volumes, and SCCs as Rook's.
#   ROOK_CSI_DRIVER_RE          <prefix>.(rbd|cephfs|nfs|nvmeof).csi.ceph.com
#   ROOK_BUCKET_PROVISIONER_RE  <prefix>.ceph.rook.io/bucket
#   ROOK_PROVISIONER_RE         either of the above
#   ROOK_ATTACHER_FINALIZER_RE  external-attacher/<prefix with dots as dashes>-...
set_rook_patterns() {
  local label='^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
  local subdomain='^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$'
  if ! [[ $ROOK_NAMESPACE =~ $label ]]; then
    echo "invalid Rook namespace: $ROOK_NAMESPACE" >&2
    return 1
  fi
  ROOK_CSI_PREFIX="${ROOK_CSI_PREFIX:-$ROOK_NAMESPACE}"
  if ! [[ $ROOK_CSI_PREFIX =~ $subdomain ]]; then
    echo "invalid CSI driver prefix: $ROOK_CSI_PREFIX" >&2
    return 1
  fi
  if [ "$ROOK_NAMESPACE" = openshift-storage ] || [ "$ROOK_CSI_PREFIX" = openshift-storage ]; then
    echo "openshift-storage is ODF's namespace and CSI driver prefix, not Rook's - use the openshift-odf skill" >&2
    return 1
  fi
  local p="${ROOK_CSI_PREFIX//./[.]}"
  ROOK_CSI_DRIVER_RE="^${p}[.](rbd|cephfs|nfs|nvmeof)[.]csi[.]ceph[.]com\$"
  ROOK_BUCKET_PROVISIONER_RE="^${p}[.]ceph[.]rook[.]io/bucket\$"
  ROOK_PROVISIONER_RE="^${p}[.]((rbd|cephfs|nfs|nvmeof)[.]csi[.]ceph[.]com|ceph[.]rook[.]io/bucket)\$"
  ROOK_ATTACHER_FINALIZER_RE="^external-attacher/${ROOK_CSI_PREFIX//./-}-(rbd|cephfs|nfs|nvmeof)-csi-ceph-com\$"
}

# Who runs Ceph, seen from the Rook side. Input, slurped in this order: the
# `-o json` lists of cephclusters.ceph.rook.io (-A), the rook-ceph-operator
# Deployments (-A), storageclusters.ocs.openshift.io (-A), subscriptions (-A),
# clusterserviceversions (-A), drivers.csi.ceph.io (-A), csidrivers, and
# persistentvolumes, then ROOK_CSI_DRIVER_RE as a JSON string. Output, one
# tab-separated line each:
#   rook    <namespace> <live CephCluster names there, or "none">
#   odf     <object> <reason>
#   unknown <object> <reason>
# ODF is present when any of these exists: a StorageCluster; an ODF/OCS
# Subscription or CSV; a CephCluster in openshift-storage, owned by a StorageCluster,
# or named like ODF's; a rook-ceph-operator Deployment in openshift-storage; or a
# Ceph CSI driver, Driver object, or PV of ODF (openshift-storage. prefix, or a
# Driver in openshift-storage).
# A rook-ceph-operator Deployment outside openshift-storage that OLM did not install
# and that is not being deleted is an upstream Rook operator; existence, not
# readiness, is the test (an operator scaled to zero still owns its cluster). With
# such an operator every non-ODF CephCluster is upstream Rook (Rook watches every
# namespace by default); without one it is unknown. An OLM-installed
# rook-ceph-operator outside openshift-storage is unknown (a community Rook bundle
# and ODF look alike). A Ceph CSI driver, Driver object, or PV whose driver carries
# neither the Rook prefix nor ODF's is unknown: it may still serve mounted volumes.
# Any odf or unknown line means the caller must not delete anything shared.
# Known limitation: an upstream Rook installed inside openshift-storage reads as ODF.
# shellcheck disable=SC2016 # $clusters, $ops, $operators, $nonodf, $rookcsi are jq variables
ROOK_CEPH_OWNERSHIP_JQ='
def olm_installed: (.metadata.labels // {}) | has("olm.owner") or any(keys[]; startswith("operators.coreos.com/"));
def ceph_csi: test("[.]csi[.]ceph[.]com$");
def odf_signal:
  if .metadata.namespace == "openshift-storage" then "in openshift-storage"
  elif any(.metadata.ownerReferences[]?; .kind == "StorageCluster") then "owned by a StorageCluster"
  elif (.metadata.name | test("^ocs-(external-)?storagecluster-cephcluster$")) then "carries the ODF CephCluster name"
  else empty end;
.[8] as $rookcsi
| def csi_owner: if startswith("openshift-storage.") then "odf" elif test($rookcsi) then "rook" else "unknown" end;
  def csi_reason($o; $what): if $o == "odf" then "ODF Ceph CSI \($what)" else "Ceph CSI \($what) without the Rook driver prefix; it may still serve mounted volumes" end;
(.[0].items // []) as $clusters
| [(.[1].items // [])[]
   | select(.metadata.name == "rook-ceph-operator")
   | select(.metadata.deletionTimestamp == null)] as $ops
| ([$ops[] | select(.metadata.namespace != "openshift-storage") | select(olm_installed | not) | .metadata.namespace] | unique) as $operators
| [$clusters[] | select([odf_signal] | length == 0)] as $nonodf
| ((.[2].items // [])[] | ["odf", "StorageCluster \(.metadata.namespace)/\(.metadata.name)", "ODF storage cluster"]),
  ((.[3].items // [])[] | select((.spec.name // "") | test("'"$ODF_PACKAGES_RE"'"))
   | ["odf", "Subscription \(.metadata.namespace)/\(.metadata.name)", "ODF package \(.spec.name)"]),
  ((.[4].items // [])[] | select(.metadata.name | test("'"$ODF_CSV_PREFIX_RE"'"))
   | ["odf", "CSV \(.metadata.namespace)/\(.metadata.name)", "ODF ClusterServiceVersion"]),
  ($clusters[] | [odf_signal] as $why | select(($why | length) > 0)
   | ["odf", "CephCluster \(.metadata.namespace)/\(.metadata.name)", $why[0]]),
  ($ops[] | select(.metadata.namespace == "openshift-storage")
   | ["odf", "Deployment openshift-storage/rook-ceph-operator", "the Rook operator of ODF"]),
  ($ops[] | select(.metadata.namespace != "openshift-storage") | select(olm_installed)
   | ["unknown", "Deployment \(.metadata.namespace)/rook-ceph-operator", "installed by OLM; cannot tell whether it is ODF or a Rook bundle"]),
  (if ($operators | length) == 0 then
     ($nonodf[] | ["unknown", "CephCluster \(.metadata.namespace)/\(.metadata.name)", "no non-OLM rook-ceph-operator Deployment outside openshift-storage (renamed, OLM-installed, or absent operator)"])
   else empty end),
  ((.[5].items // [])[]
   | (if .metadata.namespace == "openshift-storage" then "odf" else (.metadata.name | csi_owner) end) as $o
   | select($o != "rook")
   | [$o, "csi.ceph.io Driver \(.metadata.namespace)/\(.metadata.name)", csi_reason($o; "Driver object")]),
  ((.[6].items // [])[] | select(.metadata.name | ceph_csi) | (.metadata.name | csi_owner) as $o
   | select($o != "rook")
   | [$o, "CSIDriver \(.metadata.name)", csi_reason($o; "driver")]),
  ((.[7].items // [])[] | (.spec.csi.driver // "") as $d | select($d | ceph_csi) | ($d | csi_owner) as $o
   | select($o != "rook")
   | [$o, "PV \(.metadata.name)", csi_reason($o; "volume (driver \($d))")]),
  (if ($operators | length) > 0 then
     (($operators + [$nonodf[].metadata.namespace]) | unique | .[]) as $ns
     | ["rook", $ns, ([$nonodf[] | select(.metadata.namespace == $ns) | .metadata.name] | if length > 0 then join(",") else "none" end)]
   else empty end)
| @tsv
'

# "No such resource": the server's NotFound, or no such resource type (the CRD is
# not installed). Client-side errors such as an unknown --context are not matched.
is_not_found() {
  case "$1" in
    *NotFound*|*the\ server\ doesn\'t\ have\ a\ resource\ type*) return 0 ;;
    *) return 1 ;;
  esac
}

# Only "the CRD is not installed"; nothing else means "there are none".
is_missing_resource_type() {
  case "$1" in
    *the\ server\ doesn\'t\ have\ a\ resource\ type*) return 0 ;;
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
# RUN_ERR, and RUN_RC. Bash builtins only (no mktemp, no temp file). A warning on
# stderr (client throttling, API deprecation) must not be read as part of the JSON
# on stdout. stdout and the status go out first as NUL-terminated fields on fd 3;
# stderr is captured into a variable, which drops any NUL byte in it, and sent last,
# so a NUL in either stream cannot shift the fields.
run_split() {
  RUN_OUT=""
  RUN_ERR=""
  RUN_RC=""
  {
    IFS= read -r -d '' RUN_OUT || true
    IFS= read -r -d '' RUN_RC || true
    IFS= read -r -d '' RUN_ERR || true
  } < <(
    exec 3>&1
    { err=$( { out=$("$@"); rc=$?; printf '%s\0%d\0' "$out" "$rc" >&3; } 2>&1 ); } 2>/dev/null
    printf '%s\0' "$err"
  )
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

# Parse --context/--kubeconfig/--namespace/--csi-prefix/--help into
# OC_GLOBAL_ARGS, OC_CONTEXT_LABEL, ROOK_NAMESPACE, and ROOK_CSI_PREFIX. The
# caller defines usage(). Exits 2 on a bad argument.
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
      --namespace|--csi-prefix)
        if [ "$#" -lt 2 ] || [ -z "$2" ]; then echo "$1 requires a value" >&2; exit 2; fi
        if [ "$1" = --namespace ]; then ROOK_NAMESPACE="$2"; else ROOK_CSI_PREFIX="$2"; fi
        shift 2 ;;
      --namespace=*|--csi-prefix=*)
        value="${1#*=}"
        [ -n "$value" ] || { echo "${1%%=*} requires a value" >&2; exit 2; }
        if [ "${1%%=*}" = --namespace ]; then ROOK_NAMESPACE="$value"; else ROOK_CSI_PREFIX="$value"; fi
        shift ;;
      -h|--help)
        usage; exit 0 ;;
      *)
        echo "unknown argument: $1" >&2
        usage >&2
        exit 2 ;;
    esac
  done
  set_rook_patterns || exit 2
}
