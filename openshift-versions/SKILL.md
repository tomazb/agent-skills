---
name: openshift-versions
description: Query Red Hat OpenShift versions via api.openshift.com. Use when users ask about available OpenShift versions, latest patch versions, upgrade paths, ROSA/OSD versions, or channel-specific releases. Supports the public upgrades_info graph endpoint (no auth) and the authenticated clusters_mgmt versions endpoint. Also use when the user asks "what OCP versions exist", "what can I upgrade to", "latest OCP patch", "is 4.x still supported", or any question about OpenShift release availability, upgrade targets, or end-of-life dates — even if they don't name a specific version number.
---

# OpenShift Versions Skill

Query OpenShift Container Platform versions from Red Hat's public APIs.
**No version numbers are hardcoded.** All examples use dynamic discovery so the skill stays current as new OCP minors ship.

## IMPORTANT — Version-Agnostic Workflow

**Never assume which OCP minor versions currently exist.** Always discover them at runtime:

1. Run `--discover` or `--all-latest` first to see what's active right now
2. Then drill into specific channels or upgrade paths based on the results
3. Use `{MAJOR}.{MINOR}` placeholders when explaining commands to the user — fill them in from discovery output

## Choose Your Endpoint

**Public (no auth required):**
- Latest patch discovery via `--all-latest`
- Upgrade-path validation via `--upgrade-path`
- Real-time patch availability, which often appears here before the authenticated endpoint
- CI/CD and automation contexts where you do not want to manage tokens

**Authenticated (requires OCM token):**
- EOL dates and lifecycle metadata
- ROSA and HCP eligibility checks
- Marketplace availability and deployment flags
- Full version inventory with filtering and pagination

## API Endpoints

| Endpoint | Auth | Use Case |
|----------|------|----------|
| `/api/upgrades_info/v1/graph` | **No** | Versions, upgrade paths by channel |
| `/api/clusters_mgmt/v1/versions` | Yes (OAuth) | Detailed metadata, ROSA/HCP flags, EOL |

## Quick Start (No Authentication)

### 1. Discover What's Available

```bash
# Find all active minor versions in the stable channel
python3 scripts/query_versions.py --discover

# Same for EUS channel
python3 scripts/query_versions.py --discover --channel-type eus

# One-liner: latest patch for every active minor
python3 scripts/query_versions.py --all-latest

# Narrow the scan range (e.g., only check 4.14–4.18)
python3 scripts/query_versions.py --discover --floor 14 --ceiling 18

# ARM64
python3 scripts/query_versions.py --all-latest --arch arm64
```

### 2. Query a Specific Channel

Once you know which minors are active, drill in:

```bash
# Latest patch in a specific channel (substitute actual minor from discovery)
python3 scripts/query_versions.py --channel stable-{MAJOR}.{MINOR} --latest

# All versions in a channel
python3 scripts/query_versions.py --channel stable-{MAJOR}.{MINOR}

# Candidate channel for pre-release
python3 scripts/query_versions.py --channel candidate-{MAJOR}.{MINOR} --latest
```

### 3. Upgrade Paths

Given a running version, find all valid one-hop upgrade targets:

```bash
# Check stable channel for upgrade targets
python3 scripts/query_versions.py --upgrade-path {FULL_VERSION}

# Check multiple channels (stable + EUS)
python3 scripts/query_versions.py --upgrade-path {FULL_VERSION} --channel-type stable,eus

# ARM64 upgrade targets
python3 scripts/query_versions.py --upgrade-path {FULL_VERSION} --arch arm64
```

The script checks both the same-minor and next-minor channels for cross-minor upgrade edges.

### Raw curl (no script)

```bash
# Discovery via curl: probe a channel, extract versions
curl -s "https://api.openshift.com/api/upgrades_info/v1/graph?channel=stable-{MAJOR}.{MINOR}&arch=amd64" \
  | jq -r '.nodes[].version' | sort -V

# Latest only
curl -s "https://api.openshift.com/api/upgrades_info/v1/graph?channel=stable-{MAJOR}.{MINOR}&arch=amd64" \
  | jq -r '.nodes[].version' | sort -V | tail -1
```

