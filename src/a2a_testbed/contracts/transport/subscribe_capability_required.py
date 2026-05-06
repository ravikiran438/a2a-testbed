# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: tasks/resubscribe is gated on streaming capability.

  Spec:    A2A 1.0 §3.1.6 (SubscribeToTask), §9.5 (Errors)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Spec line 574: "If AgentCard.capabilities.streaming is
           false or not present, attempts to use SendStreamingMessage
           or SubscribeToTask operations MUST return
           UnsupportedOperationError." This contract handles the
           SubscribeToTask half of the rule — the streaming half is
           covered by ``streaming_capability_consistency``.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import (
    call_method,
    fetch_card,
)
from a2a_testbed.transport import Transport


_EXPECTED_CODE = -32004


def make_subscribe_capability_required_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        card = await fetch_card(transport, agent_url)
        if (card.get("capabilities") or {}).get("streaming") is True:
            return "skipped — agent advertises streaming=true (positive case)"
        envelope = await call_method(
            transport,
            agent_url,
            "tasks/resubscribe",
            {"id": str(uuid.uuid4())},
        )
        if "result" in envelope and envelope.get("error") is None:
            raise AssertionError(
                "agent advertises streaming=false but tasks/resubscribe "
                "returned a result; per §3.1.6 + §9.5 it MUST return "
                "UnsupportedOperationError (-32004)"
            )
        error = envelope.get("error") or {}
        code = error.get("code")
        if code == _EXPECTED_CODE:
            return None
        return (
            f"capability honored — agent refused tasks/resubscribe but "
            f"returned code {code} ({error.get('message') or '?'}); spec "
            f"mandates {_EXPECTED_CODE} (UnsupportedOperationError)"
        )

    return Contract(
        id="transport.subscribe_capability_required",
        description=(
            "tasks/resubscribe returns -32004 when streaming=false (§3.1.6)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
