# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Policy contract: an ACS manifest enforces its declared verdicts.

  Spec:    Agent Control Specification 0.3.1-beta — intervention points
  Source:  https://commandline.microsoft.com/agent-control-specification-runtime-governance/
  Clause:  Each intervention point evaluates a policy against the current
           snapshot and the policy can allow, warn, deny, or escalate.

Where the fail-closed contract proves the *error path*, this proves the
*happy path*: a manifest that should deny a given wire exchange does, and
one that should allow does. Built around an explicit (snapshot, expected
decision) pair so the same factory covers positive and negative cases —
the ACS analog of the conformance suite's skip-gracefully positive/negative
probes.
"""

from __future__ import annotations

from typing import Any

from a2a_testbed.acs.evaluator import AcsEvaluator
from a2a_testbed.acs.types import AcsManifest, Decision, InterventionPoint
from a2a_testbed.contracts.base import Contract, ContractCategory


def make_acs_enforcement_contract(
    manifest: AcsManifest,
    point: InterventionPoint,
    snapshot: dict[str, Any],
    expected: Decision,
    *,
    label: str = "",
    evaluator: AcsEvaluator | None = None,
) -> Contract:
    """Assert ``manifest`` yields ``expected`` for ``snapshot`` at ``point``."""
    suffix = f".{label}" if label else ""

    async def verify() -> str:
        ev = evaluator or AcsEvaluator(fail_closed=True)
        verdict = await ev.evaluate(manifest, point, snapshot)
        assert verdict.decision == expected, (
            f"expected {expected.value!r} at {point.value}, got "
            f"{verdict.decision.value!r} ({'; '.join(verdict.reasons)})"
        )
        cite = f" via rule {verdict.rule_name!r}" if verdict.rule_name else ""
        return f"{point.value} -> {verdict.decision.value}{cite}"

    return Contract(
        id=f"policy.acs_enforcement.{point.value}{suffix}",
        description=f"ACS manifest yields '{expected.value}' for the {point.value} snapshot",
        category=ContractCategory.POLICY,
        verify_fn=verify,
    )
