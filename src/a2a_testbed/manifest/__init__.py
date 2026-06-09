# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Self-describing extension manifests for A2A protocols.

A2A 1.0's ``capabilities.extensions[].uri`` makes extensions
*declarable* but not *describable*: the URI is opaque, with no
machine-readable schema attached. Validators are forced to hard-code
knowledge of every extension they want to validate.

This module proposes a convention: each extension URI resolves to a
JSON manifest (``ExtensionManifest``) at a well-known path, e.g.::

    GET <extension_uri>/manifest.json

The manifest carries:
  - small metadata block (name, version, links to human-readable spec)
  - a JSON Schema for the AgentCard payload (auto-generated from a
    pydantic model via ``.model_json_schema()``)
  - optional descriptors for wire artefacts (per-message body schemas
    + the field on the AgentCard payload that points to their endpoint)
  - optional human-readable invariants

A generic validator can fetch the manifest, validate the agent's
declared payload against the contained JSON Schema, and even validate
observed wire traffic against the artefact schemas — without ever
importing the protocol's package.

The generator (``generate_manifest``) reduces the cost of authoring a
manifest to a one-line call against the protocol's pydantic ``*Ref``
class, so every protocol that already has typed models gets a manifest
for free.
"""

from a2a_testbed.manifest.generator import generate_manifest
from a2a_testbed.manifest.spec_md import render_spec_md
from a2a_testbed.manifest.store import (
    CompositeManifestStore,
    HttpManifestStore,
    InMemoryManifestStore,
    LocalManifestStore,
    ManifestStore,
    manifest_url_for_uri,
)
from a2a_testbed.manifest.types import (
    MANIFEST_VERSION,
    ExtensionManifest,
    ExtensionMetadata,
    WireArtefact,
)
from a2a_testbed.manifest.validator import (
    SUPPORTED_MANIFEST_MAJOR_VERSIONS,
    Finding,
    FindingKind,
    validate_agent_card,
)


__all__ = [
    "CompositeManifestStore",
    "ExtensionManifest",
    "ExtensionMetadata",
    "Finding",
    "FindingKind",
    "HttpManifestStore",
    "InMemoryManifestStore",
    "LocalManifestStore",
    "MANIFEST_VERSION",
    "ManifestStore",
    "SUPPORTED_MANIFEST_MAJOR_VERSIONS",
    "WireArtefact",
    "generate_manifest",
    "manifest_url_for_uri",
    "render_spec_md",
    "validate_agent_card",
]
