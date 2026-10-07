# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: the send result is a Task or a Message, discriminated.

Spec:    A2A 1.0 §9.4.1 (SendMessage), §3.2.2 (SendMessageResponse)
Source:  docs/specification.md (LF AI & Data A2A repo)
Clause:  ``SendMessage`` returns a ``SendMessageResponse`` that
         contains exactly one of ``"task"`` or ``"message"`` — the
         ProtoJSON rendering of a oneof. Returning a bare Task (the
         0.3 shape) under the 1.0 method name breaks 1.0 clients,
         which parse the result strictly. For A2A 0.3 agents the
         result is the bare object discriminated by ``kind``
         (``"task"`` / ``"message"``), which is what is checked
         for them.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import AgentProbe, error_code
from a2a_testbed.transport import Transport

_ONEOF = ("task", "message")


def make_send_message_result_shape_contract(transport: Transport, agent_url: str) -> Contract:
    async def verify() -> str | None:
        probe = await AgentProbe.create(transport, agent_url)
        envelope = await probe.call("send", probe.send_params("result-shape probe"))
        if error_code(envelope) is not None:
            return (
                f"skipped — {probe.method('send')} returned error "
                f"{envelope['error'].get('code')}; result shape not observable"
            )
        result = envelope.get("result")
        assert isinstance(result, dict), (
            f"{probe.method('send')} result MUST be an object; got {type(result).__name__}"
        )
        if probe.is_legacy:
            kind = result.get("kind")
            assert kind in _ONEOF, (
                f"A2A 0.3 message/send result MUST be a Task or Message with "
                f"kind 'task' / 'message'; got kind={kind!r}"
            )
            return f"A2A 0.3 result kind={kind!r}"
        present = [k for k in _ONEOF if k in result]
        assert len(present) == 1, (
            f"SendMessage result MUST contain exactly one of 'task' / 'message' "
            f"(SendMessageResponse, §3.2.2); got keys {sorted(result.keys())}"
            + (
                " — this looks like a bare Task (the A2A 0.3 shape)"
                if "status" in result and "id" in result
                else ""
            )
        )
        inner = result[present[0]]
        assert isinstance(inner, dict), f"result.{present[0]} MUST be an object"
        assert set(result.keys()) == {present[0]}, (
            f"SendMessage result carries extra keys beside {present[0]!r}: "
            f"{sorted(set(result.keys()) - {present[0]})}"
        )
        return None

    return Contract(
        id="transport.send_message_result_shape",
        description=("SendMessage result is exactly one of {task} / {message} (§9.4.1, §3.2.2)"),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
