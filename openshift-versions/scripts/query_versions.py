#!/usr/bin/env python3
"""
Query OpenShift versions from api.openshift.com.

Supports two endpoints:
1. Public (no auth): /api/upgrades_info/v1/graph - upgrade graphs by channel
2. Authenticated: /api/clusters_mgmt/v1/versions - detailed version metadata

Dynamic discovery modes:
    --discover          Probe channels to find all active OCP minor versions
    --all-latest        Show the latest patch for every active minor version
    --upgrade-path VER  Show all valid upgrade targets from a given version

Standard queries:
    --channel stable-4.18 --latest   Latest patch in a specific channel
    --channel stable-4.18            All versions in a channel

Authenticated queries:
    --token "$OCM_TOKEN" --rosa-enabled --enabled
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional


BASE_URL = "https://api.openshift.com"
GRAPH_ENDPOINT = "/api/upgrades_info/v1/graph"
VERSIONS_ENDPOINT = "/api/clusters_mgmt/v1/versions"

# Sensible defaults - fully overridable via --floor / --ceiling / --major
DEFAULT_FLOOR_MINOR = 12
DEFAULT_CEILING_MINOR = 99
DEFAULT_MAJOR = 4
CHANNELS = ["stable", "fast", "candidate", "eus"]


def make_request(
    endpoint: str,
    params: Optional[dict] = None,
    token: Optional[str] = None
) -> dict:
    """Make request to OCM API."""
    url = f"{BASE_URL}{endpoint}"

    if params:
        query_string = urllib.parse.urlencode(params)
        url = f"{url}?{query_string}"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {e.reason}\n{error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error: {e.reason}") from e


def get_graph_versions(channel: str, arch: str = "amd64") -> dict:
    """Get versions from the public upgrades graph endpoint."""
    params = {"channel": channel, "arch": arch}
    return make_request(GRAPH_ENDPOINT, params)


def list_versions(
    token: str,
    search: Optional[str] = None,
    page: int = 1,
    size: int = 100
) -> dict:
    """List versions from authenticated clusters_mgmt endpoint."""
    params = {"page": page, "size": size}
    if search:
        params["search"] = search
    return make_request(VERSIONS_ENDPOINT, params, token)


def get_version(token: str, version_id: str) -> dict:
    """Get specific version details from authenticated endpoint."""
    endpoint = f"{VERSIONS_ENDPOINT}/{version_id}"
    return make_request(endpoint, token=token)


def build_search_query(
    enabled: Optional[bool] = None,
    rosa_enabled: Optional[bool] = None,
    hcp_enabled: Optional[bool] = None,
    channel_group: Optional[str] = None,
    version_pattern: Optional[str] = None
) -> Optional[str]:
    """Build OCM search query from filter parameters."""
    conditions = []

    if enabled is not None:
        conditions.append(f"enabled = '{str(enabled).lower()}'")
    if rosa_enabled is not None:
        conditions.append(f"rosa_enabled = '{str(rosa_enabled).lower()}'")
    if hcp_enabled is not None:
        conditions.append(f"hosted_control_plane_enabled = '{str(hcp_enabled).lower()}'")
    if channel_group:
        conditions.append(f"channel_group = '{channel_group}'")
    if version_pattern:
        conditions.append(f"raw_id like '{version_pattern}%'")

    return " and ".join(conditions) if conditions else None


def version_key(v: str) -> tuple:
    """Parse version string for sorting (e.g., '4.18.30' -> (4, 18, 30))."""
    try:
        parts = v.split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)


def parse_version(v: str) -> Optional[tuple]:
    """Parse 'major.minor.patch' into (major, minor, patch). Returns None on failure."""
    try:
        parts = v.split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return None


def format_version(version: dict, verbose: bool = False) -> str:
    """Format a version entry for display (clusters_mgmt format)."""
    raw_id = version.get("raw_id", "N/A")
    channel = version.get("channel_group", "N/A")
    enabled = "✓" if version.get("enabled") else "✗"
    rosa = "✓" if version.get("rosa_enabled") else "✗"
    hcp = "✓" if version.get("hosted_control_plane_enabled") else "✗"

    line = f"{raw_id:<12} | {channel:<10} | enabled:{enabled} | rosa:{rosa} | hcp:{hcp}"

    if verbose:
        v_id = version.get("id", "N/A")
        eol = version.get("end_of_life_timestamp", "N/A")
        line += f"\n  ID: {v_id}\n  EOL: {eol}"
        if version.get("release_image"):
            line += f"\n  Image: {version['release_image']}"

    return line


# ---------------------------------------------------------------------------
# Discovery: probe the API to find all active minor versions
# ---------------------------------------------------------------------------

def discover_active_minors(
    channel_type: str = "stable",
    arch: str = "amd64",
    major: int = DEFAULT_MAJOR,
    floor_minor: int = DEFAULT_FLOOR_MINOR,
    ceiling_minor: int = DEFAULT_CEILING_MINOR,
) -> list:
    """
    Probe channel_type-{major}.{minor} for minor in [floor..ceiling].
    Stops after 3 consecutive empty responses to avoid infinite scanning.
    Returns list of dicts: {minor, channel, versions_count, latest, oldest}.
    Raises RuntimeError if ALL probes fail with connection errors (vs empty channels).
    """
    results = []
    consecutive_empty = 0
    total_probed = 0
    connection_errors = 0
    last_conn_error = ""

    for minor in range(floor_minor, ceiling_minor + 1):
        channel = f"{channel_type}-{major}.{minor}"
        total_probed += 1
        try:
            data = get_graph_versions(channel, arch)
            nodes = data.get("nodes", [])
            versions = sorted(
                [n["version"] for n in nodes if n.get("version")],
                key=version_key,
            )
            if versions:
                consecutive_empty = 0
                results.append({
                    "minor": minor,
                    "channel": channel,
                    "versions_count": len(versions),
                    "latest": versions[-1],
                    "oldest": versions[0],
                })
            else:
                consecutive_empty += 1
        except RuntimeError as e:
            consecutive_empty += 1
            err_msg = str(e)
            # Distinguish connectivity failures from HTTP 404s
            if "Connection error" in err_msg or "Name or service not known" in err_msg \
               or "name resolution" in err_msg or "timed out" in err_msg:
                connection_errors += 1
                last_conn_error = err_msg

        if consecutive_empty >= 3:
            break

    # If every single probe was a connection error, report it clearly
    if total_probed > 0 and connection_errors == total_probed:
        raise RuntimeError(
            f"Cannot reach api.openshift.com — all {total_probed} probes failed.\n"
            f"Last error: {last_conn_error}\n"
            f"Check network connectivity / DNS / proxy settings."
        )

    return results


# ---------------------------------------------------------------------------
# Upgrade paths: parse graph edges
# ---------------------------------------------------------------------------

def get_upgrade_targets(channel: str, from_version: str, arch: str = "amd64") -> list:
    """
    Given a channel and a source version, return all versions reachable
    in one hop via the graph edges.
    """
    data = get_graph_versions(channel, arch)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    # Build index: version_string -> node_index
    version_to_idx = {}
    idx_to_version = {}
    for i, node in enumerate(nodes):
        v = node.get("version", "")
        version_to_idx[v] = i
        idx_to_version[i] = v

    source_idx = version_to_idx.get(from_version)
    if source_idx is None:
        return []

    targets = []
    for edge in edges:
        if len(edge) == 2 and edge[0] == source_idx:
            target_ver = idx_to_version.get(edge[1])
            if target_ver:
                targets.append(target_ver)

    return sorted(targets, key=version_key)


def find_upgrade_paths(
    from_version: str,
    arch: str = "amd64",
    channel_types: Optional[list] = None,
) -> dict:
    """
    For a given source version, check all relevant channels for upgrade targets.
    Returns {channel: [target_versions]}.
    """
    parsed = parse_version(from_version)
    if not parsed or len(parsed) < 2:
        raise ValueError(f"Cannot parse version: {from_version}")

    major, minor = parsed[0], parsed[1]

    if channel_types is None:
        channel_types = CHANNELS

    results = {}
    total_probed = 0
    connection_errors = 0
    last_conn_error = ""

    for ct in channel_types:
        # Check same minor channel
        channel = f"{ct}-{major}.{minor}"
        total_probed += 1
        try:
            targets = get_upgrade_targets(channel, from_version, arch)
            if targets:
                results[channel] = targets
        except RuntimeError as e:
            err_msg = str(e)
            if "Connection error" in err_msg or "name resolution" in err_msg \
               or "timed out" in err_msg:
                connection_errors += 1
                last_conn_error = err_msg

        # Check next minor channel (cross-minor upgrades)
        next_channel = f"{ct}-{major}.{minor + 1}"
        total_probed += 1
        try:
            targets = get_upgrade_targets(next_channel, from_version, arch)
            if targets:
                results[next_channel] = targets
        except RuntimeError as e:
            err_msg = str(e)
            if "Connection error" in err_msg or "name resolution" in err_msg \
               or "timed out" in err_msg:
                connection_errors += 1
                last_conn_error = err_msg

    if total_probed > 0 and connection_errors == total_probed:
        raise RuntimeError(
            f"Cannot reach api.openshift.com — all {total_probed} probes failed.\n"
            f"Last error: {last_conn_error}\n"
            f"Check network connectivity / DNS / proxy settings."
        )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Query OpenShift versions from api.openshift.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Discovery (no auth, version-agnostic):
  %(prog)s --discover
  %(prog)s --discover --channel-type fast --arch arm64
  %(prog)s --discover --floor 14 --ceiling 20
  %(prog)s --all-latest
  %(prog)s --all-latest --channel-type eus

Upgrade paths (no auth):
  %(prog)s --upgrade-path 4.17.12
  %(prog)s --upgrade-path 4.16.30 --arch arm64 --channel-type stable,eus

Standard queries (no auth):
  %(prog)s --channel stable-4.18 --latest
  %(prog)s --channel stable-4.18 --arch arm64

Authenticated queries:
  %(prog)s --token "$OCM_TOKEN" --rosa-enabled --enabled
  %(prog)s --token "$OCM_TOKEN" --channel-group stable
  %(prog)s --token "$OCM_TOKEN" --version "openshift-v4.14.0"
        """
    )

    # Discovery options
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover all active minor versions by probing channels"
    )
    parser.add_argument(
        "--all-latest",
        action="store_true",
        help="Show latest patch version for every active minor"
    )
    parser.add_argument(
        "--upgrade-path",
        metavar="VERSION",
        help="Show upgrade targets from a specific version (e.g., 4.17.12)"
    )

    # Range controls
    parser.add_argument(
        "--major",
        type=int,
        default=DEFAULT_MAJOR,
        help=f"Major version to scan (default: {DEFAULT_MAJOR})"
    )
    parser.add_argument(
        "--floor",
        type=int,
        default=DEFAULT_FLOOR_MINOR,
        help=f"Lowest minor version to probe (default: {DEFAULT_FLOOR_MINOR})"
    )
    parser.add_argument(
        "--ceiling",
        type=int,
        default=DEFAULT_CEILING_MINOR,
        help=f"Highest minor version to probe (default: {DEFAULT_CEILING_MINOR})"
    )
    parser.add_argument(
        "--channel-type",
        default="stable",
        help="Channel type for discovery/upgrade-path (stable|fast|candidate|eus, "
             "comma-separated for upgrade-path, default: stable)"
    )

    # Public endpoint options
    parser.add_argument(
        "--channel",
        help="Channel name for public graph API (e.g., stable-4.18, fast-4.19)"
    )
    parser.add_argument(
        "--arch",
        default="amd64",
        choices=["amd64", "arm64", "ppc64le", "s390x", "multi"],
        help="Architecture (default: amd64)"
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Show only the latest version in channel"
    )

    # Authenticated endpoint options
    parser.add_argument(
        "--token", "-t",
        help="OCM API token (from console.redhat.com/openshift/token)"
    )
    parser.add_argument(
        "--version", "-v",
        help="Get specific version by ID (e.g., openshift-v4.14.0)"
    )
    parser.add_argument(
        "--enabled",
        action="store_true",
        help="Filter to enabled versions only"
    )
    parser.add_argument(
        "--rosa-enabled",
        action="store_true",
        help="Filter to ROSA-enabled versions only"
    )
    parser.add_argument(
        "--hcp-enabled",
        action="store_true",
        help="Filter to HCP enabled versions only"
    )
    parser.add_argument(
        "--channel-group", "-c",
        choices=["stable", "candidate", "fast", "eus"],
        help="Filter by channel group (authenticated endpoint)"
    )
    parser.add_argument(
        "--search", "-s",
        help="Version pattern to search (e.g., '4.14')"
    )

    # Output options
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        dest="output_json",
        help="Output raw JSON"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show additional version details"
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="Page number for pagination (default: 1)"
    )
    parser.add_argument(
        "--size",
        type=int,
        default=100,
        help="Page size (default: 100, max: 100)"
    )

    args = parser.parse_args()

    try:
        # ---- Discovery mode ----
        if args.discover or args.all_latest:
            results = discover_active_minors(
                channel_type=args.channel_type,
                arch=args.arch,
                major=args.major,
                floor_minor=args.floor,
                ceiling_minor=args.ceiling,
            )

            if args.output_json:
                print(json.dumps(results, indent=2))
            elif args.all_latest:
                print(f"Latest patch versions ({args.channel_type}, {args.arch}):")
                print("-" * 50)
                for r in results:
                    print(f"  {args.major}.{r['minor']:<4}  ->  {r['latest']}")
                print(f"\n{len(results)} active minor version(s) found")
            else:
                print(f"Active minor versions ({args.channel_type}, {args.arch}):")
                print("-" * 70)
                print(f"  {'Minor':<8} {'Count':<8} {'Oldest':<16} {'Latest':<16}")
                print("-" * 70)
                for r in results:
                    print(
                        f"  {args.major}.{r['minor']:<6} "
                        f"{r['versions_count']:<8} "
                        f"{r['oldest']:<16} "
                        f"{r['latest']:<16}"
                    )
                print(f"\n{len(results)} active minor version(s) found "
                      f"(scanned {args.major}.{args.floor}+, "
                      f"stopped after 3 consecutive empty)")

        # ---- Upgrade path mode ----
        elif args.upgrade_path:
            channel_types = [
                ct.strip() for ct in args.channel_type.split(",")
            ]
            paths = find_upgrade_paths(
                from_version=args.upgrade_path,
                arch=args.arch,
                channel_types=channel_types,
            )

            if args.output_json:
                print(json.dumps(paths, indent=2))
            elif not paths:
                print(f"No upgrade targets found for {args.upgrade_path}")
                print("Hint: check that the version exists in the channel(s) you specified.")
            else:
                print(f"Upgrade targets from {args.upgrade_path} ({args.arch}):")
                print("-" * 60)
                for channel, targets in sorted(paths.items()):
                    print(f"\n  [{channel}]")
                    for t in targets:
                        print(f"    -> {t}")
                total = sum(len(t) for t in paths.values())
                print(f"\n{total} target(s) across {len(paths)} channel(s)")

        # ---- Public graph endpoint (channel query) ----
        elif args.channel:
            result = get_graph_versions(args.channel, args.arch)

            if args.output_json:
                print(json.dumps(result, indent=2))
            else:
                nodes = result.get("nodes", [])
                versions = [n.get("version", "") for n in nodes if n.get("version")]
                versions_sorted = sorted(versions, key=version_key)

                if args.latest:
                    if versions_sorted:
                        print(versions_sorted[-1])
                    else:
                        print("No versions found")
                else:
                    print(f"Versions in {args.channel} ({args.arch}):")
                    print("-" * 40)
                    for v in versions_sorted:
                        print(v)
                    print(f"\nTotal: {len(versions_sorted)} versions")
                    if versions_sorted:
                        print(f"Latest: {versions_sorted[-1]}")

        # ---- Authenticated endpoint ----
        elif args.token:
            if args.version:
                result = get_version(args.token, args.version)
                if args.output_json:
                    print(json.dumps(result, indent=2))
                else:
                    print(format_version(result, verbose=True))
            else:
                search_query = build_search_query(
                    enabled=True if args.enabled else None,
                    rosa_enabled=True if args.rosa_enabled else None,
                    hcp_enabled=True if args.hcp_enabled else None,
                    channel_group=args.channel_group,
                    version_pattern=args.search
                )

                result = list_versions(
                    args.token,
                    search=search_query,
                    page=args.page,
                    size=min(args.size, 100)
                )

                if args.output_json:
                    print(json.dumps(result, indent=2))
                else:
                    items = result.get("items", [])
                    total = result.get("total", len(items))
                    page = result.get("page", 1)
                    size = result.get("size", len(items))

                    print(f"OpenShift Versions (showing {len(items)} of {total}, page {page})")
                    print("-" * 70)
                    print(f"{'Version':<12} | {'Channel':<10} | Status")
                    print("-" * 70)

                    for version in items:
                        print(format_version(version, verbose=args.verbose))

                    if total > page * size:
                        print(f"\n... {total - page * size} more. Use --page to paginate.")

        else:
            parser.print_help()
            print("\nError: Provide --discover, --all-latest, --upgrade-path, "
                  "--channel, or --token")
            sys.exit(1)

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
