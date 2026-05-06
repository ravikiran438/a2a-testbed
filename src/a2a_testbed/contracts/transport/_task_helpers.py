# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Shared helpers for the Task / GetTask / ListTasks / CancelTask /
multi-turn contract families.

These contracts target agents that produce Tasks (per A2A 1.0 §3.4).
Agents that only return Messages (e.g. simple echo agents) are
silently exempted by ``probe_for_task`` returning ``None`` —
contracts that consume the helper return a "skipped" detail string
in that case so they remain countable in the coverage metric while
honestly reporting the agent doesn't exercise the surface.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import httpx

from a2a_testbed.transport import Transport


def _build_send_request(
    *,
    text: str = "task-probe",
    request_id: str = "task-probe-1",
    context_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "messageId": str(uuid.uuid4()),
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
    }
    if context_id is not None:
        message["contextId"] = context_id
    if task_id is not None:
        message["taskId"] = task_id
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {"message": message},
    }


def looks_like_task(value: Any) -> bool:
    """Return True if `value` is a Task envelope (id + status.state)."""
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("id"), str):
        return False
    status = value.get("status")
    if not isinstance(status, dict):
        return False
    return isinstance(status.get("state"), str)


async def probe_for_task(
    transport: Transport,
    agent_url: str,
    *,
    context_id: Optional[str] = None,
    task_id: Optional[str] = None,
    text: str = "task-probe",
    blocking: bool = True,
) -> Optional[dict[str, Any]]:
    """Send a vanilla message/send and return the Task body if any.

    Returns ``None`` when the agent responds with a Message instead
    of a Task — the calling contract should report a "skipped"
    detail and pass.

    ``blocking=False`` adds ``configuration.blocking: false`` to the
    request, asking the agent to return immediately so the caller
    can register a push config before the task completes.
    """
    rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
    payload = _build_send_request(
        text=text,
        request_id="task-probe-" + uuid.uuid4().hex[:8],
        context_id=context_id,
        task_id=task_id,
    )
    if not blocking:
        payload["params"]["configuration"] = {"blocking": False}  # type: ignore[index]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            rpc_url,
            json=payload,
            headers={"content-type": "application/json"},
        )
    try:
        body = json.loads(resp.text)
    except json.JSONDecodeError:
        return None
    result = body.get("result") if isinstance(body, dict) else None
    if not looks_like_task(result):
        return None
    return result  # type: ignore[return-value]


async def call_method(
    transport: Transport,
    agent_url: str,
    method: str,
    params: Any,
    *,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    """Send a JSON-RPC call and return the parsed envelope (or {} on
    non-JSON response)."""
    rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
    req = {
        "jsonrpc": "2.0",
        "id": request_id or ("call-" + uuid.uuid4().hex[:8]),
        "method": method,
        "params": params,
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            rpc_url, json=req, headers={"content-type": "application/json"}
        )
    try:
        return json.loads(resp.text)
    except json.JSONDecodeError:
        return {}


# Per A2A 1.0 §4.1.3, every TaskState enum value the agent may emit.
VALID_TASK_STATES = frozenset(
    {
        "TASK_STATE_UNSPECIFIED",
        "TASK_STATE_SUBMITTED",
        "TASK_STATE_WORKING",
        "TASK_STATE_INPUT_REQUIRED",
        "TASK_STATE_COMPLETED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_FAILED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_AUTH_REQUIRED",
    }
)


# TaskState values that mean "no further work" — used by the
# state-transition contract to flag terminal-state mutations.
TERMINAL_TASK_STATES = frozenset(
    {
        "TASK_STATE_COMPLETED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_FAILED",
        "TASK_STATE_REJECTED",
    }
)


# TaskNotFoundError per §9.5.
TASK_NOT_FOUND_CODE = -32001


# --------------------------------------------------------------------------
# Capability-gated probes
# --------------------------------------------------------------------------


async def fetch_card(transport: Transport, agent_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            agent_url.rstrip("/") + transport.card_endpoint_path()
        )
    try:
        return json.loads(resp.text)
    except json.JSONDecodeError:
        return {}


def streaming_skip_detail(card: dict[str, Any]) -> Optional[str]:
    """Return a skip-detail string if streaming is not advertised."""
    if (card.get("capabilities") or {}).get("streaming") is True:
        return None
    return "skipped — agent does not advertise capabilities.streaming=true"


def push_skip_detail(card: dict[str, Any]) -> Optional[str]:
    """Return a skip-detail string if pushNotifications is not advertised."""
    if (card.get("capabilities") or {}).get("pushNotifications") is True:
        return None
    return (
        "skipped — agent does not advertise capabilities.pushNotifications=true"
    )


# --------------------------------------------------------------------------
# SSE consumption
# --------------------------------------------------------------------------


async def stream_sse_events(
    transport: Transport,
    agent_url: str,
    method: str,
    params: Any,
    *,
    timeout: float = 10.0,
    max_events: int = 50,
) -> list[dict[str, Any]]:
    """POST a JSON-RPC method and consume its `text/event-stream` body.

    Returns the parsed `data:` payloads in order. Raises if the
    response isn't an SSE stream (e.g. an error envelope or wrong
    content-type) — callers handle that via the assertion contracts.
    """
    rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
    req = {
        "jsonrpc": "2.0",
        "id": "sse-" + uuid.uuid4().hex[:8],
        "method": method,
        "params": params,
    }
    events: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            rpc_url,
            json=req,
            headers={"content-type": "application/json", "accept": "text/event-stream"},
        ) as resp:
            ctype = resp.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                # Not SSE — read full body so caller can inspect the
                # error envelope.
                raise SseFormatError(
                    f"expected text/event-stream, got {ctype!r}"
                )
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    parsed = _parse_sse_block(raw)
                    if parsed is not None:
                        events.append(parsed)
                        if len(events) >= max_events:
                            return events
            # Trailing block without final blank line.
            if buffer.strip():
                parsed = _parse_sse_block(buffer)
                if parsed is not None:
                    events.append(parsed)
    return events


def _parse_sse_block(block: str) -> Optional[dict[str, Any]]:
    """Extract the JSON payload from a `data:`-prefixed SSE block."""
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    payload = "\n".join(data_lines)
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class SseFormatError(AssertionError):
    """Raised when an SSE response's framing is wrong."""


# --------------------------------------------------------------------------
# Push-receiver helpers
#
# `push_fires_on_completion` configures the agent to push to a URL we
# control, then polls that URL to see if the webhook arrived. The
# default points at our hosted receiver; override via the
# A2A_TESTBED_PUSH_RECEIVER env var when testing in restricted
# environments.
# --------------------------------------------------------------------------


def push_receiver_base() -> str:
    import os
    return os.environ.get(
        "A2A_TESTBED_PUSH_RECEIVER",
        "https://push.a2a-testbed.com",
    )


def fresh_token() -> str:
    """Generate a unique token for this probe so concurrent runs
    don't see each other's webhooks."""
    return "tok-" + uuid.uuid4().hex


async def read_received_hooks(token: str) -> list[dict[str, Any]]:
    """Fetch the list of webhooks captured at the receiver for this token."""
    url = f"{push_receiver_base().rstrip('/')}/received/{token}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        return []
    try:
        body = json.loads(resp.text)
    except json.JSONDecodeError:
        return []
    hooks = body.get("hooks") if isinstance(body, dict) else None
    return hooks if isinstance(hooks, list) else []
