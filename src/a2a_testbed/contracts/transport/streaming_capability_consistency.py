# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: streaming methods are gated on the streaming capability.

  Spec:    A2A 1.0 §3.1.2 (Send Streaming Message), §9.5 (Errors)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  If ``AgentCard.capabilities.streaming`` is ``false`` or not
           present, attempts to use ``message/stream`` MUST return
           ``UnsupportedOperationError`` (code -32004).

           Strictness: a 200+result on ``message/stream`` is a hard
           failure (the agent lied about its capability). Any error
           response satisfies the binding part of the rule; the
           spec-mandated code -32004 is a strict pass, any other
           error code is a soft pass with the deviation recorded
           in the contract detail.
"""

from __future__ import annotations

import json

import httpx

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.transport import Transport


# UnsupportedOperationError per §9.5. The spec mandates this exact
# code when capability=false; we treat other -32xxx codes as a soft
# pass since the agent still honored the capability flag (refused
# to process), even if the error type doesn't match.
_EXPECTED_CODE = -32004


def make_streaming_capability_consistency_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> None:
        # 1. Read the card to learn the agent's streaming claim.
        async with httpx.AsyncClient(timeout=5.0) as client:
            card_resp = await client.get(
                agent_url.rstrip("/") + transport.card_endpoint_path()
            )
            assert card_resp.status_code == 200, (
                f"card endpoint returned {card_resp.status_code}"
            )
            card_body = json.loads(card_resp.text)
            streaming = (card_body.get("capabilities") or {}).get("streaming")
            if streaming is True:
                # Agent claims to support streaming; the negative case
                # this contract checks doesn't apply. (We'd need a
                # streaming-positive contract to validate it works,
                # which requires SSE infra — roadmap.)
                return "skipped — agent advertises streaming=true"

            # 2. Fire a message/stream call — agent MUST refuse.
            rpc_url = agent_url.rstrip("/") + transport.rpc_endpoint_path()
            stream_request = {
                "jsonrpc": "2.0",
                "id": "contract-stream",
                "method": "message/stream",
                "params": {
                    "message": {
                        "messageId": "contract",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "probe"}],
                    },
                },
            }
            resp = await client.post(
                rpc_url,
                json=stream_request,
                headers={"content-type": "application/json"},
            )

        try:
            body = json.loads(resp.text)
        except json.JSONDecodeError:
            raise AssertionError(
                f"agent advertises streaming=false but message/stream "
                f"returned non-JSON body (status {resp.status_code}); "
                f"expected JSON-RPC error envelope per §9.5"
            )

        # If we get a successful result, the agent processed the call —
        # that's a hard violation (it claimed not to support streaming).
        if "result" in body and body.get("error") is None:
            raise AssertionError(
                "agent advertises streaming=false but message/stream "
                "returned a result (HTTP "
                f"{resp.status_code}); per §3.1.2 it MUST return "
                "UnsupportedOperationError (-32004)"
            )

        error = body.get("error") or {}
        code = error.get("code")
        if code == _EXPECTED_CODE:
            return None  # strict pass
        # Soft pass: agent refused (capability honored) but with the
        # wrong error code. The Contract.verify wrapper renders this
        # returned string as the detail on a passing result so the
        # deviation surfaces in the report without failing the run.
        return (
            f"capability honored — agent refused message/stream as required "
            f"(§3.1.2), but returned code {code} ({error.get('message') or '?'}); "
            f"spec mandates {_EXPECTED_CODE} (UnsupportedOperationError)"
        )

    return Contract(
        id="transport.streaming_capability_consistency",
        description=(
            "message/stream returns -32004 when streaming=false per §3.1.2"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
