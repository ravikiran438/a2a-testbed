# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""External-card validation: run every transport contract against a card
that was authored to A2A 1.0 spec without reference to our contract list.

Rationale: our contracts cite A2A 1.0 spec sections; this test demonstrates
they pass on a card written from the spec, not from our test surface.
This is the closest we can get to "in the wild" validation given there
are no widely-deployed public A2A 1.0 agents at the time of this test.

The fixture card declares no extensions; the transport contracts cover
the core spec. Count is asserted against ``transport_contracts(...)``
so it tracks the runner automatically as new clauses land.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2a_testbed.contracts.runner import (
    run_transport_contracts,
    summarize,
    transport_contracts,
)
from a2a_testbed.core.loader import load_agent_card_from_path
from a2a_testbed.network.multitenant import MultiTenantNetwork
from a2a_testbed.runtimes.python_inproc import PythonInProcRuntime
from a2a_testbed.transport import A2ATransport


REPO_ROOT = Path(__file__).resolve().parents[2]


# Pick a card from the example fixtures that was authored to be A2A-spec
# compliant, not retro-fitted to satisfy our contracts.
EXTERNAL_CARD_PATH = (
    REPO_ROOT / "examples" / "agent-cards" / "three-party" / "carol.json"
)


@pytest.mark.asyncio
async def test_all_transport_contracts_pass_on_external_card():
    """Every spec-derived transport contract passes on a card we did not
    author to satisfy contracts. This proves the contracts are
    spec-grounded, not test-tailored."""
    if not EXTERNAL_CARD_PATH.exists():
        pytest.skip(f"fixture missing: {EXTERNAL_CARD_PATH}")

    card = load_agent_card_from_path(EXTERNAL_CARD_PATH)
    transport = A2ATransport()

    net = MultiTenantNetwork(transport=transport, log_level="error")
    runtime = PythonInProcRuntime("external-agent", card, scripts={})
    net.register(runtime)

    async with net:
        url = net.url_of("external-agent")
        results = await run_transport_contracts(transport, url)

    summary = summarize(results)
    failed = [r for r in results if not r.passed]
    assert summary["failed"] == 0, [
        f"{r.contract_id}: {r.detail}" for r in failed
    ]
    # Sanity: every transport contract registered should have run.
    expected = len(transport_contracts(transport, "http://placeholder"))
    assert summary["total"] == expected, (
        f"expected {expected} contracts to run, got {summary['total']}"
    )
