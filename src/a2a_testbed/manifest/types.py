# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Pydantic types for the ExtensionManifest convention.

The manifest is intentionally JSON-Schema-shaped: the centerpiece
field, ``agent_card_payload_schema``, is a JSON Schema document that
any standards-compliant validator can consume. The surrounding
metadata is small and stable so manifests render reliably across
toolchains.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# Bumped when the manifest envelope (not the wrapped JSON Schema)
# changes shape in a backwards-incompatible way.
MANIFEST_VERSION = "1.0.0"


class ExtensionMetadata(BaseModel):
    """Identity + provenance of the extension being described."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    uri: str = Field(
        ...,
        description=(
            "Stable URI used in ``AgentCard.capabilities.extensions[].uri``. "
            "MUST match the location at which this manifest is hosted."
        ),
    )
    name: str = Field(..., description="Human-readable protocol name")
    description: Optional[str] = Field(default=None)
    version: str = Field(
        ...,
        description=(
            "Semver of the protocol version this manifest describes. "
            "Distinct from manifest_version which versions the envelope."
        ),
    )
    publisher: Optional[str] = Field(
        default=None,
        description="Author or maintaining organization (DID or URL).",
    )
    human_readable_spec: Optional[str] = Field(
        default=None,
        description=(
            "URL of the human-readable specification (e.g. a Zenodo DOI or a published paper)."
        ),
    )
    machine_readable_spec: Optional[str] = Field(
        default=None,
        description=(
            "URL of a machine-readable spec (proto file, OpenAPI, etc.). "
            "Optional; the manifest itself already carries the JSON "
            "Schema."
        ),
    )


class WireArtefact(BaseModel):
    """One wire-format artefact the protocol exchanges at runtime.

    Each artefact pairs a JSON Schema (for validating message bodies)
    with the name of the field on the AgentCard payload that carries
    the endpoint URL where the artefact is delivered. Together they
    let a validator both check observed traffic AND know where it
    SHOULD have been delivered.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: str = Field(..., description="Artefact name (e.g. 'OutcomeEvent').")
    description: Optional[str] = Field(default=None)
    endpoint_field: Optional[str] = Field(
        default=None,
        description=(
            "Field path within ``agent_card_payload_schema`` whose value "
            "is the HTTPS URL where this artefact is POSTed. Use dotted "
            "notation for nested fields. Example: 'outcome_endpoint'."
        ),
    )
    method: str = Field(
        default="POST",
        description="HTTP method used to deliver the artefact.",
    )
    json_schema: dict = Field(
        ...,
        description=(
            "JSON Schema that validates the artefact body. Same schema "
            "draft as agent_card_payload_schema."
        ),
        alias="schema",
    )


class ExtensionManifest(BaseModel):
    """Self-describing manifest for one A2A capabilities extension.

    Hosted at ``<extension_uri>/manifest.json`` (or a similar
    well-known path). Validators fetch the manifest once per URI,
    cache it, and then validate AgentCard payloads + wire traffic
    against the contained schemas without any protocol-specific code.
    """

    model_config = ConfigDict(populate_by_name=True)

    manifest_version: str = Field(
        default=MANIFEST_VERSION,
        description=("Semver of the manifest envelope. Validators reject unknown major versions."),
    )
    extension: ExtensionMetadata
    agent_card_payload_schema: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "title": "OpaquePayload",
            "description": (
                "This extension declares itself by URI presence and does "
                "not constrain the AgentCard payload. Validators accept "
                "any object."
            ),
            "additionalProperties": True,
        },
        description=(
            "JSON Schema for the payload of the "
            "``capabilities.extensions[]`` entry whose ``uri`` equals "
            "``extension.uri``. Typically generated from a pydantic "
            "model via ``.model_json_schema()``. Extensions that augment "
            "runtime behavior without adding card fields MAY use the "
            "default permissive schema."
        ),
    )
    wire_artefacts: list[WireArtefact] = Field(
        default_factory=list,
        description=(
            "Optional descriptors for each runtime artefact the protocol "
            "exchanges (request/response bodies). Empty when the "
            "extension only declares static AgentCard fields."
        ),
    )
    invariants: list[str] = Field(
        default_factory=list,
        description=(
            "Optional human-readable invariants the protocol enforces "
            "(e.g. 'OE-1: every terminal task MUST produce exactly one "
            "OutcomeEvent'). For documentation only; validators rely on "
            "the schemas above for machine checking."
        ),
    )
