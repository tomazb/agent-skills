---
name: openshift-cert-manager
description: Use when installing, configuring, validating, renewing, replacing OpenShift default ingress or API certificates, or troubleshooting cert-manager, Let's Encrypt, ACME HTTP-01, or DNS-01 on OpenShift/OKD — including Single Node OpenShift, ClusterIssuer setup, staging vs production ACME, and IngressController or APIServer serving-cert replacement.
---

# OpenShift cert-manager Lifecycle

Use this skill as a lifecycle router for the Red Hat cert-manager Operator and Let's Encrypt on OpenShift/OKD. Do live discovery first, choose the relevant reference runbook, and write an actionable plan with explicit safety gates. Default to read-only discovery. Do not apply mutating resources until the user confirms the exact `oc` context and intent.

## Routing

- **Discovery, OperatorHub, or first install**: start with `references/install-and-preflight.md`.
- **Prove ACME with HTTP-01 (staging then production for app routes)**: use `references/acme-http01-proof.md`.
- **Wildcard or API certificates, or DNS provider solvers**: use `references/acme-dns01.md`.
- **Replace default `*.apps` ingress cert or public API serving cert**: use `references/platform-certs.md`.
- **Failed Challenges, Orders, CertificateRequests, or renewal issues**: use `references/validation-troubleshooting.md`.
- **Revert platform certs, uninstall operator, leftover CRDs**: use `references/maintenance-uninstall.md`.

## Core Safety Rules

- Never `oc apply`, patch `IngressController`, or patch `APIServer` until the user gives explicit confirmation for the named context (for example `htz2`).
- Do not patch `IngressController` `defaultCertificate` or `APIServer` `servingCerts.namedCertificates` until the target `Certificate` is `Ready=True` from the **production** Let's Encrypt issuer. Staging certificates must not become cluster platform certs.
- HTTP-01: fail preflight if public TCP **:80** is closed on any resolved **A or AAAA** for the challenge hostname. Let's Encrypt often prefers IPv6.
- `*.apps` wildcards **must** use DNS-01. Let's Encrypt does not issue wildcard certificates via HTTP-01.
- The public API serving cert **must** use DNS-01. kube-apiserver listens on `:6443` and is not behind the OpenShift router.
- Do not delete `router-certs-default`. Keep it for rollback. Document revert patches before applying platform certs.
- After an API cert swap, kubeconfigs that pin `certificate-authority-data` to the old kube-apiserver signer will fail TLS until that CA pin is removed or updated so the client trusts Let's Encrypt.
- Never hammer the production ACME endpoint. Always prove issuance on the **staging** issuer first.
- Do not confuse CNV `kubemacpool-cert-manager` with cluster cert-manager. Require `cert-manager.io` CRDs (`Certificate`, `ClusterIssuer`).
- On SNO, warn that an API serving-cert mispatch can lock out `oc` until kubeconfig/CA trust is fixed.

## Required Source Checks

For install, issuer, and platform-cert operations, verify current Red Hat cert-manager Operator docs for the installed OpenShift version when network access is available. Use pinned channel/CSV from live discovery; do not assume the OperatorHub default is the target unless the user asks for it or the cluster already runs it.

For OpenShift channel, patch, or one-hop upgrade-path questions, use `openshift-versions`. Release availability is not cluster upgrade readiness and is not cert-manager product compatibility.

## Inputs To Collect

- Cluster topology: SNO or multi-node, OpenShift/OKD version, `oc` context, API FQDN, ingress domain (`spec.domain` on `ingress.config/cluster`).
- Current TLS: ingress default secret issuer/SANs, API serving cert issuer/SANs, whether `APIServer` already has `namedCertificates`.
- cert-manager state: absent, RH operator installed, community operator present, CRDs, `ClusterIssuer` names, `Certificate` Ready conditions.
- ACME email, staging vs production intent, and HTTP-01 hostname for the proof Route.
- DNS-01 provider (prefer Red Hat-supported Route 53 / Azure DNS / Google Cloud DNS; Cloudflare only as an explicit unsupported path), API token Secret location, and zone that hosts the API and `*.apps` names.
- Whether the user wants only install+proof, or also platform `*.apps` / API replacement, plus a maintenance window.

## Output Expectations

- Start with discovered facts, assumptions, and safety gates.
- Name the exact reference runbook(s) used.
- Separate read-only discovery from mutating actions.
- Show commands with placeholders for cluster-specific values instead of fabricating FQDNs or tokens.
- Include post-change validation, kubeconfig CA notes, and rollback patches.
- Run `python3 scripts/discover_tls.py --execute` before recommending apply. Run `python3 scripts/check_http01_reachability.py` before HTTP-01 issuance.
