# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for the Transport abstraction and the A2A implementation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from a2a_testbed.core.loader import load_agent_card_from_path
from a2a_testbed.transport import (
    A2ATransport,
    Transport,
    WireMessage,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
THREE_PARTY = REPO_ROOT / "examples" / "agent-cards" / "three-party"


def test_a2a_transport_name():
    assert A2ATransport().name == "a2a-1.0"


def test_a2a_transport_satisfies_protocol():
    t = A2ATransport()
    assert isinstance(t, Transport)


def test_endpoint_paths():
    t = A2ATransport()
    assert t.card_endpoint_path() == "/.well-known/agent-card.json"
    assert t.rpc_endpoint_path() == "/a2a/v1/"


def test_encode_request_round_trip():
    t = A2ATransport()
    msg = WireMessage(
        sender_id="alice",
        receiver_id="bob",
        action_label="ping",
        text="hello",
    )
    body = t.encode_request(msg)
    assert body["jsonrpc"] == "2.0"
    # A2A 1.0 by default: PascalCase method, oneof Part, ROLE_* enum.
    assert body["method"] == "SendMessage"
    assert body["params"]["message"]["parts"][0] == {"text": "hello"}
    assert body["params"]["message"]["role"] == "ROLE_USER"
    assert body["params"]["configuration"]["returnImmediately"] is False
    assert t.request_headers() == {"A2A-Version": "1.0"}


def test_encode_request_legacy_0_3():
    t = A2ATransport()
    msg = WireMessage(sender_id="a", receiver_id="b", action_label="ping", text="hello")
    body = t.encode_request(msg, protocol_version="0.3")
    assert body["method"] == "message/send"
    assert body["params"]["message"]["parts"][0] == {"kind": "text", "text": "hello"}
    assert body["params"]["message"]["role"] == "user"
    assert body["params"]["configuration"]["blocking"] is True
    # 0.3 clients send no A2A-Version header (absent = 0.3, §3.6.2).
    assert t.request_headers("0.3") == {}


def test_encode_request_uses_metadata_ids_when_provided():
    t = A2ATransport()
    msg = WireMessage(
        sender_id="alice",
        receiver_id="bob",
        action_label="ping",
        text="hello",
        metadata={"request_id": "REQ", "message_id": "MSG"},
    )
    body = t.encode_request(msg)
    assert body["id"] == "REQ"
    assert body["params"]["message"]["messageId"] == "MSG"


def test_decode_response_parses_json_when_possible():
    t = A2ATransport()
    raw = '{"jsonrpc":"2.0","id":"1","result":{"x":1}}'
    response = t.decode_response(raw, 200)
    assert response.status == 200
    assert response.body_text == raw
    assert response.structured == {"jsonrpc": "2.0", "id": "1", "result": {"x": 1}}


def test_decode_response_handles_non_json_body():
    t = A2ATransport()
    response = t.decode_response("not json", 500)
    assert response.status == 500
    assert response.structured is None


def test_serialize_card_round_trip():
    t = A2ATransport()
    card = load_agent_card_from_path(THREE_PARTY / "alice.json")
    serialized = t.serialize_card(card)
    assert serialized["name"] == "Alice"
    # Round-trip back through parse
    parsed = t.parse_card_text(json.dumps(serialized))
    assert parsed.name == "Alice"


def test_extract_text_for_scripting():
    t = A2ATransport()
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "m1",
                "role": "user",
                "parts": [
                    {"kind": "text", "text": "request_consent for delivery"},
                    {"kind": "text", "text": " please"},
                ],
            }
        },
    }
    text = t.extract_text_for_scripting(request)
    assert text == "request_consent for delivery  please"


def test_extract_text_handles_missing_fields():
    t = A2ATransport()
    assert t.extract_text_for_scripting({}) == ""
    assert t.extract_text_for_scripting({"params": {}}) == ""
    assert t.extract_text_for_scripting({"params": {"message": {}}}) == ""


def test_build_response_shape():
    t = A2ATransport()
    request = {"jsonrpc": "2.0", "id": "42", "method": "SendMessage", "params": {}}
    response = t.build_response(request, "bob", "[bob] ack")
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "42"
    # SendMessageResponse oneof (A2A 1.0 §9.4.1).
    assert set(response["result"]) == {"message"}
    message = response["result"]["message"]
    assert message["role"] == "ROLE_AGENT"
    assert message["parts"] == [{"text": "[bob] ack"}]
    assert message["messageId"] == "resp-42"


def test_build_response_shape_legacy_0_3():
    """A legacy method name gets a legacy-shaped reply (bare Message with kind)."""
    t = A2ATransport()
    request = {"jsonrpc": "2.0", "id": "42", "method": "message/send", "params": {}}
    result = t.build_response(request, "bob", "[bob] ack")["result"]
    assert result["kind"] == "message"
    assert result["role"] == "agent"
    assert result["parts"] == [{"kind": "text", "text": "[bob] ack"}]


