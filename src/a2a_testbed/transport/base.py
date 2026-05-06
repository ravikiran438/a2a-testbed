# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport protocol — wire-format abstraction for the testbed.

The orchestration layer (scenario runner, network, observers, faults,
time controller) interacts with agents only through ``Transport``,
never through A2A primitives directly. A different inter-agent
protocol is added by implementing one ``Transport`` subclass; the
rest of the testbed works untouched.

The default implementation is ``A2ATransport`` (in
``a2a_transport.py``), which wraps ``a2a-sdk`` for AgentCard parsing
and JSON-RPC message delivery. Alternative transports (e.g. ACP, an
extended MCP, or a vendor-specific protocol) plug in at this seam
without rewriting the orchestrator.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentDescriptor:
    """Transport-agnostic identifying information about an agent.

    Each transport defines what payload its `card_payload` carries — for
    A2A it's an `a2a.types.AgentCard` protobuf; for a hypothetical
    future protocol it could be JSON-LD, a custom protobuf, or anything
    else. The orchestrator treats it opaquely.
    """

    agent_id: str
    base_url: str
    card_payload: Any
    extension_uris: list[str] = field(default_factory=list)
    required_extension_uris: list[str] = field(default_factory=list)


@dataclass
class WireMessage:
    """A protocol-agnostic message envelope used by the orchestrator.

    Each transport translates this into and out of its own wire format.
    The orchestrator's scenario runner only constructs and reads
    ``WireMessage`` objects.
    """

    sender_id: str
    receiver_id: str
    action_label: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WireResponse:
    """The response side of a single protocol exchange."""

    status: int
    body_text: str
    structured: Optional[dict[str, Any]] = None


class Transport(abc.ABC):
    """Wire-format-agnostic surface the orchestrator sees.

    Subclasses translate between the testbed's protocol-agnostic
    `WireMessage` / `WireResponse` and their own protocol's wire
    format. They also know how to:
      - Serve an agent's descriptor at a well-known URL.
      - Construct the address an orchestrator will POST to.
      - Parse the response body the agent returns.

    Implementations must be thread-safe; the multitenant network
    instantiates one Transport per scenario and reuses it across
    concurrent steps.
    """

    name: str = "abstract"

    @abc.abstractmethod
    def card_endpoint_path(self) -> str:
        """Relative path the agent serves its descriptor at, e.g. /.well-known/agent-card.json."""

    @abc.abstractmethod
    def rpc_endpoint_path(self) -> str:
        """Relative path the agent listens on for messages, e.g. /a2a/v1/."""

    @abc.abstractmethod
    def encode_request(self, message: WireMessage) -> dict[str, Any]:
        """Translate a `WireMessage` into the protocol's request body."""

    @abc.abstractmethod
    def decode_response(self, raw_body: str, status: int) -> WireResponse:
        """Translate a raw HTTP body into a protocol-agnostic response."""

    @abc.abstractmethod
    def serialize_card(self, card_payload: Any) -> dict[str, Any]:
        """Render the agent's card payload as a JSON-friendly dict for HTTP serving."""

    @abc.abstractmethod
    def parse_card_text(self, raw: str) -> Any:
        """Parse a card JSON string back into the protocol's native card type."""

    @abc.abstractmethod
    def extract_text_for_scripting(self, request_body: dict[str, Any]) -> str:
        """Pull out the text the in-process executor scripts match against."""

    @abc.abstractmethod
    def build_response(
        self,
        request_body: dict[str, Any],
        agent_id: str,
        response_text: str,
    ) -> dict[str, Any]:
        """Construct the response body the in-process executor returns."""

    @abc.abstractmethod
    def build_error_response(
        self,
        request_body: dict[str, Any],
        code: int,
        message: str,
    ) -> dict[str, Any]:
        """Construct a protocol-native error response."""
