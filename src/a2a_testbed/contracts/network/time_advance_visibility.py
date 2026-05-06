# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Network contract: advance_time steps move the virtual clock and
that movement is visible in step results.

  Spec:    Original to a2a-testbed.
  Rationale: TTL/refresh testing requires deterministic time control.
           If a scenario step declares ``kind: advance_time`` with a
           positive ``advance_seconds``, the resulting StepResult must
           reflect the advance in its detail. Otherwise the user has
           no way to verify the time controller is wired correctly.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.core.types import ScenarioResult, StepKind


def make_time_advance_visibility_contract(result: ScenarioResult) -> Contract:
    async def verify() -> None:
        for step_result in result.steps:
            step = step_result.step
            if step.kind != StepKind.ADVANCE_TIME:
                continue
            seconds = step.advance_seconds or 0
            if seconds <= 0:
                continue
            assert step_result.passed, (
                f"advance_time step {step_result.step_index} did not pass"
            )
            assert "advanced" in step_result.detail.lower(), (
                f"advance_time step {step_result.step_index} must record "
                f"the advance in its detail; got {step_result.detail!r}"
            )
            # The detail message includes the seconds advanced
            assert str(seconds) in step_result.detail, (
                f"advance_time step {step_result.step_index} detail did not "
                f"mention {seconds}s; got {step_result.detail!r}"
            )

    return Contract(
        id="network.time_advance_visibility",
        description=(
            "advance_time steps record their advance in StepResult detail"
        ),
        category=ContractCategory.NETWORK,
        verify_fn=verify,
    )
