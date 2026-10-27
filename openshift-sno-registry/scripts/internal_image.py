#!/usr/bin/env python3
"""Validators for registry image references.

Push credentials may only be sent to the in-cluster registry service. Source
and tool images are separate pull references and never receive those credentials.
"""

from __future__ import annotations

import re

INTERNAL_REGISTRY = "image-registry.openshift-image-registry.svc:5000"
_REPOSITORY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,61}[a-z0-9])?$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_SOURCE_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{2,5})?"
    r"(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)+"
    r":[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$"
)


class ImageReferenceError(ValueError):
    """Raised when a reference must not be rendered into a manifest."""


def parse_internal_image(reference: str, namespace: str) -> str:
    """Return a reference only when it is the internal registry plus this namespace.

    The accepted form is exactly
    ``image-registry.openshift-image-registry.svc:5000/<namespace>/<name>:<tag>``.
    A longer host, a different port, userinfo, a digest, or an extra path
    segment is rejected. The error text does not echo the submitted reference.
    """

    prefix = f"{INTERNAL_REGISTRY}/{namespace}/"
    repository = _repository_and_tag(reference, prefix)
    if repository is None:
        raise ImageReferenceError(
            "destination must be "
            f"{INTERNAL_REGISTRY}/{namespace}/<name>:<tag>"
        )
    return reference


def parse_source_image(reference: str) -> str:
    """Return a pull reference that cannot carry embedded credentials."""

    if not isinstance(reference, str) or _SOURCE_RE.fullmatch(reference) is None:
        raise ImageReferenceError(
            "image must be host[:port]/repository:tag with no scheme or credentials"
        )
    return reference


def _repository_and_tag(reference: str, prefix: str) -> str | None:
    if not isinstance(reference, str) or not reference.startswith(prefix):
        return None
    remainder = reference[len(prefix) :]
    if remainder.count(":") != 1 or "/" in remainder or "@" in remainder:
        return None
    name, tag = remainder.split(":", 1)
    if _REPOSITORY_RE.fullmatch(name) is None or _TAG_RE.fullmatch(tag) is None:
        return None
    if name in {".", ".."}:
        return None
    return remainder
