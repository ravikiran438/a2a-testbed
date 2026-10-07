# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""A2A transport implementation.

Translates between the testbed's protocol-agnostic
`WireMessage` / `WireResponse` and A2A's JSON-RPC over HTTP +
AgentCard JSON wire format.

Speaks A2A 1.0 by default and 0.3 for agents whose card advertises it
(see :mod:`a2a_testbed.transport.dialect`). The in-process server side
(:meth:`A2ATransport.handle_rpc`) answers each request in the dialect
it was made in, so testbed-hosted agents serve 1.0 and 0.3 clients
from one endpoint — the same arrangement as the a2a-sdk's
``enable_v0_3_compat``.

This is the only place A2A-specific code lives outside the loader.
Other parts of the testbed import only from ``transport.base``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from typing import Any, Optional

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict, Parse, ParseDict

from a2a_testbed.transport import dialect as d
from a2a_testbed.transport.base import (
    Transport,
    WireMessage,
    WireResponse,
)

# google.rpc.ErrorInfo reasons for the error codes the testbed emits
# (A2A 1.0 §5.4 / §9.5).
_ERROR_REASONS = {
    -32001: "TASK_NOT_FOUND",
    -32002: "TASK_NOT_CANCELABLE",
    -32003: "PUSH_NOTIFICATION_NOT_SUPPORTED",
    -32004: "UNSUPPORTED_OPERATION",
    -32005: "CONTENT_TYPE_NOT_SUPPORTED",
    -32007: "EXTENDED_AGENT_CARD_NOT_CONFIGURED",
    -32009: "VERSION_NOT_SUPPORTED",
    -32600: "INVALID_REQUEST",
    -32601: "METHOD_NOT_FOUND",
    -32602: "INVALID_PARAMS",
    -32603: "INTERNAL_ERROR",
    -32700: "JSON_PARSE_ERROR",
}


def _dialect(protocol_version: Optional[str]) -> d.Dialect:
    if protocol_version and protocol_version.startswith("0."):
        return d.Dialect.V0_3
    return d.Dialect.V1_0


