# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""A2A protocol dialects: 1.0 (current) and 0.3 (legacy).

A2A 1.0 renamed every JSON-RPC method (``message/send`` ->
``SendMessage``), switched payloads to the ProtoJSON rendering of
``a2a.proto`` (oneof Parts without ``kind``, ``ROLE_*`` roles,
``TASK_STATE_*`` states, ``{"task": ...}`` send results, JSON-RPC-
wrapped ``StreamResponse`` SSE frames) and introduced the
``A2A-Version`` service parameter. 0.3 agents are still deployed, so
the testbed speaks both:

- **As a client** (conformance sweeps, scenario runs) it talks to an
  agent in the dialect its AgentCard advertises (:func:`detect_dialect`)
  and normalizes 0.3 payloads into the 1.0 shape so every contract
  checks one canonical form (:func:`normalize_task` and friends).
- **As a server** (in-process agents, templates) it answers each
  request in the dialect the request was made in (:func:`dialect_for_method`).

1.0 is the default whenever a card is ambiguous: the spec says clients
"should be configured to request specific versions and avoid automatic
fallback to older versions" (A2A 1.0 §3.6.3), so 0.3 is only used when
the card positively says so.

This module is pure dict manipulation with no I/O so the browser
validator (``playground/src/conformance/dialect.ts``) can mirror it
line for line.
"""

from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import Any


class Dialect(str, Enum):
    """A2A wire dialect. Values are the ``A2A-Version`` strings."""

    V1_0 = "1.0"
    V0_3 = "0.3"


#: Header carrying the requested protocol version (A2A 1.0 §3.6, §14.2.1).
VERSION_HEADER = "A2A-Version"

#: Protocol version the testbed speaks by default.
CURRENT = Dialect.V1_0


# ---------------------------------------------------------------------------
# Method names
# ---------------------------------------------------------------------------

#: Logical operation -> JSON-RPC method name, per dialect. ``list`` has no
#: 0.3 equivalent in the spec; ``tasks/list`` was a common pre-1.0
#: extension (and what earlier testbed releases probed), so it is kept for
#: 0.3 agents that happen to implement it.
METHODS: dict[Dialect, dict[str, str]] = {
    Dialect.V1_0: {
        "send": "SendMessage",
        "stream": "SendStreamingMessage",
        "get": "GetTask",
        "list": "ListTasks",
        "cancel": "CancelTask",
        "subscribe": "SubscribeToTask",
        "push_set": "CreateTaskPushNotificationConfig",
        "push_get": "GetTaskPushNotificationConfig",
        "push_list": "ListTaskPushNotificationConfigs",
        "push_delete": "DeleteTaskPushNotificationConfig",
        "extended_card": "GetExtendedAgentCard",
    },
    Dialect.V0_3: {
        "send": "message/send",
        "stream": "message/stream",
        "get": "tasks/get",
        "list": "tasks/list",
        "cancel": "tasks/cancel",
        "subscribe": "tasks/resubscribe",
        "push_set": "tasks/pushNotificationConfig/set",
        "push_get": "tasks/pushNotificationConfig/get",
        "push_list": "tasks/pushNotificationConfig/list",
        "push_delete": "tasks/pushNotificationConfig/delete",
        "extended_card": "agent/getAuthenticatedExtendedCard",
    },
}

_METHOD_TO_OP: dict[str, tuple[Dialect, str]] = {
    name: (dialect, op) for dialect, ops in METHODS.items() for op, name in ops.items()
}

#: Methods whose response is an SSE stream.
STREAMING_OPS = frozenset({"stream", "subscribe"})


def method(dialect: Dialect, op: str) -> str:
    """JSON-RPC method name for logical operation ``op`` in ``dialect``."""
    return METHODS[dialect][op]


def dialect_for_method(name: Any) -> tuple[Dialect, str] | None:
    """Map a JSON-RPC method name to ``(dialect, op)``; ``None`` if unknown."""
    if not isinstance(name, str):
        return None
    return _METHOD_TO_OP.get(name)


def request_headers(dialect: Dialect) -> dict[str, str]:
    """HTTP headers a client sends with every request in ``dialect``.

    1.0 clients MUST send ``A2A-Version``; 0.3 clients send nothing
    (servers interpret an absent header as 0.3, A2A 1.0 §3.6.2).
    """
    if dialect is Dialect.V1_0:
        return {VERSION_HEADER: Dialect.V1_0.value}
    return {}


def parse_version_header(value: str | None) -> Dialect:
    """Dialect requested by an ``A2A-Version`` header value.

    Empty means 0.3 (§3.6.2). Unknown majors are returned as 1.0 when
    any listed value is 1.x, else 0.3 if any is 0.x; callers that must
    reject unsupported versions use :func:`version_supported`.
    """
    if not value:
        return Dialect.V0_3
    versions = [v.strip() for v in value.split(",") if v.strip()]
    if any(_major_minor(v)[0] == 1 for v in versions):
        return Dialect.V1_0
    return Dialect.V0_3


def version_supported(value: str | None) -> bool:
    """True when the header requests a version the testbed serves (0.3 / 1.x)."""
    if not value:
        return True
    for v in (s.strip() for s in value.split(",")):
        major, minor = _major_minor(v)
        if major == 1 or (major == 0 and minor == 3):
            return True
    return False


def _major_minor(version: str) -> tuple[int | None, int | None]:
    m = re.match(r"^\s*(\d+)(?:\.(\d+))?", version or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2)) if m.group(2) is not None else None


# ---------------------------------------------------------------------------
# Dialect detection from an AgentCard
# ---------------------------------------------------------------------------


def card_is_v03(card: Any) -> bool:
    """True when a card JSON object uses the 0.3 layout.

    0.3 cards carry ``url`` + ``protocolVersion`` (+ usually
    ``preferredTransport``) at the top level; 1.0 cards move those into
    ``supportedInterfaces[]``. A card without interfaces counts as 0.3
    only if its top-level ``protocolVersion`` is 0.x (or absent next to
    a ``url``): a card that claims 1.0 in the old layout is a malformed
    1.0 card, and the card contracts must see it as one.
    """
    if not isinstance(card, dict):
        return False
    if isinstance(card.get("supportedInterfaces"), list) and card["supportedInterfaces"]:
        return False
    version = card.get("protocolVersion")
    if version is not None:
        return isinstance(version, str) and _major_minor(version)[0] == 0
    return "url" in card


def detect_dialect(card: Any) -> Dialect:
    """Dialect to use for an agent, from its AgentCard JSON.

    Picks the JSON-RPC interface the card advertises: a 1.0 card with a
    1.x (or unversioned) JSONRPC interface -> 1.0; a card whose JSONRPC
    interfaces are all 0.x -> 0.3; a 0.3-layout card -> 0.3. Anything
    else defaults to 1.0.
    """
    if card_is_v03(card):
        return Dialect.V0_3
    if not isinstance(card, dict):
        return CURRENT
    interfaces = card.get("supportedInterfaces")
    if not isinstance(interfaces, list):
        return CURRENT
    versions = [
        iface.get("protocolVersion")
        for iface in interfaces
        if isinstance(iface, dict)
        and str(iface.get("protocolBinding", "JSONRPC")).upper() == "JSONRPC"
    ]
    if not versions:
        return CURRENT
    if any(not v or _major_minor(str(v))[0] != 0 for v in versions):
        return Dialect.V1_0
    return Dialect.V0_3


def card_lists_v03_interface(card: Any) -> bool:
    """True when a parsed ``a2a.types.AgentCard`` lists a 0.x interface."""
    return any(
        _major_minor(getattr(i, "protocol_version", "") or "")[0] == 0
        for i in getattr(card, "supported_interfaces", None) or []
    )


def dialect_of_proto_card(card: Any) -> Dialect:
    """:func:`detect_dialect` for a parsed ``a2a.types.AgentCard`` proto."""
    interfaces = getattr(card, "supported_interfaces", None) or []
    as_json = {
        "supportedInterfaces": [
            {
                "protocolBinding": getattr(i, "protocol_binding", "") or "JSONRPC",
                "protocolVersion": getattr(i, "protocol_version", "") or None,
            }
            for i in interfaces
        ]
    }
    return detect_dialect(as_json)


# ---------------------------------------------------------------------------
# Request builders (client side)
# ---------------------------------------------------------------------------


def text_message(
    dialect: Dialect,
    text: str,
    *,
    role: str = "user",
    message_id: str | None = None,
    context_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """A single-text-part Message in ``dialect``'s wire shape."""
    msg: dict[str, Any] = {"messageId": message_id or str(uuid.uuid4())}
    if dialect is Dialect.V1_0:
        msg["role"] = "ROLE_AGENT" if role == "agent" else "ROLE_USER"
        msg["parts"] = [{"text": text}]
    else:
        msg["kind"] = "message"
        msg["role"] = "agent" if role == "agent" else "user"
        msg["parts"] = [{"kind": "text", "text": text}]
    if context_id is not None:
        msg["contextId"] = context_id
    if task_id is not None:
        msg["taskId"] = task_id
    return msg


