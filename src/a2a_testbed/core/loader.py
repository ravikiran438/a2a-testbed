# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Load A2A AgentCard JSON files into validated `a2a.types.AgentCard` objects.

The official `a2a-sdk` represents AgentCard as a protobuf message, so JSON
parsing routes through `google.protobuf.json_format.Parse`.

A2A 0.3 cards (top-level ``url`` / ``protocolVersion`` /
``preferredTransport``) are accepted too: they are validated against the
SDK's 0.3 model and converted with its compat layer. The converted card's
interfaces keep their 0.x ``protocolVersion``, which is how the rest of
the testbed knows to speak 0.3 to that agent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict, ParseError

from a2a_testbed.transport.dialect import card_is_v03


class AgentCardLoadError(ValueError):
    """Raised when an AgentCard JSON file cannot be loaded or validated."""


def load_agent_card_from_path(path: Union[str, Path]) -> AgentCard:
    p = Path(path)
    if not p.exists():
        raise AgentCardLoadError(f"AgentCard file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentCardLoadError(f"could not read {p}: {exc}") from exc
    return load_agent_card_from_str(text, label=str(p))


def load_agent_card_from_str(text: str, label: str = "<inline>") -> AgentCard:
    try:
        as_json = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentCardLoadError(f"invalid JSON in {label}: {exc}") from exc
    if card_is_v03(as_json):
        return _load_v03_card(as_json, label)
    if not isinstance(as_json, dict):
        raise AgentCardLoadError(f"AgentCard in {label} must be a JSON object")
    try:
        # Unknown fields are ignored (the spec says implementations SHOULD),
        # so 1.0 cards that also carry 0.3 fields — as a2a-sdk agents
        # serving both versions publish them — load too.
        card = ParseDict(as_json, AgentCard(), ignore_unknown_fields=True)
    except ParseError as exc:
        raise AgentCardLoadError(f"AgentCard schema mismatch in {label}: {exc}") from exc
    if not card.name:
        # With unknown fields ignored, something that isn't a card at all
        # would otherwise load as an empty one.
        raise AgentCardLoadError(
            f"AgentCard schema mismatch in {label}: required field 'name' is missing"
        )
    return card


def _load_v03_card(as_json: dict, label: str) -> AgentCard:
    from a2a.compat.v0_3 import conversions
    from a2a.compat.v0_3 import types as types_v03
    from pydantic import ValidationError

    try:
        compat = types_v03.AgentCard.model_validate(as_json)
    except ValidationError as exc:
        raise AgentCardLoadError(f"A2A 0.3 AgentCard schema mismatch in {label}: {exc}") from exc
    return conversions.to_core_agent_card(compat)


def declared_extension_uris(card: AgentCard) -> list[str]:
    if not card.HasField("capabilities"):
        return []
    return [ext.uri for ext in card.capabilities.extensions]


def required_extension_uris(card: AgentCard) -> list[str]:
    if not card.HasField("capabilities"):
        return []
    return [ext.uri for ext in card.capabilities.extensions if ext.required]
