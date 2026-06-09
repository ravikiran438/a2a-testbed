# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for the ASSERT callable target (no network, no ASSERT install).

Exercises the pure pieces of examples/assert_integration/a2a_acs_target.py:
request building, response-text extraction, per-turn ACS evaluation, and
the judge-facing rendering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples.assert_integration.a2a_acs_target import (
    build_request,
    current_turn_text,
    derive_context_id,
    evaluate_turn,
    extract_text,
    render_for_judge,
)
from a2a_testbed.acs import AcsEvaluator, validate_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "examples" / "acs" / "three-party-governance.acs.yaml"


def test_build_request_shape():
    req = build_request("hello world")
    assert req["method"] == "message/send"
    assert req["params"]["message"]["parts"][0]["text"] == "hello world"
    assert "contextId" not in req["params"]["message"]
    # contextId is attached when provided.
    req2 = build_request("hi", context_id="ctx-abc")
    assert req2["params"]["message"]["contextId"] == "ctx-abc"


def test_multi_turn_context_and_latest_turn():
    convo = [
        {"role": "user", "content": "book a trip"},
        {"role": "assistant", "content": "where to?"},
        {"role": "user", "content": "Tokyo, under $2000"},
    ]
    # Latest user turn is what we send.
    assert current_turn_text("ignored", convo) == "Tokyo, under $2000"
    # Single-turn falls back to message.
    assert current_turn_text("just this", None) == "just this"
    # contextId is stable across turns of the same conversation...
    turn1 = [{"role": "user", "content": "book a trip"}]
    assert derive_context_id("book a trip", turn1) == derive_context_id("ignored", convo)
    # ...and differs for a different conversation.
    assert derive_context_id("book a trip", turn1) != derive_context_id("other", None)


def test_extract_text_variants():
    assert extract_text({"result": "plain"}) == "plain"
    assert extract_text({"result": {"parts": [{"text": "a"}, {"text": "b"}]}}) == "a b"
    assert extract_text({"result": {"message": {"parts": [{"text": "hi"}]}}}) == "hi"
    # Unknown shape falls back to a JSON dump (never throws).
    assert "weird" in extract_text({"weird": 1})


def test_render_for_judge_appends_block():
    verdicts = [
        {
            "intervention_point": "pre_tool_call",
            "decision": "deny",
            "reasons": ["external receiver"],
            "rule_name": "deny-external",
        }
    ]
    out = render_for_judge("the answer", verdicts)
    assert out.startswith("the answer")
    assert "<acs_governance>" in out
    assert "pre_tool_call: deny" in out
    assert "external receiver" in out
    # No verdicts -> unchanged text.
    assert render_for_judge("x", []) == "x"


@pytest.mark.asyncio
async def test_evaluate_turn_denies_external_receiver():
    manifest = validate_manifest(MANIFEST).manifest
    assert manifest is not None
    evaluator = AcsEvaluator(fail_closed=True)
    payload = build_request("grant_consent: deliver groceries")
    verdicts = await evaluate_turn(manifest, evaluator, "carol", payload, {})
    assert any(v["decision"] == "deny" for v in verdicts)

    # Internal receiver, benign content -> allow.
    allow = await evaluate_turn(manifest, evaluator, "bob", build_request("ping"), {})
    assert allow and all(v["decision"] == "allow" for v in allow)
