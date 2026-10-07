# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""A2A 1.0 / 0.3 dialect handling (``a2a_testbed.transport.dialect``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from a2a.types import a2a_pb2
from google.protobuf.json_format import ParseDict

from a2a_testbed.core.loader import load_agent_card_from_path
from a2a_testbed.transport import dialect as d
from a2a_testbed.transport.dialect import Dialect

REPO_ROOT = Path(__file__).resolve().parents[2]
MIXED = REPO_ROOT / "examples" / "agent-cards" / "mixed-versions"


# ---------------------------------------------------------------------------
# Method names
# ---------------------------------------------------------------------------


def test_v1_methods_are_the_spec_pascal_case_names():
    """A2A 1.0 §9.4 method names, exactly as the a2a-sdk dispatcher registers them."""
    from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher

    assert set(d.METHODS[Dialect.V1_0].values()) == set(JsonRpcDispatcher.METHOD_TO_MODEL)


def test_v03_methods_match_the_sdk_compat_adapter():
    from a2a.compat.v0_3.jsonrpc_adapter import JSONRPC03Adapter

    sdk = set(JSONRPC03Adapter.METHOD_TO_MODEL)
    ours = set(d.METHODS[Dialect.V0_3].values())
    # tasks/list is a pre-1.0 extension (not in the 0.3 spec) kept for agents
    # that implemented it; everything else is the SDK's 0.3 surface.
    assert ours - {"tasks/list"} == sdk


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("SendMessage", (Dialect.V1_0, "send")),
        ("message/send", (Dialect.V0_3, "send")),
        ("tasks/resubscribe", (Dialect.V0_3, "subscribe")),
        ("SubscribeToTask", (Dialect.V1_0, "subscribe")),
        ("no/such", None),
        (None, None),
    ],
)
def test_dialect_for_method(name, expected):
    assert d.dialect_for_method(name) == expected


# ---------------------------------------------------------------------------
# Version header (A2A 1.0 §3.6)
# ---------------------------------------------------------------------------


def test_request_headers():
    assert d.request_headers(Dialect.V1_0) == {"A2A-Version": "1.0"}
    assert d.request_headers(Dialect.V0_3) == {}


@pytest.mark.parametrize(
    ("header", "dialect", "supported"),
    [
        (None, Dialect.V0_3, True),  # absent = 0.3 (§3.6.2)
        ("", Dialect.V0_3, True),
        ("1.0", Dialect.V1_0, True),
        ("1.1", Dialect.V1_0, True),
        ("0.3", Dialect.V0_3, True),
        ("0.3, 1.0", Dialect.V1_0, True),
        ("99.0", Dialect.V0_3, False),
        ("0.2", Dialect.V0_3, False),
    ],
)
def test_version_header_parsing(header, dialect, supported):
    assert d.parse_version_header(header) is dialect
    assert d.version_supported(header) is supported


# ---------------------------------------------------------------------------
# Dialect detection from cards
# ---------------------------------------------------------------------------


def _card(path: Path) -> dict:
    return json.loads(path.read_text())


def test_detect_v1_card():
    assert d.detect_dialect(_card(MIXED / "modern.json")) is Dialect.V1_0


def test_detect_v03_card():
    card = _card(MIXED / "legacy.json")
    assert d.card_is_v03(card)
    assert d.detect_dialect(card) is Dialect.V0_3


def test_unversioned_interface_defaults_to_v1():
    card = {"supportedInterfaces": [{"url": "https://x", "protocolBinding": "JSONRPC"}]}
    assert d.detect_dialect(card) is Dialect.V1_0


