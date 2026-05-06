# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Network contract: fault-injected steps surface as failures, not silently pass.

  Spec:    Original to a2a-testbed.
  Rationale: When a scenario declares ``fault: drop``, the testbed
           must record the step as a failure rather than silently
           skipping. This is a property of the orchestrator, not the
           agent under test, but it's load-bearing for using the
           testbed as a regression suite — drops/timeouts/errors must
           be visible in the report.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.core.types import FaultKind, ScenarioResult, StepKind


def make_fault_recovery_contract(result: ScenarioResult) -> Contract:
    async def verify() -> None:
        for step_result in result.steps:
            step = step_result.step
            if step.kind != StepKind.SEND or step.fault is None:
                continue
            if step.fault.kind == FaultKind.NONE:
                continue
            if step.fault.kind == FaultKind.DROP:
                # DROP must surface as a failure (no response received)
                assert not step_result.passed, (
                    f"step {step_result.step_index} declared fault=drop but "
                    f"recorded as passed; orchestrator must surface drops"
                )
                assert "drop" in step_result.detail.lower(), (
                    f"step {step_result.step_index}: drop fault must be named "
                    f"in the result detail"
                )
            elif step.fault.kind == FaultKind.HTTP_ERROR:
                # HTTP_ERROR must produce the configured status code
                expected = step.fault.http_status
                assert step_result.response_status == expected, (
                    f"step {step_result.step_index} declared "
                    f"fault=http_error status={expected} but observed "
                    f"status={step_result.response_status}"
                )

    return Contract(
        id="network.fault_recovery",
        description=(
            "Fault-injected steps record as the right failure shape "
            "(orchestrator integrity)"
        ),
        category=ContractCategory.NETWORK,
        verify_fn=verify,
    )
