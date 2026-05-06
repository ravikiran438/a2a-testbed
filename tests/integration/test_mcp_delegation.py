# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""End-to-end test for MCP delegation.

Spawns a real Phala MCP server via stdio, hands it a Phala-shaped
card, and asserts the testbed receives a passing finding from
``validate_phala_service_ref``. Also covers the negative path: a
malformed payload yields a ``failed`` finding (not a crash).
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from a2a_testbed.extensions import (
    MCPDelegate,
    MCPDelegateRegistry,
    MCPFindingKind,
    delegate_validate_card,
    make_default_registry,
)


def _phala_card(*, broken: bool = False) -> dict:
    params = {
        "version": "1.0.0",
        "outcome_endpoint": "https://x/o",
        "satisfaction_endpoint": "https://x/s",
        "belief_update_endpoint": "https://x/b",
        "weight_keys": ["k"],
        "learning_rate": 0.05,
        "weight_bounds": {"min": -1.0, "max": 1.0},
    }
    if broken:
        del params["belief_update_endpoint"]
    return {
        "name": "demo",
        "capabilities": {
            "extensions": [
                {
                    "uri": "https://ravikiran438.github.io/phala-protocol/v1",
                    "params": params,
                }
            ]
        },
    }


def _phala_only_registry() -> MCPDelegateRegistry:
    """A registry containing only the Phala delegate, using the current
    Python interpreter for the spawn command (so the test works with
    the shared venv layout)."""
    reg = MCPDelegateRegistry()
    reg.register(
        MCPDelegate(
            extension_uri="https://ravikiran438.github.io/phala-protocol/v1",
            command=(sys.executable, "-m", "phala.mcp_server"),
            payload_validator_tool="validate_phala_service_ref",
            payload_arg_name="ref",
        )
    )
    return reg


def _is_mcp_present() -> bool:
    try:
        import mcp  # noqa: F401
        import phala  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _is_mcp_present(),
    reason="requires mcp + phala packages to be importable",
)
def test_phala_mcp_delegation_passes_for_valid_card():
    findings = asyncio.run(
        delegate_validate_card(_phala_card(), registry=_phala_only_registry())
    )
    assert len(findings) == 1, [f.detail for f in findings]
    assert findings[0].kind == MCPFindingKind.PASSED, findings[0].detail
    assert findings[0].tool_name == "validate_phala_service_ref"


@pytest.mark.skipif(
    not _is_mcp_present(),
    reason="requires mcp + phala packages to be importable",
)
def test_phala_mcp_delegation_fails_for_broken_card():
    findings = asyncio.run(
        delegate_validate_card(
            _phala_card(broken=True), registry=_phala_only_registry()
        )
    )
    assert len(findings) == 1
    assert findings[0].kind == MCPFindingKind.FAILED


def test_unregistered_uri_is_silently_skipped():
    """Extensions without a registered delegate produce no MCP findings;
    the manifest layer is responsible for those."""
    reg = MCPDelegateRegistry()  # empty
    card = _phala_card()
    findings = asyncio.run(delegate_validate_card(card, registry=reg))
    assert findings == []


def test_default_registry_includes_all_four_protocols():
    """All four reference protocols ship a card-payload validator tool;
    the default registry covers each of them."""
    reg = make_default_registry()
    for uri in (
        "https://ravikiran438.github.io/agent-consent-protocol/v1",
        "https://ravikiran438.github.io/phala-protocol/v1",
        "https://ravikiran438.github.io/pratyahara-nerve/v1",
        "https://ravikiran438.github.io/sauvidya-pace/v1",
    ):
        assert reg.get(uri) is not None, uri


def _is_acap_present() -> bool:
    try:
        import mcp  # noqa: F401
        import acap  # noqa: F401
        return True
    except ImportError:
        return False


def _acap_card(*, broken: bool = False) -> dict:
    params = {
        "version": "1.0.0",
        "document_uri": "https://callee.example.com/.well-known/usage-policy.json",
        "document_hash": "sha256:" + "a" * 64,
        "effective_date": "2026-04-01T00:00:00Z",
        "acceptance_required": False,
        "natural_language_uri": "https://callee.example.com/terms",
    }
    if broken:
        params["acceptance_required"] = True
        # acceptance_endpoint deliberately omitted — should fail V-3-style coherence.
    return {
        "name": "demo",
        "capabilities": {
            "extensions": [
                {
                    "uri": "https://ravikiran438.github.io/agent-consent-protocol/v1",
                    "params": params,
                }
            ]
        },
    }


def _acap_only_registry() -> MCPDelegateRegistry:
    reg = MCPDelegateRegistry()
    reg.register(
        MCPDelegate(
            extension_uri="https://ravikiran438.github.io/agent-consent-protocol/v1",
            command=(sys.executable, "-m", "acap.mcp_server"),
            payload_validator_tool="validate_usage_policy_ref",
            payload_arg_name="ref",
        )
    )
    return reg


@pytest.mark.skipif(
    not _is_acap_present(),
    reason="requires mcp + acap packages to be importable",
)
def test_acap_mcp_delegation_passes_for_valid_card():
    findings = asyncio.run(
        delegate_validate_card(_acap_card(), registry=_acap_only_registry())
    )
    assert len(findings) == 1, [f.detail for f in findings]
    assert findings[0].kind == MCPFindingKind.PASSED, findings[0].detail


@pytest.mark.skipif(
    not _is_acap_present(),
    reason="requires mcp + acap packages to be importable",
)
def test_acap_mcp_delegation_fails_when_acceptance_endpoint_missing():
    findings = asyncio.run(
        delegate_validate_card(
            _acap_card(broken=True), registry=_acap_only_registry()
        )
    )
    assert findings[0].kind == MCPFindingKind.FAILED
    assert "acceptance_endpoint" in findings[0].detail.lower() or \
        "acceptance_endpoint" in (findings[0].raw_response or "").lower()