def test_dual_version_card_prefers_v1():
    card = {
        "supportedInterfaces": [
            {"url": "https://x", "protocolBinding": "JSONRPC", "protocolVersion": "0.3"},
            {"url": "https://x", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
        ]
    }
    assert d.detect_dialect(card) is Dialect.V1_0


def test_card_listing_only_0x_jsonrpc_interfaces_is_v03():
    card = {
        "supportedInterfaces": [
            {"url": "https://x", "protocolBinding": "JSONRPC", "protocolVersion": "0.3"},
            {"url": "https://x/grpc", "protocolBinding": "GRPC", "protocolVersion": "1.0"},
        ]
    }
    assert d.detect_dialect(card) is Dialect.V0_3


def test_garbage_card_defaults_to_current():
    assert d.detect_dialect(None) is d.CURRENT
    assert d.detect_dialect({}) is d.CURRENT


def test_v03_card_converts_to_v1_layout_via_sdk():
    v1 = d.card_to_v10_json(_card(MIXED / "legacy.json"))
    assert v1["supportedInterfaces"][0] == {
        "url": "http://127.0.0.1:0",
        "protocolBinding": "JSONRPC",
        "protocolVersion": "0.3.0",
    }
    assert "url" not in v1 and "preferredTransport" not in v1
    # The converted card is valid 1.0 ProtoJSON.
    ParseDict(v1, a2a_pb2.AgentCard())


def test_v1_card_passes_through_untouched():
    card = _card(MIXED / "modern.json")
    assert d.card_to_v10_json(card) is card


def test_loader_accepts_v03_card_and_keeps_its_version():
    card = load_agent_card_from_path(MIXED / "legacy.json")
    assert card.name == "Legacy Agent"
    assert d.dialect_of_proto_card(card) is Dialect.V0_3
    # Serving it back yields the 0.3 layout again.
    served = d.card_to_v03_json(card)
    assert served["url"] == "http://127.0.0.1:0"
    assert d.card_is_v03(served)


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------


def test_v1_send_request_parses_as_sdk_send_message_request():
    params = d.send_params(
        Dialect.V1_0, d.text_message(Dialect.V1_0, "hi", context_id="c1"), blocking=False
    )
    req = ParseDict(params, a2a_pb2.SendMessageRequest())
    assert req.message.parts[0].text == "hi"
    assert req.message.role == a2a_pb2.ROLE_USER
    assert req.message.context_id == "c1"
    assert req.configuration.return_immediately is True


def test_v03_send_request_validates_against_sdk_03_model():
    from a2a.compat.v0_3 import types as types_v03

    params = d.send_params(Dialect.V0_3, d.text_message(Dialect.V0_3, "hi"), blocking=False)
    parsed = types_v03.MessageSendParams.model_validate(params)
    assert parsed.message.parts[0].root.text == "hi"
    assert parsed.configuration.blocking is False


def test_push_params_validate_against_each_version():
    from a2a.compat.v0_3 import types as types_v03

    ParseDict(
        d.push_set_params(Dialect.V1_0, "t1", url="https://h", token="tok", config_id="c"),
        a2a_pb2.TaskPushNotificationConfig(),
    )
    ParseDict(
        d.push_get_params(Dialect.V1_0, "t1", "c"), a2a_pb2.GetTaskPushNotificationConfigRequest()
    )
    ParseDict(
        d.push_list_params(Dialect.V1_0, "t1"), a2a_pb2.ListTaskPushNotificationConfigsRequest()
    )
    types_v03.TaskPushNotificationConfig.model_validate(
        d.push_set_params(Dialect.V0_3, "t1", url="https://h", token="tok")
    )
    types_v03.GetTaskPushNotificationConfigParams.model_validate(
        d.push_get_params(Dialect.V0_3, "t1", "c")
    )
    types_v03.ListTaskPushNotificationConfigParams.model_validate(
        d.push_list_params(Dialect.V0_3, "t1")
    )


# ---------------------------------------------------------------------------
# 0.3 -> 1.0 normalization
# ---------------------------------------------------------------------------

V03_TASK = {
    "kind": "task",
    "id": "t1",
    "contextId": "c1",
    "status": {"state": "input-required", "timestamp": "2026-01-01T00:00:00Z"},
    "history": [
        {
            "kind": "message",
            "messageId": "m1",
            "role": "user",
            "parts": [{"kind": "text", "text": "hi"}],
        }
    ],
    "artifacts": [
        {
            "artifactId": "a1",
            "parts": [
                {
                    "kind": "file",
                    "file": {"uri": "https://f", "mimeType": "text/plain", "name": "f.txt"},
                },
                {"kind": "data", "data": {"x": 1}},
            ],
        }
    ],
}


def test_normalized_v03_task_is_valid_v1_protojson():
    v1 = d.normalize_task(V03_TASK)
    task = ParseDict(v1, a2a_pb2.Task())  # strict: no unknown fields survive
    assert task.status.state == a2a_pb2.TASK_STATE_INPUT_REQUIRED
    assert task.history[0].role == a2a_pb2.ROLE_USER
    assert task.artifacts[0].parts[0].url == "https://f"
    assert task.artifacts[0].parts[0].media_type == "text/plain"
    assert task.artifacts[0].parts[0].filename == "f.txt"


def test_normalize_send_result():
    assert set(d.normalize_send_result(Dialect.V0_3, V03_TASK)) == {"task"}
    msg = {"kind": "message", "messageId": "m", "role": "agent", "parts": []}
    assert d.normalize_send_result(Dialect.V0_3, msg)["message"]["role"] == "ROLE_AGENT"
    v1 = {"task": {"id": "x"}}
    assert d.normalize_send_result(Dialect.V1_0, v1) is v1


def test_v1_payloads_are_not_normalized():
    """Genuine 1.0 violations must reach the contracts unchanged."""
    bad = {"kind": "task", "id": "t", "status": {"state": "completed"}}
    assert d.normalize_send_result(Dialect.V1_0, bad) is bad
    assert d.unwrap_stream_frame(Dialect.V1_0, {"jsonrpc": "2.0", "id": 1, "result": bad}) is bad


def test_normalize_v03_stream_events():
    su = {
        "kind": "status-update",
        "taskId": "t",
        "contextId": "c",
        "final": True,
        "status": {"state": "completed"},
    }
    frame = {"jsonrpc": "2.0", "id": 1, "result": su}
    out = d.unwrap_stream_frame(Dialect.V0_3, frame)
    assert out == {
        "statusUpdate": {
            "taskId": "t",
            "contextId": "c",
            "status": {"state": "TASK_STATE_COMPLETED"},
        }
    }
    ParseDict(out, a2a_pb2.StreamResponse())
    au = {
        "kind": "artifact-update",
        "taskId": "t",
        "contextId": "c",
        "artifact": {"artifactId": "a", "parts": [{"kind": "text", "text": "x"}]},
    }
    assert d.unwrap_stream_frame(Dialect.V0_3, {"jsonrpc": "2.0", "id": 1, "result": au}) == {
        "artifactUpdate": {
            "taskId": "t",
            "contextId": "c",
            "artifact": {"artifactId": "a", "parts": [{"text": "x"}]},
        }
    }
    assert set(
        d.unwrap_stream_frame(Dialect.V0_3, {"jsonrpc": "2.0", "id": 1, "result": V03_TASK})
    ) == {"task"}


def test_unwrap_error_frame():
    err = {"code": -32001, "message": "nope"}
    assert d.unwrap_stream_frame(Dialect.V1_0, {"jsonrpc": "2.0", "id": 1, "error": err}) == {
        "error": err
    }


def test_normalize_push_configs():
    v03 = {
        "taskId": "t",
        "pushNotificationConfig": {
            "id": "c",
            "url": "https://h",
            "token": "tok",
            "authentication": {"schemes": ["Bearer"], "credentials": "cred"},
        },
    }
    flat = d.normalize_push_config(Dialect.V0_3, v03)
    ParseDict(flat, a2a_pb2.TaskPushNotificationConfig())
    assert flat["authentication"] == {"scheme": "Bearer", "credentials": "cred"}
    assert d.normalize_push_config_list(Dialect.V0_3, [v03])[0]["id"] == "c"
    assert d.normalize_push_config_list(Dialect.V1_0, {"configs": [flat]}) == [flat]
    # ProtoJSON omits an empty repeated field.
    assert d.normalize_push_config_list(Dialect.V1_0, {}) == []
    assert d.normalize_push_config_list(Dialect.V1_0, None) is None


def test_v03_rendering_round_trips():
    v1_task = d.normalize_task(V03_TASK)
    from a2a.compat.v0_3 import types as types_v03

    types_v03.Task.model_validate(d.to_v03_task(v1_task))


def test_v1_claim_in_old_layout_is_not_treated_as_v03():
    """A card claiming 1.0 without supportedInterfaces is a malformed 1.0
    card; probing it as 0.3 would hide the violation."""
    card = {"name": "x", "url": "https://x", "protocolVersion": "1.0"}
    assert not d.card_is_v03(card)
    assert d.detect_dialect(card) is Dialect.V1_0
    assert d.card_to_v10_json(card) is card  # card contracts see it as sent


def test_sdk_dual_version_card_loads_and_negotiates_v1():
    """a2a-sdk agents serving 1.0 + 0.3 merge 0.3 fields into the 1.0 card."""
    from a2a.server.request_handlers.response_helpers import agent_card_to_dict

    from a2a_testbed.core.loader import load_agent_card_from_str
    from a2a_testbed.transport import A2ATransport

    card = load_agent_card_from_path(MIXED / "modern.json")
    card.supported_interfaces.add(
        url="http://h", protocol_binding="JSONRPC", protocol_version="0.3"
    )
    served = agent_card_to_dict(card)
    assert served["preferredTransport"] == "JSONRPC" and "supportedInterfaces" in served
    assert not d.card_is_v03(served)
    assert d.detect_dialect(served) is Dialect.V1_0
    assert load_agent_card_from_str(json.dumps(served)).name == "Modern Agent"
    assert A2ATransport().parse_card_text(json.dumps(served)).name == "Modern Agent"
    # The testbed serves such a card the same way the SDK does.
    ours = A2ATransport().serialize_card(card)
    assert ours["url"] and ours["protocolVersion"].startswith("0.3")
