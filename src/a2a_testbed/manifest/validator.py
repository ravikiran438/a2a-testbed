# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Validate AgentCards against fetched ExtensionManifests.

This is the universal validator: given a manifest store, the validator
walks the ``capabilities.extensions[]`` list, fetches each manifest,
and validates the entry's payload against the manifest's
``agent_card_payload_schema``. No protocol-specific code. Adding a new
protocol that publishes a manifest costs zero validator changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from a2a_testbed.manifest.store import ManifestStore


class FindingKind(str, Enum):
    """Outcome of probing one capabilities.extensions[] entry.

    ``DECLARED_OK`` is the only "passed" state. The other values report
    different failure or information modes — together they let a
    third-party reviewer answer "what's wrong with this AgentCard?"
    without having any prior knowledge of the protocols involved.
    """

    DECLARED_OK = "declared_ok"
    DECLARED_INVALID = "declared_invalid"
    MANIFEST_NOT_FOUND = "manifest_not_found"
    MANIFEST_VERSION_UNSUPPORTED = "manifest_version_unsupported"
    PAYLOAD_MISSING = "payload_missing"


@dataclass(frozen=True)
class Finding:
    """One result from validating one declared extension."""

    kind: FindingKind
    extension_uri: str
    detail: str = ""
    schema_errors: tuple[str, ...] = ()


def _extract_payload(entry: dict) -> Optional[dict]:
    """Pull the typed payload out of an extension entry.

    A2A 1.0 doesn't strictly mandate where extension-specific fields
    live; common conventions in observed implementations are
    ``params`` and ``payload``, with some early implementations using
    inline keys on the entry itself.
    """
    if not isinstance(entry, dict):
        return None
    for key in ("params", "payload"):
        candidate = entry.get(key)
        if isinstance(candidate, dict):
            return candidate
    reserved = {"uri", "description", "required"}
    extra = {k: v for k, v in entry.items() if k not in reserved}
    return extra or None


# Manifest envelope versions this validator understands. Bumped only
# when a NEW major manifest_version requires code changes.
SUPPORTED_MANIFEST_MAJOR_VERSIONS = {"1"}


def _major(version: str) -> str:
    return version.split(".", 1)[0]


async def validate_agent_card(
    card: dict,
    *,
    store: ManifestStore,
) -> list[Finding]:
    """Validate every declared extension in an AgentCard against its manifest.

    Returns one Finding per ``capabilities.extensions[]`` entry. Order
    preserved so callers can correlate findings with the source entry.
    """
    findings: list[Finding] = []

    capabilities = card.get("capabilities") if isinstance(card, dict) else None
    if not isinstance(capabilities, dict):
        return findings
    extensions = capabilities.get("extensions") or []
    if not isinstance(extensions, list):
        return findings

    for entry in extensions:
        if not isinstance(entry, dict):
            continue
        uri = entry.get("uri")
        if not isinstance(uri, str) or not uri:
            continue

        manifest = await store.fetch(uri)
        if manifest is None:
            findings.append(
                Finding(
                    kind=FindingKind.MANIFEST_NOT_FOUND,
                    extension_uri=uri,
                    detail=("no manifest available for this URI; cannot validate payload"),
                )
            )
            continue

        if _major(manifest.manifest_version) not in SUPPORTED_MANIFEST_MAJOR_VERSIONS:
            findings.append(
                Finding(
                    kind=FindingKind.MANIFEST_VERSION_UNSUPPORTED,
                    extension_uri=uri,
                    detail=(
                        f"manifest_version={manifest.manifest_version!r} is "
                        "outside the supported set "
                        f"{sorted(SUPPORTED_MANIFEST_MAJOR_VERSIONS)}"
                    ),
                )
            )
            continue

        payload = _extract_payload(entry)
        if payload is None:
            findings.append(
                Finding(
                    kind=FindingKind.PAYLOAD_MISSING,
                    extension_uri=uri,
                    detail=(
                        "extension declared but no payload present "
                        "(checked 'params', 'payload', and inline keys)"
                    ),
                )
            )
            continue

        validator = Draft202012Validator(manifest.agent_card_payload_schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
        if errors:
            findings.append(
                Finding(
                    kind=FindingKind.DECLARED_INVALID,
                    extension_uri=uri,
                    detail="payload failed JSON Schema validation",
                    schema_errors=tuple(_format_error(e) for e in errors),
                )
            )
            continue

        findings.append(
            Finding(
                kind=FindingKind.DECLARED_OK,
                extension_uri=uri,
                detail=(
                    f"payload conforms to {manifest.extension.name} v{manifest.extension.version}"
                ),
            )
        )

    return findings


def _format_error(err: ValidationError) -> str:
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"