## Upgrades Graph Endpoint (Public)

**URL:** `https://api.openshift.com/api/upgrades_info/v1/graph`

| Parameter | Required | Values | Example |
|-----------|----------|--------|---------|
| `channel` | Yes | `{type}-{major}.{minor}` | `stable-4.18` |
| `arch` | No | `amd64`, `arm64`, `ppc64le`, `s390x`, `multi` | `amd64` |

**Channel types:** `stable`, `fast`, `candidate`, `eus`

**Response structure:**
```json
{
  "nodes": [
    {"version": "X.Y.Z", "payload": "quay.io/..."}
  ],
  "edges": [[0,1], [1,2]]
}
```

`edges` encode directed upgrade paths: `[from_node_index, to_node_index]`. The script's `--upgrade-path` mode parses these for you.

## Authenticated Endpoint (clusters_mgmt)

For ROSA/HCP flags, EOL dates, and deployment metadata. Requires an OAuth token from https://console.redhat.com/openshift/token.

```bash
# List all versions with metadata
python3 scripts/query_versions.py --token "$OCM_TOKEN"

# Filter: ROSA-enabled only
python3 scripts/query_versions.py --token "$OCM_TOKEN" --rosa-enabled --enabled

# Filter: HCP-enabled, stable channel
python3 scripts/query_versions.py --token "$OCM_TOKEN" --hcp-enabled --channel-group stable

# Specific version details
python3 scripts/query_versions.py --token "$OCM_TOKEN" --version "openshift-v{MAJOR}.{MINOR}.{PATCH}"
```

### Key Response Fields

| Field | Description |
|-------|-------------|
| `raw_id` | Semantic version string |
| `channel_group` | `stable`, `candidate`, `fast`, `eus` |
| `enabled` | Available for new cluster deployment |
| `rosa_enabled` | Available for ROSA |
| `hosted_control_plane_enabled` | Available for HCP |
| `end_of_life_timestamp` | ISO 8601 EOL date |
| `available_upgrades` | Upgrade targets from this version |

## Script Reference

All modes accept `--json` for machine-parseable output and `--arch` to specify architecture.

| Mode | Flag | Auth | Description |
|------|------|------|-------------|
| Discover | `--discover` | No | Probe channels, list active minors with counts |
| All Latest | `--all-latest` | No | Latest patch per active minor (one-liner summary) |
| Upgrade Path | `--upgrade-path VER` | No | Valid upgrade targets from a given version |
| Channel Query | `--channel CH` | No | List/latest versions in a specific channel |
| Authenticated | `--token TOK` | Yes | Detailed metadata, filters for ROSA/HCP/EOL |

### Output Formats

All modes support `--json` for machine-readable output.

```bash
# Discover active minors as JSON
python3 scripts/query_versions.py --discover --json

# Parse upgrade-path output with jq
python3 scripts/query_versions.py --upgrade-path 4.15.10 --json | jq '.'
```

### Pagination (Authenticated Endpoint Only)

When using `--token`, the authenticated endpoint returns paginated results with a maximum `--size` of 100.

```bash
# First page (default)
python3 scripts/query_versions.py --token "$OCM_TOKEN" --enabled

# Explicit page and size
python3 scripts/query_versions.py --token "$OCM_TOKEN" --enabled --page 2 --size 50
```

Only authenticated queries use `--page` and `--size`. Discovery, channel queries, and upgrade-path mode return complete results.

### Retry Controls

Use global retry flags to tune resilience behavior per run:

```bash
# Increase retries for flaky networks
python3 scripts/query_versions.py --discover --retry-count 5 --retry-base-delay 0.25

# Disable retries for fast-fail automation
python3 scripts/query_versions.py --channel stable-4.18 --latest --retry-count 0
```

- `--retry-count` controls transient retry attempts (default: `3`)
- `--retry-base-delay` controls exponential backoff base in seconds (default: `0.5`)

### Range Controls (for discover / all-latest)

