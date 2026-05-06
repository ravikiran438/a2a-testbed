# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""A2A transport implementation.

Translates between the testbed's protocol-agnostic
`WireMessage` / `WireResponse` and A2A's JSON-RPC over HTTP +
AgentCard JSON wire format.

This is the only place A2A-specific code lives outside the loader.
Other parts of the testbed import only from ``transport.base``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict, Parse

from a2a_testbed.transport.base import (
    Transport,
    WireMessage,
    WireResponse,
)


class A2ATransport(Transport):
    """A2A 1.0 over HTTP+JSON-RPC."""

    name = "a2a-1.0"

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def card_endpoint_path(self) -> str:
        return "/.well-known/agent-card.json"

    def rpc_endpoint_path(self) -> str:
        return "/a2a/v1/"

    # ------------------------------------------------------------------
    # Request encoding / response decoding
    # ------------------------------------------------------------------

    def encode_request(self, message: WireMessage) -> dict[str, Any]:
        request_id = message.metadata.get("request_id") or str(uuid.uuid4())
        message_id = message.metadata.get("message_id") or str(uuid.uuid4())
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": message_id,
                    "role": "user",
                    "parts": [{"kind": "text", "text": message.text}],
                },
                "configuration": {"blocking": True},
            },
        }

    def decode_response(self, raw_body: str, status: int) -> WireResponse:
        try:
            structured = json.loads(raw_body) if raw_body else None
        except json.JSONDecodeError:
            structured = None
        return WireResponse(status=status, body_text=raw_body, structured=structured)

    # ------------------------------------------------------------------
    # Card serialization (AgentCard ↔ JSON)
    # ------------------------------------------------------------------

    def serialize_card(self, card_payload: Any) -> dict[str, Any]:
        if not isinstance(card_payload, AgentCard):
            raise TypeError(
                f"A2ATransport.serialize_card expects AgentCard, got {type(card_payload).__name__}"
            )
        return MessageToDict(card_payload, preserving_proto_field_name=False)

    def parse_card_text(self, raw: str) -> Any:
        return Parse(raw, AgentCard())

    # ------------------------------------------------------------------
    # In-process executor helpers
    # ------------------------------------------------------------------

    def extract_text_for_scripting(self, request_body: dict[str, Any]) -> str:
        params = request_body.get("params") if isinstance(request_body, dict) else None
        if not isinstance(params, dict):
            return ""
        message = params.get("message")
        if not isinstance(message, dict):
            return ""
        parts = message.get("parts") or []
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                t = part.get("text") or ""
                if t:
                    chunks.append(t)
        return " ".join(chunks)

    def build_response(
        self,
        request_body: dict[str, Any],
        agent_id: str,
        response_text: str,
    ) -> dict[str, Any]:
        request_id = request_body.get("id") if isinstance(request_body, dict) else None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "kind": "message",
                "messageId": f"resp-{request_id}",
                "role": "assistant",
                "parts": [{"kind": "text", "text": response_text}],
            },
        }

    def build_error_response(
        self,
        request_body: dict[str, Any],
        code: int,
        message: str,
    ) -> dict[str, Any]:
        request_id = request_body.get("id") if isinstance(request_body, dict) else None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
