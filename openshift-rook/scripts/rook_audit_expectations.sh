# shellcheck shell=bash
# Definitions for target-bound, reviewed audit expectations. Never mutates resources.
# A reviewed inventory is bound to the target server and exact CRD UIDs.
# Labels alone never exempt resources; malformed/stale inventory fails the audit.
check_retained_objectbucket_inventory() {
  [ -n "${ROOK_RETAINED_OBJECTBUCKET_CRDS_FILE:-}" ] || return 0
  local inventory json expected
  inventory=$(jq -ce '
    select(type == "object" and (.apiServer | type == "string"))
    | select((.crds | type == "array") and (.crds | length > 0 and length <= 2))
    | select(all(.crds[]; (.name == "objectbucketclaims.objectbucket.io" or .name == "objectbuckets.objectbucket.io")
        and (.uid | type == "string" and length > 0)))
    | select(([.crds[].name] | unique | length) == (.crds | length))
    ' "$ROOK_RETAINED_OBJECTBUCKET_CRDS_FILE" 2>/dev/null) || {
    fail "invalid retained ObjectBucket CRD inventory"; return 1;
  }
  expected=$(jq -r '.apiServer' <<<"$inventory") || return 1
  if [ "$expected" != "$AUDIT_SERVER" ]; then
    fail "retained CRD inventory targets a different API server"; return 1
  fi
  run_split oc get crd -o json
  if [ "$RUN_RC" -ne 0 ]; then
    fail "retained CRD ownership lookup failed"; return 1
  fi
  json="$RUN_OUT"
  if ! jq -e --argjson inventory "$inventory" '
      .items as $live | all($inventory.crds[]; . as $expected |
        any($live[]; .metadata.name == $expected.name and .metadata.uid == $expected.uid
          and .metadata.deletionTimestamp == null and .spec.group == "objectbucket.io"
          and ((.metadata.labels // {}) |
               (((.["olm.owner"] // "") | type == "string" and length > 0)
                 and ((.["olm.owner.namespace"] // "") | type == "string" and length > 0))
               or any(keys[]; startswith("operators.coreos.com/")))))
      ' <<<"$json" >/dev/null 2>&1; then
    fail "retained CRD identity or OLM ownership is unverified"; return 1
  fi
  RETAINED_OBJECTBUCKET_KINDS=$(jq -r '.crds[].name' <<<"$inventory") || return 1
}

check_retained_objectbucket_group() {
  local all_kinds="$1" kind retained=1
  while IFS= read -r kind; do
    case $'\n'"$all_kinds"$'\n' in
      *$'\n'"$kind"$'\n'*) ;;
      *) fail "retained ObjectBucket API missing from discovery: $kind"; retained=0 ;;
    esac
  done <<<"$RETAINED_OBJECTBUCKET_KINDS"
  while IFS= read -r kind; do
    case $'\n'"$RETAINED_OBJECTBUCKET_KINDS"$'\n' in
      *$'\n'"$kind"$'\n'*) ;;
      *) retained=0 ;;
    esac
    if ! query_json "retained $kind instances" '.items | if type == "array" then length else error("malformed resource list") end' oc get "$kind" -A; then
      retained=0
    elif [ "$QUERY_NOT_FOUND" -ne 0 ] || [ "$QUERY_RESULT" != 0 ]; then
      fail "retained ObjectBucket API is unavailable or has instances: $kind"
      retained=0
    fi
  done <<<"$all_kinds"
  if [ "$retained" -eq 1 ]; then
    ok "objectbucket.io API resources retained: verified OLM-owned CRD inventory"
    return 0
  fi
  return 1
}
