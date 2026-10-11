"""Tests for the AG-UI projection of ACS verdicts (Governance over AG-UI)."""

from __future__ import annotations

import pytest

from a2a_testbed.acs.types import Decision, InterventionPoint, Verdict
from a2a_testbed.ag_ui import (
    ACS_GOVERNANCE_URI,
    AG_UI_PROTOCOL_VERSION,
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


# --- AG-UI 1.0 -------------------------------------------------------------


def test_escalation_carries_run_identity():
    ev = project_verdict(_verdict(Decision.ESCALATE))
    assert ev["threadId"] and ev["runId"]
    ev = project_verdict(_verdict(Decision.ESCALATE), thread_id="t-1", run_id="r-1")
    assert (ev["threadId"], ev["runId"]) == ("t-1", "r-1")


def test_interrupt_ids_are_unique_per_escalation():
    a = _escalation_interrupt()["id"]
    b = _escalation_interrupt()["id"]
    assert a != b
    assert a.startswith("acs-escalate-pre_tool_call-")
    ev = project_verdict(_verdict(Decision.ESCALATE), interrupt_id="fixed")
    assert ev["outcome"]["interrupts"][0]["id"] == "fixed"


def test_resume_array_resolves_the_matching_entry():
    it = _escalation_interrupt()
    other = _escalation_interrupt()
    resume = [
        {"interruptId": other["id"], "status": "resolved", "payload": {"approved": False}},
        {"interruptId": it["id"], "status": "resolved", "payload": {"approved": True}},
    ]
    assert resolve_escalation(interrupt=it, resume=resume) is Decision.ALLOW
    assert resolve_escalation(interrupt=other, resume=resume) is Decision.DENY


def test_resume_array_without_an_entry_fails_closed():
    it = _escalation_interrupt()
    other = _escalation_interrupt()
    resume = [{"interruptId": other["id"], "status": "resolved", "payload": {"approved": True}}]
    assert resolve_escalation(interrupt=it, resume=resume) is Decision.DENY
    assert resolve_escalation(interrupt=it, resume=[]) is Decision.DENY


def test_resume_entry_for_another_interrupt_fails_closed():
    it = _escalation_interrupt()
    entry = {"interruptId": "someone-else", "status": "resolved", "payload": {"approved": True}}
    assert resolve_escalation(interrupt=it, resume=entry) is Decision.DENY


def test_resume_entry_without_interrupt_id_is_still_accepted():
    it = _escalation_interrupt()
    entry = {"status": "resolved", "payload": {"approved": True}}
    assert resolve_escalation(interrupt=it, resume=entry) is Decision.ALLOW


def test_non_object_payload_fails_closed():
    it = _escalation_interrupt()
    entry = {"interruptId": it["id"], "status": "resolved", "payload": "yes"}
    assert resolve_escalation(interrupt=it, resume=entry) is Decision.DENY


@pytest.mark.parametrize("decision", list(Decision))
@pytest.mark.parametrize("policy_id", ["pii-guard", None])
def test_events_validate_against_official_ag_ui_models(decision, policy_id):
    core = pytest.importorskip("ag_ui.core")
    assert core.PROTOCOL_VERSION == AG_UI_PROTOCOL_VERSION
    verdict = Verdict(
        decision=decision,
        intervention_point=InterventionPoint.PRE_TOOL_CALL,
        policy_id=policy_id,
        reasons=["r"],
    )
    ev = project_verdict(verdict)
    model = {
        "RUN_FINISHED": core.RunFinishedEvent,
        "RUN_ERROR": core.RunErrorEvent,
        "CUSTOM": core.CustomEvent,
    }[ev["type"]]
    parsed = model.model_validate(ev)
    # Round-trips through the official model without losing anything.
    assert parsed.model_dump(mode="json", by_alias=True, exclude_unset=True) == ev


def test_resume_entries_validate_against_official_ag_ui_models():
    core = pytest.importorskip("ag_ui.core")
    it = _escalation_interrupt()
    for entry in (
        {"interruptId": it["id"], "status": "resolved", "payload": {"approved": True}},
        {"interruptId": it["id"], "status": "cancelled"},
    ):
        core.ResumeEntry.model_validate(entry)
        core.Interrupt.model_validate(it)