def send_params(
    dialect: Dialect,
    message: dict[str, Any],
    *,
    blocking: bool | None = None,
) -> dict[str, Any]:
    """``SendMessage`` / ``message/send`` params.

    ``blocking=False`` asks the agent to return immediately: 1.0's
    ``configuration.returnImmediately`` (§3.2.2) or 0.3's
    ``configuration.blocking: false``. ``None`` leaves the agent default.
    """
    params: dict[str, Any] = {"message": message}
    if blocking is not None:
        if dialect is Dialect.V1_0:
            params["configuration"] = {"returnImmediately": not blocking}
        else:
            params["configuration"] = {"blocking": blocking}
    return params


def push_set_params(
    dialect: Dialect,
    task_id: str,
    *,
    url: str,
    token: str | None = None,
    config_id: str | None = None,
) -> dict[str, Any]:
    """Params to register a push-notification config for ``task_id``."""
    if dialect is Dialect.V1_0:
        cfg: dict[str, Any] = {"taskId": task_id, "url": url}
        if config_id:
            cfg["id"] = config_id
        if token:
            cfg["token"] = token
        return cfg
    inner: dict[str, Any] = {"url": url}
    if config_id:
        inner["id"] = config_id
    if token:
        inner["token"] = token
    return {"taskId": task_id, "pushNotificationConfig": inner}


