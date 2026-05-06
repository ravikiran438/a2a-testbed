# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: client-provided contextId is preserved or rejected.

  Spec:    A2A 1.0 §3.4.2 (ContextId semantics)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  Spec line 593: "If an agent cannot accept a client-provided
           contextId, it MUST reject the request with an error and
           MUST NOT generate a new contextId for the response." The
           agent has two valid behaviors: accept the client's
           contextId (preserve it on the returned Task) or refuse
           with an error. Generating a different contextId silently
           is non-conformant — clients lose the conversational
           thread they tried to continue.
"""

from __future__ import annotations

import uuid

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import probe_for_task
from a2a_testbed.transport import Transport


def make_task_context_id_echoed_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        client_context = "ctx-" + uuid.uuid4().hex[:12]
        task = await probe_for_task(
            transport, agent_url, context_id=client_context
        )
        if task is None:
            return (
                "skipped — agent did not return a Task envelope, or "
                "rejected the client-provided contextId (§3.4.2 line 593 "
                "permits rejection)"
            )
        agent_context = task.get("contextId")
        if agent_context == client_context:
            return None  # accepted + preserved
        # Agent silently produced a different contextId — non-conformant.
        if isinstance(agent_context, str) and agent_context:
            raise AssertionError(
                f"agent produced a different contextId {agent_context!r} "
                f"after the client supplied {client_context!r}; per §3.4.2 "
                "the agent must EITHER preserve the client value OR reject "
                "the request — silently substituting is non-conformant"
            )
        # Missing contextId on a response Task is also a violation
        # of §3.4.2 line 591 (agent-generated contextIds MUST be
        # included in the response).
        raise AssertionError(
            "Task.contextId is missing from the response; §3.4.2 line 591 "
            "requires it be included in any response that establishes one"
        )

    return Contract(
        id="transport.task_context_id_echoed",
        description=(
            "Client-provided contextId is preserved on the response Task "
            "or the request is rejected (§3.4.2)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
