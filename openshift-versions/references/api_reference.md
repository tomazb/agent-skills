# OpenShift Cluster Manager (OCM) API Reference

## Base Information

| Property | Value |
|----------|-------|
| Base URL | `https://api.openshift.com` |
| Content Type | `application/json` |

## Public Endpoint (No Authentication)

### Upgrades Graph

Provides version information and upgrade paths for a specific channel.

```
GET /api/upgrades_info/v1/graph
```

**Query Parameters:**

| Parameter | Required | Description | Example |
|-----------|----------|-------------|---------|
| `channel` | Yes | Channel name (`{type}-{major}.{minor}`) | `stable-4.18` |
| `arch` | No | CPU architecture (default: `amd64`) | `arm64` |

**Channel Types:**
- `stable` - Production-ready releases
- `fast` - Early access to stable releases  
- `candidate` - Pre-release testing
- `eus` - Extended Update Support

**Architectures:** `amd64`, `arm64`, `ppc64le`, `s390x`, `multi`

**Response Schema:**

```json
{
  "nodes": [
    {
      "version": "4.18.0",
      "payload": "quay.io/openshift-release-dev/ocp-release:4.18.0-x86_64",
      "metadata": {
        "url": "https://access.redhat.com/errata/RHSA-2024:0000"
      }
    },
    {
      "version": "4.18.1",
      "payload": "quay.io/openshift-release-dev/ocp-release:4.18.1-x86_64"
    }
  ],
  "edges": [
    [0, 1],
    [1, 2]
  ]
}
```

**Response Fields:**

| Field | Description |
|-------|-------------|
| `nodes` | Array of version objects |
| `nodes[].version` | Semantic version string |
| `nodes[].payload` | Container image reference |
| `nodes[].metadata.url` | Errata/release notes URL (optional) |
| `edges` | Upgrade paths as `[from_index, to_index]` pairs |

**Example Queries:**

```bash
# Latest stable-4.18 version
curl -s "https://api.openshift.com/api/upgrades_info/v1/graph?channel=stable-4.18&arch=amd64" \
  | jq -r '.nodes[].version' | sort -V | tail -1

# All versions in fast-4.19
curl -s "https://api.openshift.com/api/upgrades_info/v1/graph?channel=fast-4.19&arch=amd64" \
  | jq -r '.nodes[].version' | sort -V

# ARM64 versions
curl -s "https://api.openshift.com/api/upgrades_info/v1/graph?channel=stable-4.18&arch=arm64" \
  | jq -r '.nodes[].version' | sort -V
```

---

## Authenticated Endpoint (OAuth Required)

### Versions Endpoint (clusters_mgmt)

```
GET /api/clusters_mgmt/v1/versions
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | integer | Page number (default: 1) |
| `size` | integer | Items per page (default: 100, max: 100) |
| `search` | string | SQL-like search filter |
| `order` | string | Sort order (e.g., `raw_id desc`) |

**Response Schema:**

```json
{
  "kind": "VersionList",
  "page": 1,
  "size": 100,
  "total": 250,
  "items": [
    {
      "kind": "Version",
      "id": "openshift-v4.14.0",
      "href": "/api/clusters_mgmt/v1/versions/openshift-v4.14.0",
      "raw_id": "4.14.0",
      "channel_group": "stable",
      "enabled": true,
      "default": false,
      "rosa_enabled": true,
      "hosted_control_plane_enabled": true,
      "hosted_control_plane_default": false,
      "end_of_life_timestamp": "2025-05-17T00:00:00Z",
      "release_image": "quay.io/openshift-release-dev/ocp-release:4.14.0-x86_64",
      "available_upgrades": ["4.14.1", "4.14.2"]
    }
  ]
}
```

### Get Single Version

```
GET /api/clusters_mgmt/v1/versions/{version_id}
```

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `version_id` | string | Version identifier (e.g., `openshift-v4.14.0`) |

## Version Object Schema

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique version identifier |
| `href` | string | API path to this version |
| `raw_id` | string | Semantic version number |
| `channel_group` | string | Update channel (`stable`, `candidate`, `fast`, `eus`) |
| `enabled` | boolean | Version available for new cluster deployment |
| `default` | boolean | Default version for OCP/OSD clusters |
| `rosa_enabled` | boolean | Available for ROSA clusters |
| `hosted_control_plane_enabled` | boolean | Available for HCP clusters |
| `hosted_control_plane_default` | boolean | Default for HCP clusters |
| `end_of_life_timestamp` | string | ISO 8601 EOL date |
| `release_image` | string | Container image reference |
| `available_upgrades` | array | List of available upgrade targets |
| `gcp_marketplace_enabled` | boolean | Available on GCP Marketplace |
| `azure_marketplace_enabled` | boolean | Available on Azure Marketplace |

## Search Query Syntax

The API supports SQL-like search queries with these operators:

### Comparison Operators

| Operator | Example |
|----------|---------|
| `=` | `enabled = 'true'` |
| `!=` or `<>` | `channel_group <> 'candidate'` |
| `like` | `raw_id like '4.14%'` |
| `in` | `channel_group in ('stable', 'eus')` |

### Logical Operators

| Operator | Example |
|----------|---------|
| `and` | `enabled = 'true' and rosa_enabled = 'true'` |
| `or` | `channel_group = 'stable' or channel_group = 'eus'` |

### Common Search Patterns

```
# All enabled ROSA versions
enabled = 'true' and rosa_enabled = 'true'

# Stable channel versions only
channel_group = 'stable'

# Versions matching 4.14.x pattern
raw_id like '4.14%'

# All HCP-enabled stable versions
hosted_control_plane_enabled = 'true' and channel_group = 'stable'

# EUS (Extended Update Support) versions
channel_group = 'eus' and enabled = 'true'
```

## Channel Groups

| Channel | Description |
|---------|-------------|
| `stable` | Production-ready, recommended for most workloads |
| `fast` | Early access to stable releases |
| `candidate` | Pre-release testing versions |
| `eus` | Extended Update Support (longer lifecycle) |

## Authentication

### Obtaining a Token

1. Navigate to https://console.redhat.com/openshift/token
2. Log in with your Red Hat account
3. Copy the displayed token

### Using the Token

Include in request headers:

```
Authorization: Bearer <your-token>
```

Token characteristics:
- Access tokens expire (typically 15 minutes)
- Offline tokens have longer validity
- Use `ocm login` CLI for automatic token management

## Error Responses

| HTTP Code | Error | Description |
|-----------|-------|-------------|
| 400 | Bad Request | Invalid query syntax |
| 401 | Unauthorized | Missing or invalid token |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Version does not exist |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server-side error |

Error response format:

```json
{
  "kind": "Error",
  "id": "401",
  "href": "/api/clusters_mgmt/v1/errors/401",
  "code": "CLUSTERS-MGMT-401",
  "reason": "Authentication required"
}
```

## Rate Limits

The API implements rate limiting. When exceeded:
- HTTP 429 response returned
- `Retry-After` header indicates wait time

## Related Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/clusters_mgmt/v1/clusters` | Cluster management |
| `/api/clusters_mgmt/v1/cloud_providers` | Available cloud providers |
| `/api/clusters_mgmt/v1/products` | Product types (OSD, ROSA, etc.) |
| `/api/accounts_mgmt/v1/subscriptions` | Account subscriptions |

## External Resources

- [OCM CLI](https://github.com/openshift-online/ocm-cli)
- [OCM API Model](https://github.com/openshift-online/ocm-api-model)
- [Red Hat Console](https://console.redhat.com/openshift)