def push_get_params(dialect: Dialect, task_id: str, config_id: str) -> dict[str, Any]:
    if dialect is Dialect.V1_0:
        return {"taskId": task_id, "id": config_id}
    return {"id": task_id, "pushNotificationConfigId": config_id}


def push_list_params(dialect: Dialect, task_id: str) -> dict[str, Any]:
    if dialect is Dialect.V1_0:
        return {"taskId": task_id}
    return {"id": task_id}


def push_delete_params(dialect: Dialect, task_id: str, config_id: str) -> dict[str, Any]:
    return push_get_params(dialect, task_id, config_id)


# ---------------------------------------------------------------------------
# 0.3 -> 1.0 normalization (client side)
#
# Contracts check one canonical (1.0) shape. Payloads from a 1.0 agent are
# left untouched so genuine 1.0 violations still surface; payloads from a
# 0.3 agent are translated field by field. The translation is lenient: it
# only rewrites values it recognizes as 0.3, so hybrid agents that already
# emit 1.0 enum values pass through.
# ---------------------------------------------------------------------------

_STATE_V03_TO_V10 = {
    "submitted": "TASK_STATE_SUBMITTED",
    "working": "TASK_STATE_WORKING",
    "input-required": "TASK_STATE_INPUT_REQUIRED",
    "completed": "TASK_STATE_COMPLETED",
    "canceled": "TASK_STATE_CANCELED",
    "failed": "TASK_STATE_FAILED",
    "rejected": "TASK_STATE_REJECTED",
    "auth-required": "TASK_STATE_AUTH_REQUIRED",
    "unknown": "TASK_STATE_UNSPECIFIED",
}
_STATE_V10_TO_V03 = {v: k for k, v in _STATE_V03_TO_V10.items()}

_ROLE_V03_TO_V10 = {"user": "ROLE_USER", "agent": "ROLE_AGENT"}
_ROLE_V10_TO_V03 = {v: k for k, v in _ROLE_V03_TO_V10.items()}


