#!/usr/bin/env python3
"""Read-only OpenShift TLS / cert-manager discovery helper.

Builds and optionally runs `oc` discovery commands. Never mutates the cluster.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

DEFAULT_PORTS = (80, 443, 6443)

SUBJECT_RE = re.compile(r"^subject\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE)
ISSUER_RE = re.compile(r"^issuer\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE)
NOT_BEFORE_RE = re.compile(r"^notBefore\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE)
NOT_AFTER_RE = re.compile(r"^notAfter\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE)
DNS_SAN_RE = re.compile(r"DNS:([^\s,]+)")


@dataclass(frozen=True)
class DiscoveryCommand:
    name: str
    argv: tuple[str, ...]


def oc_argv(context: str | None, *args: str) -> list[str]:
    cmd = ["oc"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(args)
    return cmd


def discovery_commands(context: str | None = None) -> list[DiscoveryCommand]:
    """Return ordered read-only discovery commands."""
    return [
        DiscoveryCommand("whoami", tuple(oc_argv(context, "whoami"))),
        DiscoveryCommand(
            "cluster_version",
            tuple(
                oc_argv(
                    context,
                    "get",
                    "clusterversion",
                    "-o",
                    "jsonpath={.items[0].status.desired.version}",
                )
            ),
        ),
        DiscoveryCommand(
            "api_server_url",
            tuple(
                oc_argv(
                    context,
                    "get",
                    "infrastructure",
                    "cluster",
                    "-o",
                    "jsonpath={.status.apiServerURL}",
                )
            ),
        ),
        DiscoveryCommand(
            "ingress_domain",
            tuple(
                oc_argv(
                    context,
                    "get",
                    "ingress.config",
                    "cluster",
                    "-o",
                    "jsonpath={.spec.domain}",
                )
            ),
        ),
        DiscoveryCommand(
            "ingresscontroller_default",
            tuple(
                oc_argv(
                    context,
                    "get",
                    "ingresscontroller",
                    "default",
                    "-n",
                    "openshift-ingress-operator",
                    "-o",
                    "yaml",
                )
            ),
        ),
        DiscoveryCommand(
            "apiserver_cluster",
            tuple(oc_argv(context, "get", "apiserver", "cluster", "-o", "yaml")),
        ),
        DiscoveryCommand(
            "cert_manager_crds",
            tuple(oc_argv(context, "api-resources", "--api-group=cert-manager.io")),
        ),
        DiscoveryCommand(
            "packagemanifests_cert_manager",
            tuple(
                oc_argv(
                    context,
                    "get",
                    "packagemanifests",
                    "-n",
                    "openshift-marketplace",
                    "-o",
                    "custom-columns=NAME:.metadata.name,CATALOG:.status.catalogSource",
                    "--no-headers",
                )
            ),
        ),
        DiscoveryCommand(
            "operator_subscription",
            tuple(
                oc_argv(
                    context,
                    "-n",
                    "cert-manager-operator",
                    "get",
                    "subscription,csv,pods",
                )
            ),
        ),
        DiscoveryCommand(
            "operand_pods",
            tuple(oc_argv(context, "-n", "cert-manager", "get", "pods")),
        ),
    ]


def parse_openssl_x509(text: str) -> dict[str, Any]:
    """Parse `openssl x509 -noout -subject -issuer -dates -ext subjectAltName` output."""
    subject = SUBJECT_RE.search(text)
    issuer = ISSUER_RE.search(text)
    not_before = NOT_BEFORE_RE.search(text)
    not_after = NOT_AFTER_RE.search(text)
    dns_names = DNS_SAN_RE.findall(text)
    return {
        "subject": subject.group(1).strip() if subject else None,
        "issuer": issuer.group(1).strip() if issuer else None,
        "not_before": not_before.group(1).strip() if not_before else None,
        "not_after": not_after.group(1).strip() if not_after else None,
        "dns_names": dns_names,
    }


def certificate_ready_from_status(status: dict[str, Any] | None) -> bool:
    """Return True when Certificate status.conditions includes Ready=True."""
    if not status:
        return False
    conditions = status.get("conditions")
    if not isinstance(conditions, list):
        return False
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if condition.get("type") != "Ready":
            continue
        return str(condition.get("status", "")).lower() == "true"
    return False


def is_staging_acme_server(server: str | None) -> bool:
    if not server:
        return False
    return "acme-staging" in server.lower()


def is_production_acme_server(server: str | None) -> bool:
    if not server:
        return False
    lowered = server.lower()
    return "acme-v02.api.letsencrypt.org" in lowered and "staging" not in lowered


def filter_cert_manager_packagemanifests(lines: Iterable[str]) -> list[str]:
    """Keep OperatorHub lines that mention cert-manager (excluding noise)."""
    kept: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if "cert-manager" in line.lower():
            kept.append(line)
    return kept


def hostname_from_api_url(api_url: str) -> str | None:
    """Extract hostname from https://api.example:6443."""
    text = api_url.strip()
    if not text:
        return None
    text = re.sub(r"^https?://", "", text)
    host = text.split("/")[0]
    host = host.split(":")[0]
    return host or None


def probe_ports_plan(
    hostname: str, ports: Sequence[int] = DEFAULT_PORTS
) -> list[tuple[str, int]]:
    return [(hostname, port) for port in ports]


def tcp_connect(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_command(argv: Sequence[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def print_discovery(context: str | None, *, execute: bool) -> int:
    commands = discovery_commands(context)
    exit_code = 0
    for command in commands:
        print(f"## {command.name}")
        print(" ".join(command.argv))
        if not execute:
            print()
            continue
        try:
            result = run_command(command.argv)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            exit_code = 1
            print()
            continue
        if result.stdout.strip():
            print(result.stdout.rstrip())
        if result.stderr.strip():
            print(result.stderr.rstrip(), file=sys.stderr)
        if result.returncode != 0:
            exit_code = 1
        print()
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only TLS / cert-manager discovery for OpenShift."
    )
    parser.add_argument(
        "--context",
        default=None,
        help="oc/kubectl context (for example htz2)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the discovery commands (default: print only)",
    )
    parser.add_argument(
        "--parse-openssl",
        metavar="FILE",
        help="Parse an openssl x509 text dump and print JSON",
    )
    parser.add_argument(
        "--parse-certificate-status",
        metavar="FILE",
        help="Parse Certificate .status JSON and print Ready bool as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.parse_openssl:
        with open(args.parse_openssl, encoding="utf-8") as handle:
            text = handle.read()
        print(json.dumps(parse_openssl_x509(text), indent=2, sort_keys=True))
        return 0

    if args.parse_certificate_status:
        with open(args.parse_certificate_status, encoding="utf-8") as handle:
            payload = json.loads(handle.read())
        status = payload.get("status") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and "conditions" in payload and "status" not in payload:
            status = payload
        print(
            json.dumps(
                {"ready": certificate_ready_from_status(status)},
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    return print_discovery(args.context, execute=args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