| Flag | Default | Description |
|------|---------|-------------|
| `--major` | `4` | Major version to scan |
| `--floor` | `12` | Lowest minor to probe |
| `--ceiling` | `99` | Highest minor to probe (auto-stops after 3 empty) |
| `--channel-type` | `stable` | Channel type to probe (`stable`, `fast`, `candidate`, `eus`) |

Validation rules:
- `--channel-type` must be a single value for `--discover` and `--all-latest`
- `--floor` must be `0` or greater
- `--ceiling` must be greater than or equal to `--floor`
- `--major` must be between `1` and `20`

### Upgrade Path Controls

| Flag | Default | Description |
|------|---------|-------------|
| `--channel-type` | `stable` | Comma-separated channel types to check (e.g., `stable,eus`) |
| `--arch` | `amd64` | Architecture |

### Multi-Architecture Support

Not every OCP minor is published for every architecture. Use discovery first if you are checking `arm64`, `ppc64le`, `s390x`, or `multi`.

```bash
# Find the latest patch for every active ppc64le minor
python3 scripts/query_versions.py --all-latest --arch ppc64le

# Inspect one channel on ARM64
python3 scripts/query_versions.py --channel stable-{MAJOR}.{MINOR} --arch arm64
```

`multi` is valid but usually less useful for operator workflows than a concrete architecture.

## Error Handling

| HTTP Code | Meaning |
|-----------|---------|
| 401 | Invalid or expired token (clusters_mgmt only) |
| 404 | Channel or version not found (expected during discovery probing) |
| 429 | Rate limited — script retries with bounded exponential backoff |

## Troubleshooting & Common Issues

### No versions found for a channel

- Cause: the channel does not exist yet or that architecture has no payloads for it
- Fix: run `--discover` or `--all-latest` first, then plug the discovered minor into `--channel`

### Discovery stops earlier than expected

- The script stops after 3 consecutive empty channels to avoid probing the entire ceiling range
- Connection failures do not count toward that empty-channel cutoff
- If you expect higher minors, raise `--ceiling` explicitly

### Upgrade path returns no targets

- Cause: there is no direct one-hop upgrade edge from that version in the channels you checked
- Fix: try `--channel-type stable,eus` or inspect intermediate versions in the same minor

### Invalid argument errors

- `--channel` must match `{type}-{major}.{minor}` such as `stable-4.18`
- `--size` must stay between `1` and `100`
- `--page` must be `1` or greater
- `--channel-type` must be one of `stable`, `fast`, `candidate`, `eus`
- `--retry-count` must be `0` or greater
- `--retry-base-delay` must be greater than `0`

### Token rejected with 401

- Cause: token expired or copied incorrectly
- Fix: generate a fresh token from https://console.redhat.com/openshift/token
- Note: the script does not auto-refresh tokens

### Rate limiting and transient network failures

- The script retries bounded transient failures automatically (`429`, `5xx`, and URL connection errors)
- Retry behavior uses short exponential backoff and then returns a clear error if all attempts fail
- Use `--json` in automation so retries stay transparent to downstream parsing

### Public and authenticated endpoints disagree

- The public graph can show newly published payloads before `clusters_mgmt` picks up the same version metadata
- Use the public endpoint for immediate availability questions and the authenticated endpoint for lifecycle and ROSA/HCP metadata

## Workflow Guidance for Claude

When a user asks about OpenShift versions:

1. **"What versions are available?"** → Run `--all-latest` to show current state
2. **"What's the latest 4.X?"** → Run `--channel stable-4.X --latest` (or `--all-latest` if X is unknown)
3. **"What can I upgrade to from 4.X.Y?"** → Run `--upgrade-path 4.X.Y`
4. **"Is 4.X still supported?"** → Run `--discover` and check if 4.X appears; for EOL dates use `--token` with authenticated endpoint
5. **"What ROSA/HCP versions are available?"** → Requires `--token`; prompt user for OCM token if not provided

Always run `--discover` or `--all-latest` first when the user's question is broad or doesn't name a specific version. Never guess version numbers.

## References

See `references/api_reference.md` for detailed API schema, pagination details, search query syntax, and authentication details.
