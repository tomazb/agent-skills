#!/usr/bin/env python3
"""Check public TCP :80 reachability on all A and AAAA addresses for HTTP-01.

Read-only. Exits non-zero if any resolved address fails the port probe, or if
no addresses resolve. Let's Encrypt often prefers IPv6 when AAAA exists.
"""

from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class AddressProbe:
    family: str
    address: str
    port: int
    ok: bool
    error: str | None = None


def resolve_addresses(hostname: str) -> dict[str, list[str]]:
    """Resolve A and AAAA without contacting the challenge path."""
    found: dict[str, list[str]] = {"A": [], "AAAA": []}
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return found

    for family, _type, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET:
            ip = sockaddr[0]
            if ip not in found["A"]:
                found["A"].append(ip)
        elif family == socket.AF_INET6:
            ip = sockaddr[0]
            if ip not in found["AAAA"]:
                found["AAAA"].append(ip)
    return found


def probe_tcp(address: str, port: int, timeout: float = 5.0) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True, None
    except OSError as error:
        return False, str(error)


def build_probes(
    hostname: str,
    *,
    port: int = 80,
    timeout: float = 5.0,
    resolver=resolve_addresses,
    connector=probe_tcp,
) -> list[AddressProbe]:
    resolved = resolver(hostname)
    probes: list[AddressProbe] = []
    for family in ("A", "AAAA"):
        for address in resolved[family]:
            ok, error = connector(address, port, timeout)
            probes.append(
                AddressProbe(
                    family=family,
                    address=address,
                    port=port,
                    ok=ok,
                    error=error,
                )
            )
    return probes


def preflight_ok(probes: Sequence[AddressProbe]) -> bool:
    """HTTP-01 preflight passes only when every resolved address accepts :port."""
    if not probes:
        return False
    return all(probe.ok for probe in probes)


def summarize(hostname: str, probes: Sequence[AddressProbe]) -> str:
    lines = [f"hostname={hostname}"]
    if not probes:
        lines.append("result=FAIL reason=no_addresses_resolved")
        return "\n".join(lines)
    for probe in probes:
        status = "open" if probe.ok else "closed"
        detail = f" error={probe.error}" if probe.error else ""
        lines.append(
            f"{probe.family} {probe.address}:{probe.port} {status}{detail}"
        )
    lines.append("result=PASS" if preflight_ok(probes) else "result=FAIL")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail if TCP :80 is closed on any A/AAAA for HTTP-01."
    )
    parser.add_argument("--hostname", required=True, help="Challenge hostname")
    parser.add_argument("--port", type=int, default=80, help="TCP port (default 80)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-address connect timeout seconds",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    probes = build_probes(
        args.hostname,
        port=args.port,
        timeout=args.timeout,
    )
    print(summarize(args.hostname, probes))
    return 0 if preflight_ok(probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
