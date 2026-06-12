"""Project ACS governance verdicts into AG-UI events.

AG-UI (Agent-User Interaction protocol) is the agent <-> human transport. The
testbed already evaluates inter-agent exchanges against an Agent Control
Specification (ACS) manifest and produces a normalized ``Verdict``
(allow / warn / deny / escalate). This module renders those verdicts onto the
AG-UI event stream under the cross-cutting "Governance over AG-UI" convention,
so a governed scenario can be replayed with a human in the loop:

  * ``allow``    -> a ``CUSTOM`` annotation; the run continues.
  * ``warn``     -> a ``CUSTOM`` annotation (surfaced, non-blocking); continues.
  * ``deny``     -> a terminal ``RUN_ERROR``; the action is blocked.
  * ``escalate`` -> a ``RUN_FINISHED`` **interrupt** (reason ``confirmation``):
    the run pauses for human review; the resume decides allow vs. deny.

The escalation path is the point of the exercise: ACS ``escalate`` is exactly a
human-in-the-loop gate, and AG-UI interrupts are the standard mechanism for it.
Resolution is **fail-closed** — an abandoned (``cancelled``) or un-approved
resume resolves to ``deny``.

Output events are plain JSON-serializable dicts (no AG-UI SDK dependency).
Governance identity travels in ``metadata.governance.uri`` so a governance-aware
client routes the interrupt while a generic client falls back to ``message`` +
``responseSchema``.
"""

from __future__ import annotations

from typing import Any

from a2a_testbed.acs.types import Decision, Verdict

# Stable governance identity for ACS verdicts on the AG-UI transport. Mirrors
# the role the per-protocol extension URI plays for the published protocols.
ACS_GOVERNANCE_URI = "acs"

GOVERNANCE_KEY = "governance"

_APPROVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {
            "type": "boolean",
            "description": "True to allow the escalated action, false to deny it.",
        },
    },
    "required": ["approved"],
}


def _governance_meta(verdict: Verdict) -> dict[str, Any]:
    return {
        "uri": ACS_GOVERNANCE_URI,
        "type": "Verdict",
        "decision": verdict.decision.value,
        "intervention_point": verdict.intervention_point.value,
        "policy_id": verdict.policy_id,
        "rule_name": verdict.rule_name,
        "failed_closed": verdict.failed_closed,
    }


def _reason_text(verdict: Verdict) -> str:
    return "; ".join(verdict.reasons) if verdict.reasons else verdict.decision.value


def project_verdict(verdict: Verdict) -> dict[str, Any]:
    """Render one ACS ``Verdict`` as a single AG-UI event.

    ``escalate`` becomes a human-in-the-loop interrupt; ``deny`` a terminal
    ``RUN_ERROR``; ``allow`` / ``warn`` a ``CUSTOM`` annotation.
    """
    meta = _governance_meta(verdict)

    if verdict.decision is Decision.ESCALATE:
        return {
            "type": "RUN_FINISHED",
            "outcome": {
                "type": "interrupt",
                "interrupts": [
                    {
                        "id": f"acs-escalate-{verdict.intervention_point.value}",
                        "reason": "confirmation",
                        "message": _reason_text(verdict),
                        "responseSchema": _APPROVAL_SCHEMA,
                        "metadata": {GOVERNANCE_KEY: meta},
                    }
                ],
            },
        }

    if verdict.decision is Decision.DENY:
        return {
            "type": "RUN_ERROR",
            "message": _reason_text(verdict),
            "code": "acs_deny",
            "metadata": {GOVERNANCE_KEY: meta},
        }

    # ALLOW or WARN: a non-blocking annotation the UI can surface.
    return {
        "type": "CUSTOM",
        "name": ACS_GOVERNANCE_URI,
        "value": {
            "decision": verdict.decision.value,
            "intervention_point": verdict.intervention_point.value,
            "reasons": list(verdict.reasons),
            "policy_id": verdict.policy_id,
        },
    }


def resolve_escalation(*, interrupt: dict[str, Any], resume: dict[str, Any]) -> Decision:
    """Resolve a human's response to an ACS escalation interrupt.

    Returns ``Decision.ALLOW`` only when the resume is ``resolved`` with
    ``payload.approved == true``. Everything else — explicit denial, a
    ``cancelled`` (abandoned) resume, or a missing payload — resolves
    **fail-closed** to ``Decision.DENY``. Raises ``ValueError`` if the interrupt
    is not an ACS escalation (governance identity check).
    """
    gov = (interrupt.get("metadata") or {}).get(GOVERNANCE_KEY) or {}
    if gov.get("uri") != ACS_GOVERNANCE_URI or gov.get("decision") != "escalate":
        raise ValueError("interrupt is not an ACS escalation")

    if resume.get("status") != "resolved":
        return Decision.DENY  # cancelled / abandoned -> fail-closed
    payload = resume.get("payload") or {}
    return Decision.ALLOW if payload.get("approved") is True else Decision.DENY
