# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for core/loader.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from a2a_testbed.core.loader import (
    AgentCardLoadError,
    declared_extension_uris,
    load_agent_card_from_path,
    required_extension_uris,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples" / "agent-cards" / "three-party"


def test_load_alice():
    card = load_agent_card_from_path(EXAMPLES / "alice.json")
    assert card.name == "Alice"
    assert card.version == "1.0.0"


def test_carol_declares_four_extensions():
    card = load_agent_card_from_path(EXAMPLES / "carol.json")
    extensions = declared_extension_uris(card)
    assert len(extensions) == 4
    assert any("agent-consent-protocol" in u for u in extensions)


def test_required_extensions_carol():
    card = load_agent_card_from_path(EXAMPLES / "carol.json")
    required = required_extension_uris(card)
    # All 4 of carol's extensions are required:true
    assert len(required) == 4


def test_required_extensions_alice():
    card = load_agent_card_from_path(EXAMPLES / "alice.json")
    required = required_extension_uris(card)
    # ACAP and PACE are required:true; Phala is required:false
    assert len(required) == 2


def test_missing_file_raises():
    with pytest.raises(AgentCardLoadError, match="not found"):
        load_agent_card_from_path("/nonexistent.json")


def test_invalid_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not JSON {{", encoding="utf-8")
    with pytest.raises(AgentCardLoadError, match="invalid JSON"):
        load_agent_card_from_path(bad)


def test_schema_mismatch_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"completely": "wrong"}), encoding="utf-8")
    with pytest.raises(AgentCardLoadError, match="schema mismatch"):
        load_agent_card_from_path(bad)
