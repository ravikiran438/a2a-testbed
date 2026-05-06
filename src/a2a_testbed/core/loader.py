# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Load A2A AgentCard JSON files into validated `a2a.types.AgentCard` objects.

The official `a2a-sdk` represents AgentCard as a protobuf message, so JSON
parsing routes through `google.protobuf.json_format.Parse`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from a2a.types import AgentCard
from google.protobuf.json_format import Parse, ParseError


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
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentCardLoadError(f"invalid JSON in {p}: {exc}") from exc
    try:
        return Parse(text, AgentCard())
    except ParseError as exc:
        raise AgentCardLoadError(f"AgentCard schema mismatch in {p}: {exc}") from exc


def load_agent_card_from_str(text: str, label: str = "<inline>") -> AgentCard:
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentCardLoadError(f"invalid JSON in {label}: {exc}") from exc
    try:
        return Parse(text, AgentCard())
    except ParseError as exc:
        raise AgentCardLoadError(
            f"AgentCard schema mismatch in {label}: {exc}"
        ) from exc


def declared_extension_uris(card: AgentCard) -> list[str]:
    if not card.HasField("capabilities"):
        return []
    return [ext.uri for ext in card.capabilities.extensions]


def required_extension_uris(card: AgentCard) -> list[str]:
    if not card.HasField("capabilities"):
        return []
    return [ext.uri for ext in card.capabilities.extensions if ext.required]
