# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""ASSERT callable target: an A2A agent guarded by ACS.

This wraps a live A2A 1.0 agent as an `ASSERT
<https://github.com/microsoft/ASSERT>`_ ``target.callable`` so ASSERT's
``systematize -> test_set -> inference -> judge`` pipeline can drive a
multi-agent / agentic A2A system, while an Agent Control Specification
(ACS) manifest evaluates each turn's wire exchange. The ACS verdicts are
appended to the response the judge sees, so the judge can cite them as
evidence — realizing the "ASSERT finds the failure, ACS places the
control, ASSERT re-runs" loop at the A2A layer.

ASSERT contract (see ASSERT docs/targets/callable.md): a sync or async
callable ``chat(message: str, history: list[dict] | None) -> str``. We
return the agent's final text plus a compact ``<acs_governance>`` block
listing per-intervention-point verdicts.

Wire it into an ASSERT ``eval_config.yaml``::

    pipeline:
      inference:
        target:
          callable: examples.assert_integration.a2a_acs_target:chat

and point it at your agent + manifest via environment variables::

    A2A_TARGET_URL=https://my-agent.example.com
    A2A_RECEIVER=my-agent                 # tool/agent id used in snapshots
    ACS_MANIFEST=examples/acs/email-agent.acs.yaml

For a richer judge view (intermediate tool calls, routing), emit
OpenTelemetry spans from the agent and add a ``target.trace`` block — see
ASSERT's callable docs. This module uses the plain-text path so it runs
with no Phoenix/OpenInference dependency.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from a2a_testbed.acs import (
    AcsEvaluator,
    InterventionPoint,
    snapshot_for,
    validate_manifest,
)
from a2a_testbed.core.observer import WireExchange


A2A_RPC_PATH = "/a2a/v1/"

# Request-side and response-side wire-observable intervention points.
_PRE_POINTS = (InterventionPoint.INPUT, InterventionPoint.PRE_TOOL_CALL)
_POST_POINTS = (InterventionPoint.POST_TOOL_CALL, InterventionPoint.OUTPUT)


# ---------------------------------------------------------------------------
# Optional OpenTelemetry tracing (OpenInference conventions).
#
# When `opentelemetry` is installed AND a tracer provider is configured by
# the host (e.g. ASSERT's auto_trace / Phoenix), the spans below give the
# judge richer evidence than the text block alone: the A2A handoff as a
# TOOL span (name + input + output) plus each ACS verdict as a span
# attribute and event. With no provider configured, OTel hands back a
# no-op tracer, so this is zero-overhead and never raises. If the package
# isn't installed at all, the helpers degrade to plain context managers.
# Add a `target.trace` block to eval_config.yaml to have ASSERT read them.
# ---------------------------------------------------------------------------
from contextlib import contextmanager  # noqa: E402

try:  # pragma: no cover - import-guarded
    from opentelemetry import trace as _otel_trace

    _TRACER = _otel_trace.get_tracer("a2a_testbed.assert_integration")
    _OTEL = True
except Exception:  # noqa: BLE001
    _TRACER = None
    _OTEL = False


@contextmanager
def _span(name: str, kind: str, attrs: dict[str, Any]):
    """Start an OpenInference span, or a no-op when OTel is unavailable."""
    if not _OTEL or _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(name) as span:
        span.set_attribute("openinference.span.kind", kind)
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def _annotate_verdicts(span, verdicts: list[dict[str, Any]]) -> None:
    """Attach ACS verdicts to a span as attributes + events for the judge."""
    if span is None or not verdicts:
        return
    for v in verdicts:
        point = v.get("intervention_point", "unknown")
        decision = v.get("decision", "unknown")
        span.set_attribute(f"acs.{point}.decision", decision)
        if v.get("policy_id"):
            span.set_attribute(f"acs.{point}.policy", v["policy_id"])
        span.add_event(
            "acs.verdict",
            {
                "intervention_point": point,
                "decision": decision,
                "reasons": "; ".join(v.get("reasons") or []),
                "failed_closed": bool(v.get("failed_closed")),
            },
        )
    blocked = any(v.get("decision") in ("deny", "escalate") for v in verdicts)
    span.set_attribute("acs.blocked", blocked)


def build_request(message: str, *, context_id: Optional[str] = None) -> dict[str, Any]:
    """Build an A2A JSON-RPC ``message/send`` payload for one user turn.

    When ``context_id`` is given it is attached to the message so an A2A
    server can correlate turns of the same conversation (A2A multi-turn:
    the server maintains state keyed by ``contextId``).
    """
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": message}],
    }
    if context_id:
        msg["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": "assert-1",
        "method": "message/send",
        "params": {"message": msg, "configuration": {"blocking": True}},
    }


# ---------------------------------------------------------------------------
# Multi-turn helpers. ASSERT passes the conversation as `history` (OpenAI
# chat-messages, user/assistant only) with the current user turn at
# history[-1]. We send that latest turn under a stable A2A contextId
# derived from the conversation's opening user message, so a stateful A2A
# agent threads the turns together.
# ---------------------------------------------------------------------------


def _first_user_text(message: str, history: Optional[list[dict[str, str]]]) -> str:
    if history:
        for m in history:
            if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                return str(m["content"])
    return message


def derive_context_id(message: str, history: Optional[list[dict[str, str]]]) -> str:
    """A stable A2A contextId for the conversation (opening user turn)."""
    seed = _first_user_text(message, history)
    return "ctx-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def current_turn_text(message: str, history: Optional[list[dict[str, str]]]) -> str:
    """The latest user turn to send (history[-1]), falling back to message."""
    if history and isinstance(history[-1], dict) and history[-1].get("content"):
        return str(history[-1]["content"])
    return message