def normalize_state(state: Any) -> Any:
    return _STATE_V03_TO_V10.get(state, state) if isinstance(state, str) else state


def normalize_part(part: Any) -> Any:
    """0.3 ``{kind, text|file|data}`` -> 1.0 oneof Part."""
    if not isinstance(part, dict) or "kind" not in part:
        return part
    out: dict[str, Any] = {}
    kind = part.get("kind")
    if kind == "text":
        out["text"] = part.get("text")
    elif kind == "data":
        out["data"] = part.get("data")
    elif kind == "file":
        f = part.get("file") if isinstance(part.get("file"), dict) else {}
        if "uri" in f:
            out["url"] = f.get("uri")
        if "bytes" in f:
            out["raw"] = f.get("bytes")
        if f.get("mimeType"):
            out["mediaType"] = f["mimeType"]
        if f.get("name"):
            out["filename"] = f["name"]
    else:
        out = {k: v for k, v in part.items() if k != "kind"}
    if "metadata" in part:
        out["metadata"] = part["metadata"]
    return out


def normalize_message(msg: Any) -> Any:
    if not isinstance(msg, dict):
        return msg
    out = {k: v for k, v in msg.items() if k != "kind"}
    if isinstance(out.get("role"), str):
        out["role"] = _ROLE_V03_TO_V10.get(out["role"], out["role"])
    if isinstance(out.get("parts"), list):
        out["parts"] = [normalize_part(p) for p in out["parts"]]
    return out


def normalize_artifact(art: Any) -> Any:
    if not isinstance(art, dict):
        return art
    out = dict(art)
    if isinstance(out.get("parts"), list):
        out["parts"] = [normalize_part(p) for p in out["parts"]]
    return out


def normalize_status(status: Any) -> Any:
    if not isinstance(status, dict):
        return status
    out = dict(status)
    if "state" in out:
        out["state"] = normalize_state(out["state"])
    if isinstance(out.get("message"), dict):
        out["message"] = normalize_message(out["message"])
    return out


def normalize_task(task: Any) -> Any:
    if not isinstance(task, dict):
        return task
    out = {k: v for k, v in task.items() if k != "kind"}
    if "status" in out:
        out["status"] = normalize_status(out["status"])
    if isinstance(out.get("history"), list):
        out["history"] = [normalize_message(m) for m in out["history"]]
    if isinstance(out.get("artifacts"), list):
        out["artifacts"] = [normalize_artifact(a) for a in out["artifacts"]]
    return out


def normalize_send_result(dialect: Dialect, result: Any) -> Any:
    """``SendMessage`` result in the 1.0 ``{task}`` / ``{message}`` shape.

    1.0 results are returned untouched. A 0.3 result is a bare Task or
    Message discriminated by ``kind``.
    """
    if dialect is Dialect.V1_0 or not isinstance(result, dict):
        return result
    if "task" in result or "message" in result:
        return result  # already wrapped (hybrid agent)
    kind = result.get("kind")
    if kind == "message" or (kind is None and "messageId" in result and "status" not in result):
        return {"message": normalize_message(result)}
    return {"task": normalize_task(result)}


def normalize_stream_result(dialect: Dialect, result: Any) -> Any:
    """One SSE ``result`` as a 1.0 ``StreamResponse`` (oneof wrapper)."""
    if dialect is Dialect.V1_0 or not isinstance(result, dict):
        return result
    if result.keys() & {"task", "message", "statusUpdate", "artifactUpdate"}:
        # Already wrapped; still normalize inner 0.3 values.
        out = dict(result)
        if "task" in out:
            out["task"] = normalize_task(out["task"])
        if "message" in out:
            out["message"] = normalize_message(out["message"])
        if isinstance(out.get("statusUpdate"), dict):
            su = {k: v for k, v in out["statusUpdate"].items() if k not in ("kind", "final")}
            su["status"] = normalize_status(su.get("status"))
            out["statusUpdate"] = su
        if isinstance(out.get("artifactUpdate"), dict):
            au = {k: v for k, v in out["artifactUpdate"].items() if k != "kind"}
            au["artifact"] = normalize_artifact(au.get("artifact"))
            out["artifactUpdate"] = au
        return out
    kind = result.get("kind")
    if kind == "status-update":
        su = {k: v for k, v in result.items() if k not in ("kind", "final")}
        su["status"] = normalize_status(su.get("status"))
        return {"statusUpdate": su}
    if kind == "artifact-update":
        au = {k: v for k, v in result.items() if k != "kind"}
        au["artifact"] = normalize_artifact(au.get("artifact"))
        return {"artifactUpdate": au}
    if kind == "message":
        return {"message": normalize_message(result)}
    return {"task": normalize_task(result)}


