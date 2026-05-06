# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for the SPEC.md generator (paper-code sync helper)."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from a2a_testbed.manifest import (
    ExtensionManifest,
    generate_manifest,
    render_spec_md,
)


class _SampleRef(BaseModel):
    version: str = Field(..., description="Protocol semver")
    endpoint: str = Field(..., description="HTTPS data plane URL")
    weight_keys: list[str] = Field(
        default_factory=list,
        description="Stable namespace of accepted weight keys",
    )


def _sample_manifest() -> ExtensionManifest:
    return generate_manifest(
        extension_uri="https://example.org/sample-protocol/v1",
        name="Sample Protocol",
        version="1.0.0",
        ref_class=_SampleRef,
        publisher="Example Corp",
        human_readable_spec="https://doi.example.org/foo",
        invariants=["I-1: every X must be Y"],
    )


def test_spec_md_includes_metadata_block():
    md = render_spec_md(_sample_manifest())
    assert "# Sample Protocol — Wire Specification" in md
    assert "Generated from `v1/manifest.json`" in md
    assert "do not hand-edit" in md
    assert "https://example.org/sample-protocol/v1" in md
    assert "Example Corp" in md
    assert "https://doi.example.org/foo" in md


def test_spec_md_field_table_has_required_marks():
    md = render_spec_md(_sample_manifest())
    assert "| Field | Type | Required | Notes |" in md
    # version is required, weight_keys is not
    assert "`version`" in md
    assert "`endpoint`" in md
    assert "`weight_keys`" in md
    # required line should appear
    assert "**Required fields:**" in md


def test_spec_md_invariants_section():
    md = render_spec_md(_sample_manifest())
    assert "## Invariants" in md
    assert "I-1: every X must be Y" in md


def test_spec_md_opaque_payload_is_clear():
    """Manifests for runtime-only extensions get an OpaquePayload schema;
    the SPEC.md should explicitly say no card fields are constrained."""
    m = generate_manifest(
        extension_uri="https://example.org/runtime-only/v1",
        name="Runtime-Only",
        version="1.0.0",
        # no ref_class -> OpaquePayload
    )
    md = render_spec_md(m)
    assert "does not constrain the AgentCard payload" in md


def test_spec_md_no_publisher_skips_line():
    m = generate_manifest(
        extension_uri="https://example.org/anon/v1",
        name="Anonymous Protocol",
        version="1.0.0",
        ref_class=_SampleRef,
    )
    md = render_spec_md(m)
    # The "**Publisher:**" line should be skipped when the manifest has no publisher.
    assert "**Publisher:**" not in md


# --------------------------------------------------------------------------
# Smoke: render against the four reference manifests published on
# github.io. Fetched over HTTPS — same path any third-party
# validator would take. Skipped when no network is available.
# --------------------------------------------------------------------------


SHIPPED_MANIFEST_URIS = [
    "https://ravikiran438.github.io/agent-consent-protocol/v1",
    "https://ravikiran438.github.io/phala-protocol/v1",
    "https://ravikiran438.github.io/pratyahara-nerve/v1",
    "https://ravikiran438.github.io/sauvidya-pace/v1",
]


@pytest.mark.parametrize("uri", SHIPPED_MANIFEST_URIS)
def test_render_real_manifests(uri):
    import httpx
    manifest_url = uri.rstrip("/") + "/manifest.json"
    try:
        resp = httpx.get(manifest_url, timeout=5.0)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        pytest.skip(f"network unavailable: {exc}")
    if resp.status_code != 200:
        pytest.skip(f"manifest not yet published at {manifest_url}")
    m = ExtensionManifest.model_validate_json(resp.text)
    md = render_spec_md(m)
    # Smoke: title and metadata are present; body parses as markdown.
    assert "# " in md.split("\n", 1)[0]
    assert m.extension.uri in md
    assert "## AgentCard payload" in md
