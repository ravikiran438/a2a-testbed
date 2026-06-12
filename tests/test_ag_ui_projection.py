"""Tests for the AG-UI projection of ACS verdicts (Governance over AG-UI)."""

from __future__ import annotations

import pytest

from a2a_testbed.acs.types import Decision, InterventionPoint, Verdict
from a2a_testbed.ag_ui import (
    ACS_GOVERNANCE_URI,
    GOVERNANCE_KEY,
    project_verdict,
    resolve_escalation,
)


def _verdict(decision: Decision, reasons=None) -> Verdict:
    return Verdict(
        decision=decision,
        intervention_point=InterventionPoint.PRE_TOOL_CALL,
        policy_id="pii-guard",
        reasons=reasons or [f"{decision.value} by policy"],
        rule_name="rule-1",
    )


def _escalation_interrupt():
    ev = project_verdict(_verdict(Decision.ESCALATE, ["needs human review"]))
    return ev["outcome"]["interrupts"][0]


def test_allow_projects_to_custom_annotation():
    ev = project_verdict(_verdict(Decision.ALLOW))
    assert ev["type"] == "CUSTOM"
    assert ev["name"] == ACS_GOVERNANCE_URI
    assert ev["value"]["decision"] == "allow"


def test_warn_projects_to_custom_annotation():
    ev = project_verdict(_verdict(Decision.WARN))
    assert ev["type"] == "CUSTOM"
    assert ev["value"]["decision"] == "warn"


def test_deny_projects_to_run_error():
    ev = project_verdict(_verdict(Decision.DENY, ["recipient on block list"]))
    assert ev["type"] == "RUN_ERROR"
    assert ev["code"] == "acs_deny"
    assert "block list" in ev["message"]


def test_escalate_projects_to_interrupt():
    ev = project_verdict(_verdict(Decision.ESCALATE, ["needs human review"]))
    assert ev["type"] == "RUN_FINISHED"
    assert ev["outcome"]["type"] == "interrupt"
    it = ev["outcome"]["interrupts"][0]
    assert it["reason"] == "confirmation"
    assert "approved" in it["responseSchema"]["properties"]
    gov = it["metadata"][GOVERNANCE_KEY]
    assert gov["uri"] == ACS_GOVERNANCE_URI
    assert gov["decision"] == "escalate"
    assert gov["intervention_point"] == "pre_tool_call"


def test_resolve_approved_allows():
    it = _escalation_interrupt()
    decision = resolve_escalation(
        interrupt=it,
        resume={"interruptId": it["id"], "status": "resolved", "payload": {"approved": True}},
    )
    assert decision is Decision.ALLOW


def test_resolve_not_approved_denies():
    it = _escalation_interrupt()
    decision = resolve_escalation(
        interrupt=it,
        resume={"interruptId": it["id"], "status": "resolved", "payload": {"approved": False}},
    )
    assert decision is Decision.DENY


def test_resolve_cancelled_fails_closed_to_deny():
    it = _escalation_interrupt()
    decision = resolve_escalation(
        interrupt=it, resume={"interruptId": it["id"], "status": "cancelled"}
    )
    assert decision is Decision.DENY


def test_resolve_missing_payload_fails_closed():
    it = _escalation_interrupt()
    decision = resolve_escalation(
        interrupt=it, resume={"interruptId": it["id"], "status": "resolved"}
    )
    assert decision is Decision.DENY


def test_resolve_rejects_non_acs_interrupt():
    foreign = {
        "id": "x",
        "reason": "confirmation",
        "metadata": {GOVERNANCE_KEY: {"uri": "https://example.com/other", "decision": "escalate"}},
    }
    with pytest.raises(ValueError):
        resolve_escalation(
            interrupt=foreign,
            resume={"interruptId": "x", "status": "resolved", "payload": {"approved": True}},
        )


def test_blocking_decisions():
    assert Decision.DENY.blocks and Decision.ESCALATE.blocks
    assert not Decision.ALLOW.blocks and not Decision.WARN.blocks