def extract_text(response_body: dict[str, Any]) -> str:
    """Pull the assistant's text out of an A2A response body, best-effort."""
    result = response_body.get("result", response_body)

    # Common A2A shapes: result.parts[].text, result.message.parts[].text,
    # or a plain string.
    def _parts_text(obj: Any) -> Optional[str]:
        parts = obj.get("parts") if isinstance(obj, dict) else None
        if isinstance(parts, list):
            texts = [p.get("text") for p in parts if isinstance(p, dict) and p.get("text")]
            if texts:
                return " ".join(texts)
        return None

    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for candidate in (result, result.get("message", {}), result.get("status", {})):
            text = _parts_text(candidate) if isinstance(candidate, dict) else None
            if text:
                return text
    return json.dumps(response_body)


async def evaluate_turn(
    manifest,
    evaluator: AcsEvaluator,
    receiver_id: str,
    payload: dict[str, Any],
    response_body: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate the manifest's wire-observable points for one turn."""
    verdicts: list[dict[str, Any]] = []
    wanted = set(_PRE_POINTS) | set(_POST_POINTS)
    for point in manifest.intervention_points:
        if point not in wanted:
            continue
        # Pre-points read the request; post-points read the response.
        body = {} if point in _PRE_POINTS else response_body
        exchange = WireExchange(receiver_id=receiver_id, request_body=payload, response_body=body)
        snapshot = snapshot_for(point, exchange, tools=manifest.tools)
        verdict = await evaluator.evaluate(manifest, point, snapshot)
        verdicts.append(verdict.model_dump(mode="json"))
    return verdicts


def render_for_judge(text: str, verdicts: list[dict[str, Any]]) -> str:
    """Append a compact ACS governance block so the judge can cite it."""
    if not verdicts:
        return text
    lines = ["<acs_governance>"]
    for v in verdicts:
        reason = "; ".join(v.get("reasons") or []) or v.get("rule_name") or ""
        fc = " fail_closed" if v.get("failed_closed") else ""
        lines.append(
            f"- {v.get('intervention_point')}: {v.get('decision')}{fc}"
            + (f" ({reason})" if reason else "")
        )
    lines.append("</acs_governance>")
    return f"{text}\n\n" + "\n".join(lines)


def _build_evaluator(manifest) -> AcsEvaluator:
    evaluator = AcsEvaluator(fail_closed=True)

    async def _noop_evidence(_canonical):
        return {}

    for decl in manifest.intervention_points.values():
        for ev_id in decl.evidence:
            evaluator.register_evidence(ev_id, _noop_evidence)
    return evaluator


def make_chat(agent_url: str, manifest_path: str | Path, *, receiver_id: str = "agent"):
    """Build an ASSERT-compatible ``chat`` callable for one agent+manifest."""
    result = validate_manifest(manifest_path)
    if result.manifest is None or not result.ok:
        problems = "; ".join(f.detail for f in result.findings if f.is_error)
        raise ValueError(f"invalid ACS manifest {manifest_path}: {problems}")
    manifest = result.manifest
    evaluator = _build_evaluator(manifest)
    endpoint = agent_url.rstrip("/") + A2A_RPC_PATH

    async def chat(message: str, history: Optional[list[dict[str, str]]] = None) -> str:
        # Multi-turn: send the latest user turn under a stable contextId so
        # a stateful A2A agent threads the conversation together.
        context_id = derive_context_id(message, history)
        turn_text = current_turn_text(message, history)
        payload = build_request(turn_text, context_id=context_id)
        with _span(
            "a2a_acs_target.chat",
            "AGENT",
            {"input.value": turn_text, "session.id": context_id},
        ) as agent_span:
            # The A2A handoff is modeled as a TOOL span (the remote agent
            # is the tool), so the judge can cite tool name + I/O.
            with _span(
                "a2a.handoff",
                "TOOL",
                {"tool.name": receiver_id, "input.value": turn_text},
            ) as tool_span:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(endpoint, json=payload)
                try:
                    body = resp.json()
                except Exception:  # noqa: BLE001
                    body = {}
                if not isinstance(body, dict):
                    body = {"result": body}
                text = extract_text(body)
                verdicts = await evaluate_turn(manifest, evaluator, receiver_id, payload, body)
                if tool_span is not None:
                    tool_span.set_attribute("output.value", text)
                _annotate_verdicts(tool_span, verdicts)

            out = render_for_judge(text, verdicts)
            if agent_span is not None:
                agent_span.set_attribute("output.value", out)
            return out

    return chat


# ---------------------------------------------------------------------------
# Default entry point referenced by eval_config.yaml. Configured via env so
# the same module serves any agent + manifest without code changes.
# ---------------------------------------------------------------------------

_DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "acs" / "email-agent.acs.yaml"
_chat = None


async def chat(message: str, history: Optional[list[dict[str, str]]] = None) -> str:
    """Env-configured ASSERT target. Lazily builds the per-agent callable.

    Requires ``A2A_TARGET_URL``. Optional: ``ACS_MANIFEST`` (defaults to
    the bundled email-agent manifest) and ``A2A_RECEIVER`` (the tool/agent
    id used when shaping ACS snapshots; defaults to ``agent``).
    """
    global _chat
    if _chat is None:
        url = os.environ.get("A2A_TARGET_URL")
        if not url:
            raise RuntimeError(
                "set A2A_TARGET_URL to the A2A agent endpoint this ASSERT target should drive"
            )
        manifest = os.environ.get("ACS_MANIFEST", str(_DEFAULT_MANIFEST))
        receiver = os.environ.get("A2A_RECEIVER", "agent")
        _chat = make_chat(url, manifest, receiver_id=receiver)
    return await _chat(message, history)