def unwrap_stream_frame(dialect: Dialect, frame: Any) -> Any:
    """Turn one parsed SSE ``data:`` payload into a 1.0 StreamResponse.

    The JSON-RPC binding wraps every frame in a JSON-RPC response
    (A2A 1.0 §9.4.2); error frames are returned as ``{"error": ...}``.
    Bare frames (no envelope) are tolerated here — the dedicated
    ``streaming_jsonrpc_framing`` contract is what flags them.
    """
    if not isinstance(frame, dict):
        return frame
    if "jsonrpc" in frame or ("id" in frame and ("result" in frame or "error" in frame)):
        if frame.get("error") is not None:
            return {"error": frame["error"]}
        return normalize_stream_result(dialect, frame.get("result"))
    return normalize_stream_result(dialect, frame)


def normalize_push_config(dialect: Dialect, cfg: Any) -> Any:
    """Push-config result as a flat 1.0 ``TaskPushNotificationConfig``."""
    if dialect is Dialect.V1_0 or not isinstance(cfg, dict):
        return cfg
    inner = cfg.get("pushNotificationConfig")
    if not isinstance(inner, dict):
        return cfg
    out: dict[str, Any] = {"taskId": cfg.get("taskId")}
    for key in ("id", "url", "token"):
        if key in inner:
            out[key] = inner[key]
    auth = inner.get("authentication")
    if isinstance(auth, dict):
        schemes = auth.get("schemes") or []
        flat: dict[str, Any] = {}
        if schemes:
            flat["scheme"] = schemes[0]
        if auth.get("credentials"):
            flat["credentials"] = auth["credentials"]
        out["authentication"] = flat
    return out


def normalize_push_config_list(dialect: Dialect, result: Any) -> list[Any] | None:
    """Push-config list result as a list of flat 1.0 configs.

    1.0 returns ``{"configs": [...], "nextPageToken": ...}``; 0.3
    returns a bare array. ``None`` when the shape is unrecognized.
    """
    if dialect is Dialect.V1_0:
        if not isinstance(result, dict):
            return None
        configs = result.get("configs", [])  # ProtoJSON omits empty repeated fields
        return configs if isinstance(configs, list) else None
    if isinstance(result, list):
        return [normalize_push_config(dialect, c) for c in result]
    if isinstance(result, dict):
        # Pre-1.0 testbed reference agent shape.
        legacy = result.get("pushNotificationConfigs")
        if isinstance(legacy, list):
            return legacy
        if isinstance(result.get("configs"), list):
            return result["configs"]
    return None


# ---------------------------------------------------------------------------
# 1.0 -> 0.3 rendering (server side, for legacy callers)
# ---------------------------------------------------------------------------


def to_v03_part(part: Any) -> Any:
    if not isinstance(part, dict) or "kind" in part:
        return part
    meta = {"metadata": part["metadata"]} if "metadata" in part else {}
    if "text" in part:
        return {"kind": "text", "text": part["text"], **meta}
    if "data" in part:
        return {"kind": "data", "data": part["data"], **meta}
    file: dict[str, Any] = {}
    if "url" in part:
        file["uri"] = part["url"]
    if "raw" in part:
        file["bytes"] = part["raw"]
    if part.get("mediaType"):
        file["mimeType"] = part["mediaType"]
    if part.get("filename"):
        file["name"] = part["filename"]
    return {"kind": "file", "file": file, **meta}


def to_v03_message(msg: Any) -> Any:
    if not isinstance(msg, dict):
        return msg
    out = dict(msg)
    out["kind"] = "message"
    if isinstance(out.get("role"), str):
        out["role"] = _ROLE_V10_TO_V03.get(out["role"], out["role"])
    if isinstance(out.get("parts"), list):
        out["parts"] = [to_v03_part(p) for p in out["parts"]]
    return out


