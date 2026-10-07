# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Shared helpers for the transport contract families.

Every contract talks to the agent in the A2A dialect its AgentCard
advertises (1.0 by default, 0.3 for legacy cards; see
:mod:`a2a_testbed.transport.dialect`) through :class:`AgentProbe`, and
checks results in the canonical 1.0 shape: payloads from 0.3 agents
are normalized before assertions run, payloads from 1.0 agents are not.

Task-producing contracts target agents that produce Tasks (per A2A 1.0
§3.4). Agents that only return Messages (e.g. simple echo agents) are
silently exempted by ``probe_for_task`` returning ``None`` — contracts
that consume the helper return a "skipped" detail string in that case
so they remain countable in the coverage metric while honestly
reporting the agent doesn't exercise the surface.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from a2a_testbed.transport import Transport
from a2a_testbed.transport import dialect as d
from a2a_testbed.transport.dialect import Dialect

# ---------------------------------------------------------------------------
# AgentProbe: dialect-aware client for one agent under test
# ---------------------------------------------------------------------------


@dataclass
class AgentProbe:
    """One agent under test, addressed in the dialect its card advertises.

    ``card`` is the raw card JSON (``{}`` when unreachable); ``card_v1``
    is the same card in the 1.0 layout (0.3 cards converted with the
    a2a-sdk compat layer) for card checks that read 1.0 field names.
    """

    transport: Transport
    agent_url: str
    card: dict[str, Any] = field(default_factory=dict)
    card_v1: dict[str, Any] = field(default_factory=dict)
    dialect: Dialect = d.CURRENT

    @classmethod
    async def create(cls, transport: Transport, agent_url: str) -> AgentProbe:
        card = await fetch_card(transport, agent_url)
        card_v1 = d.card_to_v10_json(card) if card else {}
        return cls(
            transport=transport,
            agent_url=agent_url,
            card=card,
            card_v1=card_v1 if isinstance(card_v1, dict) else {},
            dialect=Dialect(transport.protocol_version_for_card(card) or d.CURRENT.value),
        )

    @property
    def rpc_url(self) -> str:
        return self.agent_url.rstrip("/") + self.transport.rpc_endpoint_path()

    @property
    def is_legacy(self) -> bool:
        return self.dialect is Dialect.V0_3

    def headers(self) -> dict[str, str]:
        return {"content-type": "application/json", **d.request_headers(self.dialect)}

    def method(self, op: str) -> str:
        """JSON-RPC method name for ``op`` in this agent's dialect."""
        return d.method(self.dialect, op)

    def message(self, text: str, **kw: Any) -> dict[str, Any]:
        return d.text_message(self.dialect, text, **kw)

    def send_params(
        self, text: str, *, blocking: Optional[bool] = None, **kw: Any
    ) -> dict[str, Any]:
        return d.send_params(self.dialect, self.message(text, **kw), blocking=blocking)

    def capability(self, name: str) -> Any:
        return (self.card_v1.get("capabilities") or {}).get(name)

    # -- result normalization (0.3 -> 1.0; 1.0 payloads pass through) --

    def task_of(self, value: Any) -> Any:
        return d.normalize_task(value) if self.is_legacy else value

    def push_config_of(self, value: Any) -> Any:
        return d.normalize_push_config(self.dialect, value)

    def push_config_list_of(self, value: Any) -> Optional[list[Any]]:
        return d.normalize_push_config_list(self.dialect, value)

    async def call(
        self,
        op: str,
        params: Any,
        *,
        request_id: Optional[str] = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Call ``op`` and return the parsed JSON-RPC envelope ({} if not JSON)."""
        return await call_method(
            self.transport,
            self.agent_url,
            self.method(op),
            params,
            request_id=request_id,
            headers=d.request_headers(self.dialect),
            timeout=timeout,
        )

    async def stream(
        self,
        op: str,
        params: Any,
        *,
        timeout: float = 10.0,
        max_events: int = 50,
    ) -> list[dict[str, Any]]:
        """Consume an SSE response; events are 1.0 ``StreamResponse`` objects."""
        frames = await self.stream_frames(op, params, timeout=timeout, max_events=max_events)
        return [d.unwrap_stream_frame(self.dialect, f) for f in frames]

    async def stream_frames(
        self,
        op: str,
        params: Any,
        *,
        timeout: float = 10.0,
        max_events: int = 50,
    ) -> list[dict[str, Any]]:
        """Raw parsed SSE ``data:`` payloads, before any unwrapping."""
        return await stream_sse_events(
            self.transport,
            self.agent_url,
            self.method(op),
            params,
            timeout=timeout,
            max_events=max_events,
            headers=d.request_headers(self.dialect),
        )

    async def send_for_task(
        self,
        *,
        text: str = "task-probe",
        blocking: bool = True,
        context_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Send a message and return the resulting Task (1.0 shape), if any."""
        envelope = await self.call(
            "send",
            self.send_params(
                text,
                blocking=None if blocking else False,
                context_id=context_id,
                task_id=task_id,
            ),
            request_id="task-probe-" + uuid.uuid4().hex[:8],
        )
        result = d.normalize_send_result(self.dialect, envelope.get("result"))
        task = result.get("task") if isinstance(result, dict) else None
        return task if looks_like_task(task) else None


def _build_send_request(
    *,
    text: str = "task-probe",
    request_id: str = "task-probe-1",
    context_id: Optional[str] = None,
    task_id: Optional[str] = None,
    dialect: Dialect = d.CURRENT,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": d.method(dialect, "send"),
        "params": d.send_params(
            dialect,
            d.text_message(dialect, text, context_id=context_id, task_id=task_id),
        ),
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
    """Send a vanilla message and return the Task body (1.0 shape) if any.

    Returns ``None`` when the agent responds with a Message instead
    of a Task — the calling contract should report a "skipped"
    detail and pass.

    ``blocking=False`` asks the agent to return immediately (1.0
    ``returnImmediately`` / 0.3 ``blocking: false``) so the caller can
    act on the task (push config, subscribe, cancel) before it completes.
    """
    probe = await AgentProbe.create(transport, agent_url)
    return await probe.send_for_task(
        text=text, blocking=blocking, context_id=context_id, task_id=task_id
    )


async def call_method(
    transport: Transport,
    agent_url: str,
    method: str,
    params: Any,
    *,
    request_id: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Send a JSON-RPC call and return the parsed envelope (or {} on
    non-JSON response).

    If the agent answers with an SSE stream (streaming methods may report
    errors as an error frame rather than a plain JSON body), the first
    frame is returned as the envelope.
    """
    rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
    req = {
        "jsonrpc": "2.0",
        "id": request_id or ("call-" + uuid.uuid4().hex[:8]),
        "method": method,
        "params": params,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            rpc_url,
            json=req,
            headers={"content-type": "application/json", **(headers or {})},
        ) as resp:
            if "text/event-stream" in resp.headers.get("content-type", ""):
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer = (buffer + chunk).replace("\r\n", "\n")
                    while "\n\n" in buffer:
                        raw, buffer = buffer.split("\n\n", 1)
                        frame = _parse_sse_block(raw)
                        if frame is not None:
                            return frame
                frame = _parse_sse_block(buffer.replace("\r", "\n"))
                return frame or {}
            text = (await resp.aread()).decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


# A2A error codes (§5.4 / §9.5).
TASK_NOT_FOUND_CODE = -32001
TASK_NOT_CANCELABLE_CODE = -32002
UNSUPPORTED_OPERATION_CODE = -32004
METHOD_NOT_FOUND_CODE = -32601

#: Text that makes the reference task runner (and the testbed's SDK
#: oracle agents) work for ~N×50ms, long enough to act on a running task.
LONG_TASK_TEXT = "count: 12 long-running probe"


def error_code(envelope: Any) -> Optional[int]:
    """``error.code`` of a JSON-RPC envelope, or ``None``."""
    if not isinstance(envelope, dict):
        return None
    err = envelope.get("error")
    return err.get("code") if isinstance(err, dict) else None


def webhook_task_id(dialect: Dialect, payload: Any) -> Optional[str]:
    """Task id a push-notification body refers to.

    1.0 posts a ``StreamResponse`` (§4.3.3); 0.3 posted the bare Task.
    """
    if not isinstance(payload, dict):
        return None
    event = d.normalize_stream_result(dialect, payload)
    if not isinstance(event, dict):
        return None
    if isinstance(event.get("task"), dict):
        return event["task"].get("id")
    for key in ("statusUpdate", "artifactUpdate", "message"):
        if isinstance(event.get(key), dict):
            return event[key].get("taskId")
    return None


def legacy_note(probe: AgentProbe) -> str:
    """Suffix for pass details on agents probed in the 0.3 dialect."""
    return " [A2A 0.3 agent: probed with 0.3 method names]" if probe.is_legacy else ""


# --------------------------------------------------------------------------
# Capability-gated probes
# --------------------------------------------------------------------------


async def fetch_card(transport: Transport, agent_url: str) -> dict[str, Any]:
    """Raw AgentCard JSON (any version); ``{}`` when unreachable or not JSON."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(agent_url.rstrip("/") + transport.card_endpoint_path())
    except httpx.HTTPError:
        return {}
    try:
        parsed = json.loads(resp.text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def streaming_skip_detail(card: dict[str, Any]) -> Optional[str]:
    """Return a skip-detail string if streaming is not advertised."""
    if (d.card_to_v10_json(card).get("capabilities") or {}).get("streaming") is True:
        return None
    return "skipped — agent does not advertise capabilities.streaming=true"


def push_skip_detail(card: dict[str, Any]) -> Optional[str]:
    """Return a skip-detail string if pushNotifications is not advertised."""
    if (d.card_to_v10_json(card).get("capabilities") or {}).get("pushNotifications") is True:
        return None
    return "skipped — agent does not advertise capabilities.pushNotifications=true"


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
    headers: Optional[dict[str, str]] = None,
    request_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """POST a JSON-RPC method and consume its `text/event-stream` body.

    Returns the parsed `data:` payloads in order, as sent (JSON-RPC
    envelopes for a conformant agent; see ``AgentProbe.stream`` for
    unwrapped events). Raises if the response isn't an SSE stream
    (e.g. an error envelope or wrong content-type) — callers handle
    that via the assertion contracts.
    """
    rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
    req = {
        "jsonrpc": "2.0",
        "id": request_id or ("sse-" + uuid.uuid4().hex[:8]),
        "method": method,
        "params": params,
    }
    events: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            rpc_url,
            json=req,
            headers={
                "content-type": "application/json",
                "accept": "text/event-stream",
                **(headers or {}),
            },
        ) as resp:
            ctype = resp.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                # Not SSE — surface the JSON-RPC error if there is one.
                body = (await resp.aread()).decode("utf-8", "replace")
                raise SseFormatError(f"expected text/event-stream, got {ctype!r}", body=body)
            buffer = ""
            async for chunk in resp.aiter_text():
                # SSE allows CRLF, LF or CR line endings (WHATWG HTML
                # §9.2.6); sse-starlette — used by the a2a-sdk — emits
                # CRLF. Normalize so blank-line framing splits correctly.
                buffer += chunk
                # Hold back a trailing CR: its LF may arrive in the next chunk.
                held = "\r" if buffer.endswith("\r") else ""
                if held:
                    buffer = buffer[:-1]
                buffer = buffer.replace("\r\n", "\n").replace("\r", "\n")
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    parsed = _parse_sse_block(raw)
                    if parsed is not None:
                        events.append(parsed)
                        if len(events) >= max_events:
                            return events
                buffer += held
            buffer = buffer.replace("\r\n", "\n").replace("\r", "\n")
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
    """Raised when an SSE response's framing is wrong.

    ``error`` carries the JSON-RPC error object when the agent answered
    with a plain JSON error envelope instead of a stream.
    """

    def __init__(self, message: str, *, body: str = "") -> None:
        super().__init__(message)
        self.body = body
        self.error: Optional[dict[str, Any]] = None
        try:
            parsed = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            self.error = parsed["error"]

    @property
    def error_code(self) -> Optional[int]:
        return self.error.get("code") if self.error else None


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
