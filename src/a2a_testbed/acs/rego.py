# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Rego policy backend for the ACS evaluator (via OPA).

ACS's reference shape evaluates `type: rego` policies with
`Open Policy Agent <https://www.openpolicyagent.org/>`_. The core
evaluator ships only the dependency-free ``builtin`` engine and fails
closed on ``rego`` policies when no backend is registered; this module
provides that backend by shelling out to the ``opa`` binary, so a
manifest authored against the ACS reference (Rego bundle + query) runs
unchanged in the testbed.

Register it on an evaluator::

    from a2a_testbed.acs import AcsEvaluator
    from a2a_testbed.acs.rego import register_rego_backend

    evaluator = AcsEvaluator(fail_closed=True)
    register_rego_backend(evaluator)          # uses `opa` on PATH

The canonical ACS policy input (``intervention_point`` / ``policy_target``
/ ``snapshot`` / ``annotations`` / ``tool``) is passed to OPA as the
``input`` document, so a Rego rule reads e.g.
``input.policy_target.value.message.to``. The policy's ``query`` (e.g.
``data.email_agent.verdict``) must evaluate to either a decision string
(``allow`` / ``warn`` / ``deny`` / ``escalate``) or an object
``{"decision": "...", "reasons": [...], "rule": "..."}``. Anything else
fails closed.

Requires the OPA binary (``brew install opa`` / see OPA docs). Without it,
``RegoBackend.is_available()`` is False and evaluation fails closed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any, Optional

from a2a_testbed.acs.types import (
    CanonicalInput,
    Decision,
    InterventionPoint,
    PolicyDecl,
    PolicyType,
    Verdict,
)


_VALID_DECISIONS = {d.value for d in Decision}


def verdict_from_opa_value(value: Any, point: InterventionPoint) -> Verdict:
    """Map an OPA query result into a normalized ACS verdict.

    Pure function (no subprocess) so the mapping is unit-testable. Unknown
    or missing decisions fail closed.
    """
    if isinstance(value, str):
        dec = value.strip().lower()
        if dec in _VALID_DECISIONS:
            return Verdict(
                decision=Decision(dec),
                intervention_point=point,
                reasons=["rego policy returned decision"],
            )
        return Verdict(
            decision=Decision.DENY,
            intervention_point=point,
            reasons=[f"rego returned unknown decision {value!r}"],
            failed_closed=True,
        )

    if isinstance(value, dict):
        raw = str(value.get("decision", "")).strip().lower()
        if raw in _VALID_DECISIONS:
            reasons = list(value.get("reasons") or []) or ["rego policy verdict"]
            return Verdict(
                decision=Decision(raw),
                intervention_point=point,
                reasons=reasons,
                rule_name=value.get("rule"),
            )
        return Verdict(
            decision=Decision.DENY,
            intervention_point=point,
            reasons=[f"rego verdict missing/invalid decision: {value!r}"],
            failed_closed=True,
        )

    # undefined / null / unexpected type
    return Verdict(
        decision=Decision.DENY,
        intervention_point=point,
        reasons=["rego query produced no decision"],
        failed_closed=True,
    )


class RegoBackend:
    """An ``AcsEvaluator`` policy backend that evaluates Rego via OPA."""

    def __init__(self, opa_path: str = "opa", *, timeout: float = 10.0) -> None:
        self.opa_path = opa_path
        self.timeout = timeout

    @staticmethod
    def is_available(opa_path: str = "opa") -> bool:
        """True when the OPA binary is on PATH."""
        return shutil.which(opa_path) is not None

    async def __call__(self, policy: PolicyDecl, canonical: CanonicalInput) -> Verdict:
        point = canonical.intervention_point
        if not policy.query or not policy.bundle:
            return Verdict(
                decision=Decision.DENY,
                intervention_point=point,
                reasons=["rego policy missing bundle/query"],
                failed_closed=True,
            )

        input_doc = json.dumps(canonical.model_dump(mode="json")).encode("utf-8")
        cmd = [
            self.opa_path,
            "eval",
            "--format",
            "json",
            "--stdin-input",
            "--data",
            policy.bundle,
            policy.query,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(input=input_doc), timeout=self.timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"opa eval failed (exit {proc.returncode}): {err.decode()[:300]}")

        value = _extract_opa_value(out)
        return verdict_from_opa_value(value, point)


def _extract_opa_value(stdout: bytes) -> Optional[Any]:
    """Pull ``result[0].expressions[0].value`` from `opa eval --format json`."""
    try:
        data = json.loads(stdout)
        return data["result"][0]["expressions"][0]["value"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None


def register_rego_backend(evaluator, *, opa_path: str = "opa") -> "RegoBackend":
    """Register a Rego backend on ``evaluator`` and return it."""
    backend = RegoBackend(opa_path)
    evaluator.register_policy_backend(PolicyType.REGO, backend)
    return backend