class A2ATransport(Transport):
    """A2A 1.0 (with 0.3 compatibility) over HTTP+JSON-RPC."""

    name = "a2a-1.0"

    def __init__(self, protocol_version: Optional[str] = None) -> None:
        """``protocol_version`` pins the client-side wire revision
        (``"1.0"`` / ``"0.3"``) instead of negotiating it from each
        agent's card — e.g. to sweep the 0.3 surface of an agent that
        serves both."""
        if protocol_version not in (None, d.Dialect.V1_0.value, d.Dialect.V0_3.value):
            raise ValueError(
                f"unsupported A2A protocol version {protocol_version!r}; "
                f"expected '{d.Dialect.V1_0.value}' or '{d.Dialect.V0_3.value}'"
            )
        self.pinned_protocol_version = protocol_version

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def card_endpoint_path(self) -> str:
        return "/.well-known/agent-card.json"

    def rpc_endpoint_path(self) -> str:
        return "/a2a/v1/"

    # ------------------------------------------------------------------
    # Version negotiation (client side)
    # ------------------------------------------------------------------

    def request_headers(self, protocol_version: Optional[str] = None) -> dict[str, str]:
        return d.request_headers(_dialect(protocol_version))

    def protocol_version_for_card(self, card_json: Any) -> Optional[str]:
        if self.pinned_protocol_version:
            return self.pinned_protocol_version
        return d.detect_dialect(card_json).value

    def protocol_version_for_proto_card(self, card: Any) -> str:
        return d.dialect_of_proto_card(card).value

    # ------------------------------------------------------------------
    # Request encoding / response decoding
    # ------------------------------------------------------------------

    def encode_request(
        self, message: WireMessage, *, protocol_version: Optional[str] = None
    ) -> dict[str, Any]:
        dialect = _dialect(protocol_version)
        request_id = message.metadata.get("request_id") or str(uuid.uuid4())
        message_id = message.metadata.get("message_id") or str(uuid.uuid4())
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": d.method(dialect, "send"),
            "params": d.send_params(
                dialect,
                d.text_message(dialect, message.text, message_id=message_id),
                blocking=True,
            ),
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
        """Render a card for HTTP serving, in the layout of its own version.

        A card whose JSON-RPC interfaces are all 0.x is served in the 0.3
        layout, so a scenario can host a faithful legacy agent; a 1.0
        card that also lists a 0.x interface is served with the 0.3
        fields merged in.
        """
        if not isinstance(card_payload, AgentCard):
            raise TypeError(
                f"A2ATransport.serialize_card expects AgentCard, got {type(card_payload).__name__}"
            )
        if d.dialect_of_proto_card(card_payload) is d.Dialect.V0_3:
            return d.card_to_v03_json(card_payload)
        if d.card_lists_v03_interface(card_payload):
            # A 1.0 card that also advertises a 0.3 interface carries the
            # 0.3 top-level fields too, so 0.3 clients can read it — the
            # same merge the a2a-sdk's card route performs.
            from a2a.server.request_handlers.response_helpers import agent_card_to_dict

            return agent_card_to_dict(card_payload)
        return MessageToDict(card_payload, preserving_proto_field_name=False)

    def parse_card_text(self, raw: str) -> Any:
        """Parse card JSON into an ``a2a.types.AgentCard``.

        0.3 cards are converted with the a2a-sdk compat layer; the
        result's interfaces keep their 0.x ``protocolVersion`` so the
        testbed still knows to speak 0.3 to that agent.
        """
        try:
            as_json = json.loads(raw)
        except json.JSONDecodeError:
            as_json = None
        if d.card_is_v03(as_json):
            from a2a.compat.v0_3 import conversions
            from a2a.compat.v0_3 import types as types_v03

            return conversions.to_core_agent_card(types_v03.AgentCard.model_validate(as_json))
        if not isinstance(as_json, dict):
            return Parse(raw, AgentCard())  # raises a ParseError with the JSON problem
        # Unknown fields are ignored (spec: implementations SHOULD ignore
        # unrecognized fields), like the a2a-sdk's own card resolver: an
        # SDK agent serving 1.0 and 0.3 merges the 0.3 top-level fields
        # (url, protocolVersion, preferredTransport, …) into its 1.0 card.
        return ParseDict(as_json, AgentCard(), ignore_unknown_fields=True)

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
        """A reply Message, in the dialect the request was made in."""
        request_id = request_body.get("id") if isinstance(request_body, dict) else None
        found = d.dialect_for_method(
            request_body.get("method") if isinstance(request_body, dict) else None
        )
        dialect = found[0] if found else d.CURRENT
        params = request_body.get("params") if isinstance(request_body, dict) else None
        incoming = params.get("message") if isinstance(params, dict) else None
        context_id = incoming.get("contextId") if isinstance(incoming, dict) else None
        reply = d.text_message(
            dialect,
            response_text,
            role="agent",
            message_id=f"resp-{request_id}",
            context_id=context_id if isinstance(context_id, str) else None,
        )
        result = {"message": reply} if dialect is d.Dialect.V1_0 else reply
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def build_error_response(
        self,
        request_body: dict[str, Any],
        code: int,
        message: str,
    ) -> dict[str, Any]:
        request_id = request_body.get("id") if isinstance(request_body, dict) else None
        error: dict[str, Any] = {"code": code, "message": message}
        reason = _ERROR_REASONS.get(code)
        if reason:
            # A2A 1.0 §9.5: error.data is an array of ProtoJSON Any objects.
            error["data"] = [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": reason,
                    "domain": "a2a-protocol.org",
                    "metadata": {},
                }
            ]
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    # ------------------------------------------------------------------
    # In-process JSON-RPC server
    # ------------------------------------------------------------------

    def handle_rpc(
        self,
        body: Any,
        headers: Mapping[str, str],
        card: Any,
        script_for: Callable[[str], str],
        agent_id: str,
    ) -> dict[str, Any]:
        """Answer one JSON-RPC request for a testbed-hosted agent.

        Testbed agents are message-only echo agents (they reply with a
        Message and never create Tasks), so:

        - ``SendMessage`` / ``message/send`` reply with the scripted text;
        - task lookups return TaskNotFound, ``ListTasks`` an empty page;
        - streaming, push and extended-card operations return the
          capability errors the spec mandates when the card does not
          advertise them (§3.3.4).

        A 1.0 card serves both dialects (1.0 requests must carry
        ``A2A-Version: 1.x``, per §3.6.2 an absent header means 0.3);
        a 0.3 card serves only 0.3, like a pre-1.0 agent would.
        """
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            return self.build_error_response(
                body if isinstance(body, dict) else {},
                -32600,
                "invalid request: expected a JSON-RPC 2.0 request object",
            )
        found = d.dialect_for_method(body.get("method"))
        agent_dialect = d.dialect_of_proto_card(card)
        if found is None or (found[0] is d.Dialect.V1_0 and agent_dialect is d.Dialect.V0_3):
            return self.build_error_response(
                body, -32601, f"method not found: {body.get('method')!r}"
            )
        req_dialect, op = found
        version_header = _header(headers, d.VERSION_HEADER)
        if (
            req_dialect is d.Dialect.V1_0
            and d.parse_version_header(version_header) is not d.Dialect.V1_0
        ):
            return self.build_error_response(
                body,
                -32009,
                f"A2A-Version {version_header or '(absent = 0.3)'} does not support "
                f"{body.get('method')}; send A2A-Version: 1.0",
            )
        if not d.version_supported(version_header):
            return self.build_error_response(
                body, -32009, f"A2A-Version {version_header} not supported"
            )

        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        caps = card.capabilities if card is not None and card.HasField("capabilities") else None
        if op == "send":
            message = params.get("message")
            valid = (
                isinstance(message, dict)
                and message.get("role")
                and message.get("messageId")
                and isinstance(message.get("parts"), list)
                and len(message["parts"]) > 0
            )
            if not valid:
                return self.build_error_response(
                    body,
                    -32602,
                    "invalid params: message MUST have role, messageId, and ≥1 part (A2A 1.0 §3.1.1)",
                )
            text = self.extract_text_for_scripting(body)
            return self.build_response(body, agent_id, script_for(text))
        if op == "stream" or (op == "subscribe" and (caps is None or not caps.streaming)):
            # In-process agents cannot stream, whatever their card says.
            return self.build_error_response(
                body, -32004, "streaming is not supported by this agent"
            )
        if op == "subscribe":
            return self.build_error_response(body, -32001, "task not found")
        if op.startswith("push_"):
            if caps is None or not caps.push_notifications:
                return self.build_error_response(
                    body, -32003, "push notifications are not supported by this agent"
                )
            return self.build_error_response(body, -32001, "task not found")
        if op == "extended_card":
            if caps is None or not caps.extended_agent_card:
                return self.build_error_response(
                    body, -32004, "this agent does not support an extended agent card"
                )
            return self.build_error_response(body, -32007, "extended agent card is not configured")
        if op == "list":
            if req_dialect is d.Dialect.V0_3:
                return self.build_error_response(body, -32601, "method not found: 'tasks/list'")
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {"tasks": [], "nextPageToken": "", "pageSize": 0, "totalSize": 0},
            }
        if not isinstance(params.get("id"), str) or not params.get("id"):
            return self.build_error_response(body, -32602, "invalid params: id is required")
        # get / cancel: this agent never creates tasks.
        return self.build_error_response(body, -32001, f"task {params['id']} not found")


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return value