def test_build_error_response_shape():
    t = A2ATransport()
    request = {"jsonrpc": "2.0", "id": "9", "method": "x"}
    response = t.build_error_response(request, -32601, "no")
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "9"
    assert response["error"]["code"] == -32601
    # error.data entries are ProtoJSON Any objects (A2A 1.0 §9.5).
    assert response["error"]["data"][0]["@type"].endswith("google.rpc.ErrorInfo")
    assert response["error"]["data"][0]["reason"] == "METHOD_NOT_FOUND"
    assert response["error"]["message"] == "no"


def test_serialize_card_rejects_non_agent_card():
    t = A2ATransport()
    with pytest.raises(TypeError, match="AgentCard"):
        t.serialize_card({"name": "not a real card"})


# ---------------------------------------------------------------------------
# In-process JSON-RPC server (A2ATransport.handle_rpc)
# ---------------------------------------------------------------------------

MIXED = REPO_ROOT / "examples" / "agent-cards" / "mixed-versions"


def _rpc(method, params=None, rid="1"):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def _send(t, card, method, message, headers=None):
    return t.handle_rpc(
        _rpc(method, {"message": message}),
        headers or {},
        card,
        lambda text: f"echo: {text}",
        "agent",
    )


V1_MSG = {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": "hi"}]}
V03_MSG = {"messageId": "m", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}


def test_v1_agent_answers_send_message_in_v1_shape():
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "modern.json")
    out = _send(t, card, "SendMessage", V1_MSG, {"A2A-Version": "1.0"})
    assert out["result"]["message"]["parts"] == [{"text": "echo: hi"}]


def test_v1_agent_requires_version_header_for_v1_methods():
    """§3.6.2: an absent A2A-Version means 0.3, which has no SendMessage."""
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "modern.json")
    out = _send(t, card, "SendMessage", V1_MSG)
    assert out["error"]["code"] == -32009


def test_v1_agent_still_serves_v03_callers():
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "modern.json")
    out = _send(t, card, "message/send", V03_MSG)
    assert out["result"]["kind"] == "message"
    assert out["result"]["parts"] == [{"kind": "text", "text": "echo: hi"}]


def test_unsupported_version_header_is_rejected():
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "modern.json")
    out = _send(t, card, "message/send", V03_MSG, {"A2A-Version": "99.0"})
    assert out["error"]["code"] == -32009


def test_v03_agent_does_not_know_v1_methods():
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "legacy.json")
    assert _send(t, card, "SendMessage", V1_MSG, {"A2A-Version": "1.0"})["error"]["code"] == -32601
    assert _send(t, card, "message/send", V03_MSG)["result"]["kind"] == "message"


@pytest.mark.parametrize(
    ("method", "params", "code"),
    [
        ("SendStreamingMessage", {"message": V1_MSG}, -32004),  # streaming=false
        ("SubscribeToTask", {"id": "t"}, -32004),
        ("CreateTaskPushNotificationConfig", {"taskId": "t", "url": "https://h"}, -32003),
        ("GetExtendedAgentCard", {}, -32004),
        ("GetTask", {"id": "t"}, -32001),  # message-only agent: no tasks exist
        ("CancelTask", {"id": "t"}, -32001),
        ("GetTask", {}, -32602),
        ("NoSuchMethod", {}, -32601),
    ],
)
def test_in_process_agent_error_semantics(method, params, code):
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "modern.json")
    out = t.handle_rpc(_rpc(method, params), {"A2A-Version": "1.0"}, card, str, "agent")
    assert out["error"]["code"] == code, out


def test_in_process_agent_lists_no_tasks():
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "modern.json")
    out = t.handle_rpc(_rpc("ListTasks"), {"A2A-Version": "1.0"}, card, str, "agent")
    assert out["result"]["tasks"] == []


def test_malformed_message_is_invalid_params():
    t = A2ATransport()
    card = load_agent_card_from_path(MIXED / "modern.json")
    out = _send(
        t, card, "SendMessage", {"messageId": "m", "role": "ROLE_USER"}, {"A2A-Version": "1.0"}
    )
    assert out["error"]["code"] == -32602


def test_serialize_card_keeps_each_cards_own_layout():
    t = A2ATransport()
    legacy = t.serialize_card(load_agent_card_from_path(MIXED / "legacy.json"))
    assert legacy["url"] == "http://127.0.0.1:0" and "supportedInterfaces" not in legacy
    modern = t.serialize_card(load_agent_card_from_path(MIXED / "modern.json"))
    assert modern["supportedInterfaces"][0]["protocolVersion"] == "1.0"


def test_pinned_protocol_version():
    assert (
        A2ATransport().protocol_version_for_card({"url": "x", "protocolVersion": "0.3.0"}) == "0.3"
    )
    assert A2ATransport(protocol_version="0.3").protocol_version_for_card({}) == "0.3"
    with pytest.raises(ValueError):
        A2ATransport(protocol_version="2.0")
