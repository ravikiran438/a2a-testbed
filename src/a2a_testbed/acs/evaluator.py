# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""ACS evaluator — turn a wire snapshot into a normalized verdict.

The evaluator owns the orchestration around policy evaluation that the
ACS spec describes: canonical-input shaping, evidence collection, policy
dispatch, verdict normalization, and — crucially for a *testbed* —
fail-closed handling. When evidence, the policy engine, or verdict
processing raises, the action is denied, never silently allowed.

Two policy backends:

- ``builtin`` : a dependency-free deterministic rule engine. Structured
  conditions, first-match-wins, default decision otherwise. Lets the
  testbed exercise ACS end-to-end with zero external services.
- ``rego``    : reference-shape passthrough. Delegated to an external
  OPA / ``agent-control-specification`` SDK backend registered via
  ``register_policy_backend``. If no backend is registered, evaluation
  fails closed (deny) rather than skipping — the safe default for a
  control layer.

Evidence providers are async callables keyed by id. A provider returns
a dict merged into ``annotations`` before the policy runs; raising
triggers fail-closed.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from a2a_testbed.acs.canonical import (
    _MISSING,
    build_canonical_input,
    resolve_path,
    snapshot_for,
)
from a2a_testbed.acs.types import (
    AcsManifest,
    BuiltinRule,
    CanonicalInput,
    Decision,
    InterventionPoint,
    PolicyDecl,
    PolicyType,
    Verdict,
)
from a2a_testbed.core.observer import WireExchange


# An evidence provider: (canonical_input_so_far) -> annotations dict.
EvidenceProvider = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
# A policy backend: (PolicyDecl, CanonicalInput) -> Verdict.
PolicyBackend = Callable[[PolicyDecl, CanonicalInput], Awaitable[Verdict]]


class AcsEvaluationError(Exception):
    """Raised internally when a stage fails; converted to a fail-closed deny."""


_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "equals": lambda a, b: a == b,
    "not_equals": lambda a, b: a != b,
    "in": lambda a, b: a in b if b is not None else False,
    "not_in": lambda a, b: a not in b if b is not None else True,
    "contains": lambda a, b: b in a if a is not None else False,
    "not_contains": lambda a, b: b not in a if a is not None else True,
    "endswith": lambda a, b: isinstance(a, str) and a.endswith(b),
    "startswith": lambda a, b: isinstance(a, str) and a.startswith(b),
    "exists": lambda a, _b: a is not _MISSING,
    "absent": lambda a, _b: a is _MISSING,
}


def _eval_rule(rule: BuiltinRule, canonical: CanonicalInput) -> bool:
    """True when ``rule`` matches the canonical input."""
    op = _OPS.get(rule.op)
    if op is None:
        raise AcsEvaluationError(f"unknown builtin op: {rule.op!r}")
    # Resolve the rule field against the full canonical input dict so a
    # rule can reference snapshot, tool, annotations, or policy_target.
    haystack = canonical.model_dump()
    actual = resolve_path(haystack, rule.field)
    # exists/absent inspect presence; other ops compare the resolved value.
    if rule.op in ("exists", "absent"):
        return op(actual, None)
    if actual is _MISSING:
        return False
    return op(actual, rule.value)


async def _builtin_backend(policy: PolicyDecl, canonical: CanonicalInput) -> Verdict:
    """First-match-wins deterministic rule engine."""
    for rule in policy.rules:
        if _eval_rule(rule, canonical):
            return Verdict(
                decision=rule.decision,
                intervention_point=canonical.intervention_point,
                reasons=[rule.description or f"matched rule {rule.name!r}"],
                rule_name=rule.name,
            )
    return Verdict(
        decision=policy.default_decision,
        intervention_point=canonical.intervention_point,
        reasons=["no rule matched; applied default decision"],
    )


class AcsEvaluator:
    """Stateless-per-call ACS intervention-point evaluator.

    ``fail_closed`` (default True) is the whole point of running ACS
    through a testbed: when a stage errors, deny. Set False only to
    study fail-open behavior in a controlled experiment.
    """

    def __init__(self, *, fail_closed: bool = True) -> None:
        self._fail_closed = fail_closed
        self._evidence: dict[str, EvidenceProvider] = {}
        self._backends: dict[PolicyType, PolicyBackend] = {
            PolicyType.BUILTIN: _builtin_backend,
        }

    # -- registries --------------------------------------------------

    def register_evidence(self, provider_id: str, provider: EvidenceProvider) -> None:
        self._evidence[provider_id] = provider

    def register_policy_backend(self, policy_type: PolicyType, backend: PolicyBackend) -> None:
        """Plug in an external engine (e.g. OPA/Rego or the ACS SDK)."""
        self._backends[policy_type] = backend

    # -- evaluation --------------------------------------------------

    def _deny_closed(self, point: InterventionPoint, reason: str) -> Verdict:
        return Verdict(
            decision=Decision.DENY,
            intervention_point=point,
            reasons=[f"fail-closed: {reason}"],
            failed_closed=True,
        )

    async def evaluate(
        self, manifest: AcsManifest, point: InterventionPoint, snapshot: dict[str, Any]
    ) -> Verdict:
        """Evaluate one intervention point against a host snapshot."""
        decl = manifest.intervention_points.get(point)
        if decl is None:
            # No control configured here: allow (nothing to enforce).
            return Verdict(
                decision=Decision.ALLOW,
                intervention_point=point,
                reasons=["no intervention point configured"],
            )

        policy = manifest.policies.get(decl.policy_id)
        if policy is None:
            return self._deny_closed(point, f"policy id {decl.policy_id!r} not found in manifest")

        # Build the canonical input first so evidence providers can read it.
        canonical = build_canonical_input(
            point,
            snapshot,
            policy_target_path=decl.policy_target,
            policy_target_kind=decl.policy_target_kind,
            tool_name_from=decl.tool_name_from,
            tools=manifest.tools,
        )

        # Evidence collection — any failure denies (fail-closed).
        annotations: dict[str, Any] = {}
        for ev_id in decl.evidence:
            provider = self._evidence.get(ev_id)
            if provider is None:
                if self._fail_closed:
                    return self._deny_closed(point, f"evidence provider {ev_id!r} missing")
                continue
            try:
                annotations.update(await provider(canonical.model_dump()))
            except Exception as exc:  # noqa: BLE001 — fail-closed boundary
                if self._fail_closed:
                    return self._deny_closed(point, f"evidence {ev_id!r} raised: {exc}")
        canonical.annotations = annotations

        # Policy dispatch — any failure denies (fail-closed).
        backend = self._backends.get(policy.type)
        if backend is None:
            return self._deny_closed(
                point, f"no backend registered for policy type {policy.type.value!r}"
            )
        try:
            verdict = await backend(policy, canonical)
        except Exception as exc:  # noqa: BLE001 — fail-closed boundary
            if self._fail_closed:
                return self._deny_closed(point, f"policy backend raised: {exc}")
            raise

        verdict.policy_id = decl.policy_id
        return verdict

    async def evaluate_exchange(
        self, manifest: AcsManifest, point: InterventionPoint, exchange: WireExchange
    ) -> Verdict:
        """Convenience: shape a WireExchange then evaluate ``point``."""
        snapshot = snapshot_for(point, exchange, tools=manifest.tools)
        return await self.evaluate(manifest, point, snapshot)
