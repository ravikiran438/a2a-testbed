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
    assert body["method"] == "message/send"
    assert body["params"]["message"]["parts"][0]["text"] == "hello"
    assert body["params"]["configuration"]["blocking"] is True


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
    request = {"jsonrpc": "2.0", "id": "42", "method": "message/send", "params": {}}
    response = t.build_response(request, "bob", "[bob] ack")
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "42"
    assert response["result"]["role"] == "assistant"
    assert response["result"]["parts"][0]["text"] == "[bob] ack"
    assert response["result"]["messageId"] == "resp-42"


def test_build_error_response_shape():
    t = A2ATransport()
    request = {"jsonrpc": "2.0", "id": "9", "method": "x"}
    response = t.build_error_response(request, -32601, "no")
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "9"
    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "no"


def test_serialize_card_rejects_non_agent_card():
    t = A2ATransport()
    with pytest.raises(TypeError, match="AgentCard"):
        t.serialize_card({"name": "not a real card"})
