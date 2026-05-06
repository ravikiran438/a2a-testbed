# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Network contract: an observer agent registered for a scenario sees
every wire exchange that flowed through the network.

  Spec:    Original to a2a-testbed.
  Rationale: A2A is a per-agent specification — it normatively
           constrains how a single agent behaves on the wire, not how
           a network of agents coordinates. Multi-agent observability
           is a load-bearing precondition for protocols like NERVE
           (behavioral fingerprint accumulation across the network);
           without this contract, a network could silently drop observer
           notifications and break drift detection. The contract has
           no analog in the A2A specification because A2A doesn't
           define network topology — it leaves that to the integrator.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.core.observer import ObserverHub
from a2a_testbed.core.types import Scenario, ScenarioResult, StepKind


def make_observer_completeness_contract(
    scenario: Scenario,
    result: ScenarioResult,
    observer_hub: ObserverHub,
) -> Contract:
    async def verify() -> None:
        observer_ids = observer_hub.observers()
        if not observer_ids:
            # Scenario has no observers; contract is trivially satisfied.
            return

        completed_sends = sum(
            1
            for step_result in result.steps
            if step_result.step.kind == StepKind.SEND
            and step_result.passed
            and step_result.response_status is not None
        )

        for observer_id in observer_ids:
            wire_records = observer_hub.wire_history(observer_id)
            assert len(wire_records) >= completed_sends, (
                f"observer {observer_id!r} saw {len(wire_records)} wire records "
                f"but {completed_sends} send steps completed; expected ≥ that"
            )

    return Contract(
        id="network.observer_completeness",
        description=(
            "Every observer agent's wire history covers at least every "
            "completed send step in the scenario."
        ),
        category=ContractCategory.NETWORK,
        verify_fn=verify,
    )
