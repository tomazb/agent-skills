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

# Who runs Ceph, by the same rule as the ownership gate in SKILL.md. Input, slurped
# in this order: the `-o json` lists of cephclusters.ceph.rook.io (-A), the
# rook-ceph-operator Deployments (-A), drivers.csi.ceph.io (-A), csidrivers, and
# persistentvolumes. Output, one tab-separated line each:
#   upstream <namespace> <live CephCluster names there, or "none">
#   residue  <namespace>/<name> <reason>
#   unknown  <object> <reason>
# Only rook-ceph-operator Deployments outside openshift-storage that are not being
# deleted are considered. One that OLM did not install (no olm.owner label, no
# operators.coreos.com/ label) is an upstream Rook operator; existence, not
# readiness, is the test, because an operator scaled to zero for maintenance still
# owns its cluster. One that OLM did install cannot be told apart from a community
# Rook bundle here, so it is unknown.
# A CephCluster with an ODF signal (in openshift-storage, owned by a StorageCluster,
# named like ODF's) is residue; so is one being deleted while an upstream operator
# exists. Every other CephCluster belongs to upstream Rook when a non-OLM operator
# exists anywhere outside openshift-storage (Rook watches every namespace by
# default, so the operator may live elsewhere), and is unknown otherwise (renamed,
# OLM-installed, or absent operator).
# With no upstream operator, a non-ODF Ceph CSI that outlived its operator — a
# drivers.csi.ceph.io object outside openshift-storage, a *.csi.ceph.com CSIDriver
# without the openshift-storage. prefix, or a PV on such a driver — may still serve
# mounted volumes, so it is unknown too. Any unknown line means the caller must
# not decide.
# Known limitation: an upstream Rook installed inside openshift-storage reads as ODF.
# shellcheck disable=SC2016 # $clusters, $ops, $operators, $live are jq variables
ODF_CEPH_OWNERSHIP_JQ='
def olm_installed: (.metadata.labels // {}) | has("olm.owner") or any(keys[]; startswith("operators.coreos.com/"));
def foreign_ceph_csi: test("[.]csi[.]ceph[.]com$") and (startswith("openshift-storage.") | not);
def odf_signal:
  if .metadata.namespace == "openshift-storage" then "in openshift-storage"
  elif any(.metadata.ownerReferences[]?; .kind == "StorageCluster") then "owned by a StorageCluster"
  elif (.metadata.name | test("^ocs-(external-)?storagecluster-cephcluster$")) then "carries the ODF CephCluster name"
  else empty end;
(.[0].items // []) as $clusters
| [(.[1].items // [])[]
   | select(.metadata.name == "rook-ceph-operator")
   | select(.metadata.namespace != "openshift-storage")
   | select(.metadata.deletionTimestamp == null)] as $ops
| ([$ops[] | select(olm_installed | not) | .metadata.namespace] | unique) as $operators
| def residue_reason:
    [odf_signal,
     (if .metadata.deletionTimestamp != null and ($operators | length) > 0 then "being deleted" else empty end)]
    | .[0] // empty;
  [$clusters[] | select([residue_reason] | length == 0)] as $live
| ($ops[] | select(olm_installed)
   | ["unknown", "\(.metadata.namespace)/rook-ceph-operator", "Deployment installed by OLM; cannot tell whether it is ODF or a Rook bundle"] | @tsv),
  (if ($operators | length) == 0 then
     ($live[] | ["unknown", "\(.metadata.namespace)/\(.metadata.name)", "no non-OLM rook-ceph-operator Deployment outside openshift-storage (renamed, OLM-installed, or absent operator)"] | @tsv),
     ((.[2].items // [])[] | select(.metadata.namespace != "openshift-storage")
      | ["unknown", "csi.ceph.io Driver \(.metadata.namespace)/\(.metadata.name)", "non-ODF Ceph CSI without a Rook operator; it may still serve mounted volumes"] | @tsv),
     ((.[3].items // [])[] | select(.metadata.name | foreign_ceph_csi)
      | ["unknown", "CSIDriver \(.metadata.name)", "non-ODF Ceph CSI driver without a Rook operator; it may still serve mounted volumes"] | @tsv),
     ((.[4].items // [])[] | select((.spec.csi.driver // "") | foreign_ceph_csi)
      | ["unknown", "PV \(.metadata.name)", "volume of non-ODF Ceph CSI driver \(.spec.csi.driver) without a Rook operator"] | @tsv)
   else
     (($operators + [$live[].metadata.namespace]) | unique | .[]) as $ns
     | ["upstream", $ns, ([$live[] | select(.metadata.namespace == $ns) | .metadata.name] | if length > 0 then join(",") else "none" end)] | @tsv
   end),
  ($clusters[] | [residue_reason] as $why | select(($why | length) > 0)
   | ["residue", "\(.metadata.namespace)/\(.metadata.name)", $why[0]] | @tsv)
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
