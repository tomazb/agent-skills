# Changelog

## 1.0.1

- Replace the real cluster FQDN used in the nested-zone troubleshooting example
  and in `test_hostname_from_api_url` with RFC 2606 documentation names. The
  example still carries two labels, so the nested-zone point it illustrates is
  unchanged.
- Move the IPv4 probe placeholder in the HTTP-01 tests from the routable
  `1.2.3.4` to RFC 5737 `192.0.2.1`, matching the RFC 3849 `2001:db8::1` already
  used beside it. The fixture's connector selected the A record by its leading
  `1.` octet, which no longer distinguishes the two, so it now matches the
  address explicitly.

## 1.0.0

- Initial OpenShift cert-manager lifecycle skill: RH operator install, staging HTTP-01 proof, parameterized DNS-01, gated `*.apps` and API serving-cert replacement, validation, and uninstall.
