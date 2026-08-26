from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_http01_reachability as http01
import discover_tls as discover


def test_oc_argv_with_context():
    assert discover.oc_argv("htz2", "whoami") == ["oc", "--context", "htz2", "whoami"]


def test_oc_argv_without_context():
    assert discover.oc_argv(None, "whoami") == ["oc", "whoami"]


def test_discovery_commands_include_context():
    commands = discover.discovery_commands("htz2")
    names = [command.name for command in commands]
    assert "whoami" in names
    assert "ingress_domain" in names
    assert "cert_manager_crds" in names
    assert all("--context" in command.argv for command in commands)
    assert all(command.argv[0] == "oc" for command in commands)


def test_parse_openssl_x509():
    text = """\
subject=CN=*.apps.example.com
issuer=CN=ingress-operator@123
notBefore=Jul 16 13:00:27 2026 GMT
notAfter=Jul 15 13:00:28 2028 GMT
X509v3 Subject Alternative Name:
    DNS:*.apps.example.com, DNS:apps.example.com
"""
    parsed = discover.parse_openssl_x509(text)
    assert parsed["subject"] == "CN=*.apps.example.com"
    assert parsed["issuer"] == "CN=ingress-operator@123"
    assert parsed["dns_names"] == ["*.apps.example.com", "apps.example.com"]


def test_certificate_ready_from_status_true():
    status = {
        "conditions": [
            {"type": "Issuing", "status": "False"},
            {"type": "Ready", "status": "True"},
        ]
    }
    assert discover.certificate_ready_from_status(status) is True


def test_certificate_ready_from_status_false():
    status = {"conditions": [{"type": "Ready", "status": "False"}]}
    assert discover.certificate_ready_from_status(status) is False


def test_certificate_ready_missing():
    assert discover.certificate_ready_from_status({}) is False
    assert discover.certificate_ready_from_status(None) is False


def test_acme_server_classification():
    assert discover.is_staging_acme_server(
        "https://acme-staging-v02.api.letsencrypt.org/directory"
    )
    assert discover.is_production_acme_server(
        "https://acme-v02.api.letsencrypt.org/directory"
    )
    assert not discover.is_production_acme_server(
        "https://acme-staging-v02.api.letsencrypt.org/directory"
    )


def test_hostname_from_api_url():
    assert (
        discover.hostname_from_api_url("https://api.ocp1.htz2.all-it.tech:6443")
        == "api.ocp1.htz2.all-it.tech"
    )


def test_filter_cert_manager_packagemanifests():
    lines = [
        "openshift-cert-manager-operator   redhat-operators",
        "cert-manager                      community-operators",
        "something-else                    redhat-operators",
    ]
    kept = discover.filter_cert_manager_packagemanifests(lines)
    assert len(kept) == 2


def test_http01_preflight_requires_addresses():
    assert http01.preflight_ok([]) is False


def test_http01_preflight_fails_closed_address():
    probes = [
        http01.AddressProbe("A", "1.2.3.4", 80, True),
        http01.AddressProbe("AAAA", "2001:db8::1", 80, False, "timed out"),
    ]
    assert http01.preflight_ok(probes) is False


def test_http01_preflight_passes_when_all_open():
    probes = [
        http01.AddressProbe("A", "1.2.3.4", 80, True),
        http01.AddressProbe("AAAA", "2001:db8::1", 80, True),
    ]
    assert http01.preflight_ok(probes) is True


def test_build_probes_uses_resolver_and_connector():
    def fake_resolver(_hostname):
        return {"A": ["1.2.3.4"], "AAAA": ["2001:db8::1"]}

    def fake_connector(address, port, timeout):
        return address.startswith("1."), None

    probes = http01.build_probes(
        "example.com",
        resolver=fake_resolver,
        connector=fake_connector,
    )
    assert len(probes) == 2
    assert probes[0].ok is True
    assert probes[1].ok is False


def test_summarize_fail_no_addresses():
    text = http01.summarize("example.com", [])
    assert "result=FAIL" in text
    assert "no_addresses_resolved" in text


def test_discover_main_parse_openssl(tmp_path):
    path = tmp_path / "cert.txt"
    path.write_text("subject=CN=demo\nissuer=CN=ca\n", encoding="utf-8")
    assert discover.main(["--parse-openssl", str(path)]) == 0


def test_discover_main_parse_certificate_status(tmp_path, capsys):
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps({"conditions": [{"type": "Ready", "status": "True"}]}),
        encoding="utf-8",
    )
    assert discover.main(["--parse-certificate-status", str(path)]) == 0
    assert '"ready": true' in capsys.readouterr().out


def test_http01_main_fail(monkeypatch):
    monkeypatch.setattr(
        http01,
        "build_probes",
        lambda *args, **kwargs: [],
    )
    assert http01.main(["--hostname", "example.com"]) == 1


def test_http01_timeout_must_be_positive():
    with pytest.raises(SystemExit):
        http01.main(["--hostname", "example.com", "--timeout", "0"])
    with pytest.raises(SystemExit):
        http01.main(["--hostname", "example.com", "--timeout", "-1"])
    with pytest.raises(SystemExit):
        http01.main(["--hostname", "example.com", "--timeout", "nan"])
    with pytest.raises(SystemExit):
        http01.main(["--hostname", "example.com", "--timeout", "inf"])


def test_positive_float_helper():
    assert http01.positive_float("1.5") == 1.5
    for bad in ("0", "-2", "nan", "inf", "-inf"):
        with pytest.raises(argparse.ArgumentTypeError, match="greater than 0"):
            http01.positive_float(bad)
