# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Agent Control Specification (ACS) types — manifest model + verdicts.

ACS is an open, vendor-neutral standard for placing deterministic
runtime controls at fixed checkpoints in an agent's lifecycle. See:

  Spec:    Agent Control Specification 0.3.1-beta
  Source:  https://github.com/microsoft/agent-governance-toolkit
  Blog:    https://commandline.microsoft.com/agent-control-specification-runtime-governance/

This module is the YAML/JSON-facing surface for an ACS *manifest*: the
portable artifact that declares *where* (intervention points), *when*,
and *how* (policies) controls are evaluated and enforced. It is the ACS
analog of the testbed's ``manifest/`` extension-manifest convention.

Design notes specific to a2a-testbed
------------------------------------
The testbed operates at the A2A *inter-agent* wire seam, not inside any
single agent's model loop. So of ACS's eight intervention points, the
ones the testbed can observe and enforce directly are ``input``,
``output``, ``pre_tool_call`` and ``post_tool_call`` (an A2A handoff is
shaped as a "tool call" against the remote agent), plus the
session-boundary points ``agent_startup`` and ``agent_shutdown``. The
two model-call points live inside an agent's process and are out of
scope unless an agent opts to emit them. This boundary is honest and
intentional — see ``acs/canonical.py``.

Nothing here branches on the A2A protocol version: ACS rides on top of
whatever transport produced the wire exchange (A2A 1.0 by default, but
0.3 or a non-A2A transport evaluate identically).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# The ACS spec revision this manifest model tracks. Pinned the same way
# the A2A spec commit is pinned in pyproject.toml — bump deliberately.
ACS_SPEC_VERSION = "0.3.1-beta"


class InterventionPoint(str, Enum):
    """The eight ACS lifecycle checkpoints.

    ``observable_at_wire()`` marks the subset the testbed can shape from
    an inter-agent wire exchange without introspecting an agent's
    internal model loop.
    """

    AGENT_STARTUP = "agent_startup"
    INPUT = "input"
    PRE_MODEL_CALL = "pre_model_call"
    POST_MODEL_CALL = "post_model_call"
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    OUTPUT = "output"
    AGENT_SHUTDOWN = "agent_shutdown"

    @classmethod
    def observable_at_wire(cls) -> frozenset["InterventionPoint"]:
        """Points the testbed can evaluate from a WireExchange alone."""
        return frozenset(
            {
                cls.AGENT_STARTUP,
                cls.INPUT,
                cls.PRE_TOOL_CALL,
                cls.POST_TOOL_CALL,
                cls.OUTPUT,
                cls.AGENT_SHUTDOWN,
            }
        )


class Decision(str, Enum):
    """Normalized ACS verdict decisions, in increasing severity."""

    ALLOW = "allow"
    WARN = "warn"
    DENY = "deny"
    ESCALATE = "escalate"

    @property
    def blocks(self) -> bool:
        """Whether the host runtime must stop the action."""
        return self in (Decision.DENY, Decision.ESCALATE)


class PolicyType(str, Enum):
    """How a policy is evaluated.

    ``builtin`` is the testbed's dependency-free deterministic rule
    engine (structured conditions, see ``BuiltinRule``). ``rego``
    matches the ACS reference shape and is delegated to an external
    OPA / ``agent-control-specification`` SDK backend when one is
    registered; absent that backend it fails closed (see the evaluator).
    """

    BUILTIN = "builtin"
    REGO = "rego"


class BuiltinRule(BaseModel):
    """One structured, deterministic rule for the ``builtin`` engine.

    We use a structured condition rather than a string expression so
    evaluation needs no ``eval`` and no expression parser — it stays
    auditable and safe. ``field`` is a dotted path into the canonical
    policy input (e.g. ``tool.args.to``); the first matching rule wins.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1)
    field: str = Field(..., description="Dotted path into the canonical input.")
    op: str = Field(
        ...,
        description=(
            "One of: equals, not_equals, in, not_in, contains, "
            "not_contains, endswith, startswith, exists, absent."
        ),
    )
    value: Any = None
    decision: Decision = Decision.DENY
    description: str = ""


class PolicyDecl(BaseModel):
    """A named policy referenced by one or more intervention points."""

    model_config = ConfigDict(str_strip_whitespace=True)

    type: PolicyType = PolicyType.BUILTIN
    # builtin
    rules: list[BuiltinRule] = Field(default_factory=list)
    default_decision: Decision = Decision.ALLOW
    # rego (reference-shape passthrough; consumed by an external backend)
    bundle: Optional[str] = None
    query: Optional[str] = None


class ToolDecl(BaseModel):
    """Tool metadata an intervention point can reason about."""

    model_config = ConfigDict(str_strip_whitespace=True)

    type: str = "Tool"
    id: str = Field(..., min_length=1)
    clearance: Optional[str] = None
    security_labels: list[str] = Field(default_factory=list)


class InterventionPointDecl(BaseModel):
    """Binds a policy (and optional evidence) to one lifecycle point."""

    model_config = ConfigDict(str_strip_whitespace=True)

    policy_target: str = Field(
        default="$",
        description="Path (``$.a.b``) selecting the value the policy judges.",
    )
    policy_target_kind: str = "snapshot"
    tool_name_from: Optional[str] = Field(
        default=None,
        description="Path to the tool name when this point involves a tool.",
    )
    policy_id: str = Field(..., min_length=1, alias="policy")
    # Ids of evidence providers to run before the policy (classifiers,
    # DLP, LLM judges). Resolved against the evaluator's registry.
    evidence: list[str] = Field(default_factory=list)


class AcsManifest(BaseModel):
    """A portable ACS control manifest.

    Mirrors the reference YAML shape::

        agent_control_specification_version: "0.3.1-beta"
        metadata:
          name: "email-agent"
        policies: { ... }
        intervention_points: { pre_tool_call: { ... } }
        tools: { send_email: { ... } }
    """

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    agent_control_specification_version: str = Field(default=ACS_SPEC_VERSION)
    metadata: dict[str, Any] = Field(default_factory=dict)
    policies: dict[str, PolicyDecl] = Field(default_factory=dict)
    intervention_points: dict[InterventionPoint, InterventionPointDecl] = Field(
        default_factory=dict
    )
    tools: dict[str, ToolDecl] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Evaluation surfaces
# ---------------------------------------------------------------------------


class CanonicalInput(BaseModel):
    """The standard policy input ACS shapes at each intervention point.

    Bridges the agent runtime and the policy engine. Shape matches the
    ACS reference contract: ``intervention_point``, ``policy_target``,
    ``snapshot``, ``annotations``, ``tool``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    intervention_point: InterventionPoint
    policy_target: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    tool: Optional[dict[str, Any]] = None


class Verdict(BaseModel):
    """A normalized ACS decision plus the rationale that produced it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Decision
    intervention_point: InterventionPoint
    policy_id: Optional[str] = None
    # Human-readable reasons + the rule/policy citation that justified
    # the verdict — the "show why the judge ruled" artifact, not just a
    # pass/fail flag.
    reasons: list[str] = Field(default_factory=list)
    rule_name: Optional[str] = None
    # True when the verdict is the result of fail-closed handling
    # (policy, evidence, or verdict processing errored) rather than a
    # clean policy evaluation.
    failed_closed: bool = False
