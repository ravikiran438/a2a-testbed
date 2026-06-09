# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Policy contract: an ACS control layer must fail closed.

  Spec:    Agent Control Specification 0.3.1-beta — fail-closed handling
  Source:  https://commandline.microsoft.com/agent-control-specification-runtime-governance/
  Clause:  "what happens when policy, evidence, or verdict processing
           fails" — the action must be denied, never silently allowed.

This is the testbed's signature ACS check and a natural fit for its
fault-injection heritage: the same way ``core/faults.py`` corrupts a
wire response to prove the orchestrator surfaces it, here we make an
evidence provider and a policy backend *fail* and prove the verdict
resolves to ``deny`` with ``failed_closed=True`` rather than ``allow``.

Two failure modes are exercised against the supplied manifest:

1. **Evidence failure** — a registered evidence provider raises (the
   analog of an ``http_error`` / ``corrupt`` fault hitting a classifier
   or DLP endpoint). Verdict must deny.
2. **Policy-backend failure** — the policy engine raises mid-evaluation.
   Verdict must deny.

A control layer that fails *open* under either condition is a critical
defect: that is exactly the gap ACS exists to close.
"""

from __future__ import annotations

from typing import Any, Optional

from a2a_testbed.acs.evaluator import AcsEvaluator
from a2a_testbed.acs.types import (
    AcsManifest,
    CanonicalInput,
    Decision,
    InterventionPoint,
    PolicyDecl,
    PolicyType,
    Verdict,
)
from a2a_testbed.contracts.base import Contract, ContractCategory


async def _exploding_evidence(_canonical: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("synthetic evidence-provider failure")


async def _exploding_backend(_policy: PolicyDecl, _canonical: CanonicalInput) -> Verdict:
    raise RuntimeError("synthetic policy-backend failure")


def make_acs_fail_closed_contract(
    manifest: AcsManifest,
    point: InterventionPoint,
    snapshot: dict[str, Any],
    *,
    evidence_provider_id: Optional[str] = None,
) -> Contract:
    """Build the fail-closed contract for one intervention point.

    ``snapshot`` is any host snapshot valid for ``point`` (e.g. from
    ``acs.snapshot_for``). ``evidence_provider_id``, when given, must be
    an evidence id the manifest's intervention point lists, so the
    evidence-failure path is actually reached.
    """

    async def verify() -> str:
        # -- evidence failure -------------------------------------
        if evidence_provider_id is not None:
            ev_eval = AcsEvaluator(fail_closed=True)
            ev_eval.register_evidence(evidence_provider_id, _exploding_evidence)
            ev_verdict = await ev_eval.evaluate(manifest, point, snapshot)
            assert ev_verdict.decision == Decision.DENY, (
                f"evidence failure produced {ev_verdict.decision.value!r}, "
                f"expected 'deny' (fail-closed violated)"
            )
            assert ev_verdict.failed_closed, "evidence-failure verdict not marked failed_closed"

        # -- policy-backend failure -------------------------------
        pb_eval = AcsEvaluator(fail_closed=True)
        pb_eval.register_policy_backend(PolicyType.BUILTIN, _exploding_backend)
        pb_eval.register_policy_backend(PolicyType.REGO, _exploding_backend)
        pb_verdict = await pb_eval.evaluate(manifest, point, snapshot)
        assert pb_verdict.decision == Decision.DENY, (
            f"policy-backend failure produced {pb_verdict.decision.value!r}, "
            f"expected 'deny' (fail-closed violated)"
        )
        assert pb_verdict.failed_closed, "policy-failure verdict not marked failed_closed"

        return f"fail-closed honored at {point.value}"

    return Contract(
        id=f"policy.acs_fail_closed.{point.value}",
        description=("ACS control fails closed (deny) when evidence or policy evaluation errors"),
        category=ContractCategory.POLICY,
        verify_fn=verify,
    )