def to_v03_task(task: Any) -> Any:
    if not isinstance(task, dict):
        return task
    out = dict(task)
    out["kind"] = "task"
    status = dict(out.get("status") or {})
    if isinstance(status.get("state"), str):
        status["state"] = _STATE_V10_TO_V03.get(status["state"], status["state"])
    if isinstance(status.get("message"), dict):
        status["message"] = to_v03_message(status["message"])
    out["status"] = status
    if isinstance(out.get("history"), list):
        out["history"] = [to_v03_message(m) for m in out["history"]]
    if isinstance(out.get("artifacts"), list):
        out["artifacts"] = [
            {**a, "parts": [to_v03_part(p) for p in a.get("parts") or []]}
            if isinstance(a, dict)
            else a
            for a in out["artifacts"]
        ]
    return out


# ---------------------------------------------------------------------------
# AgentCard conversion
# ---------------------------------------------------------------------------


def card_to_v10_json(card: Any) -> Any:
    """A card JSON object in the 1.0 layout.

    1.0 cards are returned untouched. 0.3 cards are converted with the
    a2a-sdk's own compat converter (``a2a.compat.v0_3``), so the result
    is exactly what an official 1.0 client would see; if the card is
    too malformed for the SDK model, a minimal structural conversion is
    used so card contracts can still report on it.
    """
    if not card_is_v03(card):
        return card
    try:
        from a2a.compat.v0_3 import conversions
        from a2a.compat.v0_3 import types as types_v03
        from google.protobuf.json_format import MessageToDict

        core = conversions.to_core_agent_card(types_v03.AgentCard.model_validate(card))
        return MessageToDict(core, preserving_proto_field_name=False)
    except Exception:  # noqa: BLE001 — fall back to a best-effort structural map
        out = {
            k: v
            for k, v in card.items()
            if k
            not in (
                "url",
                "preferredTransport",
                "protocolVersion",
                "additionalInterfaces",
                "supportsAuthenticatedExtendedCard",
            )
        }
        interfaces = [
            {
                "url": card.get("url"),
                "protocolBinding": card.get("preferredTransport") or "JSONRPC",
                "protocolVersion": card.get("protocolVersion") or Dialect.V0_3.value,
            }
        ]
        for extra in card.get("additionalInterfaces") or []:
            if isinstance(extra, dict):
                interfaces.append(
                    {
                        "url": extra.get("url"),
                        "protocolBinding": extra.get("transport"),
                        "protocolVersion": Dialect.V0_3.value,
                    }
                )
        out["supportedInterfaces"] = interfaces
        if "supportsAuthenticatedExtendedCard" in card:
            caps = dict(out.get("capabilities") or {})
            caps["extendedAgentCard"] = card["supportsAuthenticatedExtendedCard"]
            out["capabilities"] = caps
        return out


def card_to_v03_json(core_card: Any) -> dict[str, Any]:
    """Serialize an ``a2a.types.AgentCard`` proto in the 0.3 layout."""
    from a2a.compat.v0_3 import conversions

    compat = conversions.to_compat_agent_card(core_card)
    return compat.model_dump(by_alias=True, exclude_none=True, mode="json")


__all__ = [
    "CURRENT",
    "METHODS",
    "STREAMING_OPS",
    "VERSION_HEADER",
    "Dialect",
    "card_is_v03",
    "card_lists_v03_interface",
    "card_to_v03_json",
    "card_to_v10_json",
    "detect_dialect",
    "dialect_for_method",
    "dialect_of_proto_card",
    "method",
    "normalize_artifact",
    "normalize_message",
    "normalize_push_config",
    "normalize_push_config_list",
    "normalize_send_result",
    "normalize_state",
    "normalize_status",
    "normalize_stream_result",
    "normalize_task",
    "parse_version_header",
    "push_delete_params",
    "push_get_params",
    "push_list_params",
    "push_set_params",
    "request_headers",
    "send_params",
    "text_message",
    "to_v03_message",
    "to_v03_part",
    "to_v03_task",
    "unwrap_stream_frame",
    "version_supported",
]
