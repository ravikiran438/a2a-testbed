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

Output events are plain JSON-serializable dicts (no AG-UI SDK dependency)
that validate against the AG-UI 1.0 event schemas (``AG_UI_PROTOCOL_VERSION``;
checked against the official ``ag-ui-protocol`` models in the test suite).
Governance identity travels in ``metadata.governance.uri`` so a governance-aware
client routes the interrupt while a generic client falls back to ``message`` +
``responseSchema``.

AG-UI 1.0 notes:

  * ``RUN_FINISHED`` requires ``threadId`` and ``runId``. Pass the ids of the
    run being governed; the defaults are placeholders for standalone use.
  * Each escalation gets a unique interrupt ``id`` so two escalations at the
    same intervention point in one thread cannot be confused on resume.
  * ``RunAgentInput.resume`` is an array of entries keyed by ``interruptId``;
    ``resolve_escalation`` accepts that array (or one entry) and resolves the
    entry addressed to the interrupt — a missing entry fails closed.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Optional

from a2a_testbed.acs.types import Decision, Verdict

# The AG-UI protocol version these events are shaped for.
AG_UI_PROTOCOL_VERSION = "1.0"

# Placeholder ids for a verdict projected outside a real AG-UI run.
DEFAULT_THREAD_ID = "acs-governance"
DEFAULT_RUN_ID = "acs-governance-run"

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


def _new_interrupt_id(verdict: Verdict) -> str:
    return f"acs-escalate-{verdict.intervention_point.value}-{uuid.uuid4().hex[:12]}"


def project_verdict(
    verdict: Verdict,
    *,
    thread_id: str = DEFAULT_THREAD_ID,
    run_id: str = DEFAULT_RUN_ID,
    interrupt_id: Optional[str] = None,
) -> dict[str, Any]:
    """Render one ACS ``Verdict`` as a single AG-UI event.

    ``escalate`` becomes a human-in-the-loop interrupt; ``deny`` a terminal
    ``RUN_ERROR``; ``allow`` / ``warn`` a ``CUSTOM`` annotation.
    ``thread_id`` / ``run_id`` identify the governed run (required on
    ``RUN_FINISHED`` in AG-UI 1.0); ``interrupt_id`` overrides the generated,
    unique interrupt id.
    """
    meta = _governance_meta(verdict)

    if verdict.decision is Decision.ESCALATE:
        return {
            "type": "RUN_FINISHED",
            "threadId": thread_id,
            "runId": run_id,
            "outcome": {
                "type": "interrupt",
                "interrupts": [
                    {
                        "id": interrupt_id or _new_interrupt_id(verdict),
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


def _resume_entry_for(
    interrupt_id: Any, resume: Mapping[str, Any] | Sequence[Mapping[str, Any]]
) -> Optional[Mapping[str, Any]]:
    """The resume entry addressed to ``interrupt_id``, or ``None``.

    ``resume`` is either the AG-UI 1.0 ``RunAgentInput.resume`` array or a
    single entry. In the array, entries are matched on ``interruptId``. A
    single entry is accepted when its ``interruptId`` matches or is absent
    (callers that already picked the entry); a mismatched id is rejected.
    """
    if isinstance(resume, Mapping):
        rid = resume.get("interruptId")
        return resume if rid is None or rid == interrupt_id else None
    for entry in resume:
        if isinstance(entry, Mapping) and entry.get("interruptId") == interrupt_id:
            return entry
    return None


def resolve_escalation(
    *,
    interrupt: Mapping[str, Any],
    resume: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> Decision:
    """Resolve a human's response to an ACS escalation interrupt.

    ``resume`` is the AG-UI ``RunAgentInput.resume`` array or a single entry
    from it. Returns ``Decision.ALLOW`` only when the entry addressed to this
    interrupt is ``resolved`` with ``payload.approved == true``. Everything
    else — explicit denial, a ``cancelled`` (abandoned) resume, a missing
    payload, or no entry for this interrupt — resolves **fail-closed** to
    ``Decision.DENY``. Raises ``ValueError`` if the interrupt is not an ACS
    escalation (governance identity check).
    """
    gov = (interrupt.get("metadata") or {}).get(GOVERNANCE_KEY) or {}
    if gov.get("uri") != ACS_GOVERNANCE_URI or gov.get("decision") != "escalate":
        raise ValueError("interrupt is not an ACS escalation")

    entry = _resume_entry_for(interrupt.get("id"), resume)
    if entry is None:
        return Decision.DENY  # no answer for this interrupt -> fail-closed
    if entry.get("status") != "resolved":
        return Decision.DENY  # cancelled / abandoned -> fail-closed
    payload = entry.get("payload")
    approved = payload.get("approved") if isinstance(payload, Mapping) else None
    return Decision.ALLOW if approved is True else Decision.DENY
