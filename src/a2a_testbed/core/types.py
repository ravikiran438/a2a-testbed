# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Pydantic types for scenarios, faults, observers, and reports.

These are the YAML/JSON-facing surfaces. The A2A `AgentCard` itself is a
protobuf object from `a2a-sdk` and is loaded by `core.loader`; everything
in this module is testbed-native vocabulary that sits above the wire.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NetworkMode(str, Enum):
    """Top-level network topology a scenario can request."""

    SIM = "sim"  # multi-tenant: one HTTP server, N agents on path prefixes
    REALISTIC = "realistic"  # per-agent: each agent runs in its own process+port


class RuntimeKind(str, Enum):
    """How an agent is materialized for the scenario."""

    PYTHON_INPROC = "python_inproc"  # in the orchestrator process (fastest)
    PYTHON_SUBPROC = "python_subproc"  # spawned `python -m ...` subprocess
    GO = "go"  # spawned `go run ./agents/go-template/`
    NODEJS = "nodejs"  # spawned `node ./agents/nodejs-template/`
    JAVA = "java"  # spawned `java -jar ...`
    EXTERNAL = "external"  # already running, just point at url


class FaultKind(str, Enum):
    """Failure injection kinds applied at message dispatch."""

    NONE = "none"
    DROP = "drop"  # response never returned (timeout)
    DELAY = "delay"  # response delayed by `delay_ms`
    CORRUPT = "corrupt"  # body mutated before delivery
    HTTP_ERROR = "http_error"  # synthetic 4xx/5xx response


class Fault(BaseModel):
    """Failure injection spec for a single step."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: FaultKind = FaultKind.NONE
    delay_ms: int = Field(default=0, ge=0)
    http_status: int = Field(default=500, ge=100, le=599)
    corrupt_pattern: Optional[str] = Field(
        default=None,
        description="Substring in response body to scramble (CORRUPT only).",
    )


class StepKind(str, Enum):
    SEND = "send"
    BROADCAST = "broadcast"
    OBSERVE = "observe"
    ADVANCE_TIME = "advance_time"


class ExtensionCheck(BaseModel):
    """One extension-semantics check for a step, run on the extension's
    MCP server (see ``extensions.mcp_delegation``)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tool: str = Field(..., min_length=1, description="MCP tool on the extension's server.")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments.")
    verdict: Literal["ok", "violation", "rejected"] = Field(
        default="ok",
        description=(
            "Expected answer: 'ok' ({\"ok\": true}), 'violation' ({\"ok\": false}), "
            "or 'rejected' (the server flagged the call as an error)."
        ),
    )


# Field names of the pre-0.3 schema, where four protocols were hardcoded
# and their expectations were recorded but never checked.
_LEGACY_EXTENSION_FIELDS = ("acap", "phala", "nerve", "pace")


class Expectation(BaseModel):
    """Per-step expected outcome."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    response_status: Optional[str] = Field(
        default=None,
        description="HTTP status keyword: '2xx', '4xx', '5xx', or exact integer string.",
    )
    response_contains: Optional[str] = None
    timeout_ms: Optional[int] = Field(default=None, ge=1)
    # Extension-semantics checks keyed by extension URI. Each is run on
    # the MCP server configured for that URI (scenario `mcp_delegates:`
    # or `--mcp-delegates`); the step fails unless every check returns
    # its expected verdict.
    extensions: Optional[
        Annotated[
            dict[
                str,
                Union[ExtensionCheck, Annotated[list[ExtensionCheck], Field(min_length=1)]],
            ],
            Field(min_length=1),
        ]
    ] = None

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            legacy = [k for k in _LEGACY_EXTENSION_FIELDS if k in data]
            if legacy:
                raise ValueError(
                    f"expect.{legacy[0]} is no longer supported: extension expectations "
                    "are keyed by extension URI and checked on that extension's MCP server. "
                    'Use expect.extensions: {"<extension URI>": {tool: ..., args: {...}, '
                    "verdict: ok|violation|rejected}} (see docs/scenarios.md)."
                )
        return data

    def extension_checks(self) -> list[tuple[str, ExtensionCheck]]:
        """Every (URI, check) pair, in declaration order."""
        out: list[tuple[str, ExtensionCheck]] = []
        for uri, checks in (self.extensions or {}).items():
            for check in checks if isinstance(checks, list) else [checks]:
                out.append((uri, check))
        return out


class Step(BaseModel):
    """One step in a scenario flow."""

    # forbid: a misspelt or mis-indented key (`expext:`, `extensions:`
    # beside `expect:`) must fail the load, not silently drop a check.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: StepKind = StepKind.SEND
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    action: Optional[str] = None
    message: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    fault: Optional[Fault] = None
    expect: Optional[Expectation] = None
    # ADVANCE_TIME-only fields
    advance_seconds: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _extension_checks_need_a_send(self) -> "Step":
        if self.expect and self.expect.extensions and self.kind != StepKind.SEND:
            raise ValueError(
                f"expect.extensions is only evaluated on send steps, not kind={self.kind.value}"
            )
        return self


class AgentDecl(BaseModel):
    """How a scenario declares an agent."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., min_length=1)
    card: str = Field(
        ...,
        description="Path to AgentCard JSON (relative to scenario file or absolute).",
    )
    runtime: RuntimeKind = RuntimeKind.PYTHON_INPROC
    role: Optional[str] = Field(
        default=None,
        description="Free-form role: principal, guardian, service_provider, observer.",
    )
    # External-runtime-only
    url: Optional[str] = Field(
        default=None,
        description="Required iff runtime=external; the already-running agent URL.",
    )
    # Subprocess-runtime: where to spawn from
    source: Optional[str] = Field(
        default=None,
        description="Path to subprocess source directory (go/nodejs/java/python_subproc).",
    )
    # In-process / subprocess: scripted responses for the executor
    scripts: Optional[dict[str, str]] = Field(
        default=None,
        description="action_label -> response_text. Falls back to scripts derived from flow.",
    )


class ReportSink(BaseModel):
    """Where to write a report and in what format."""

    model_config = ConfigDict(str_strip_whitespace=True)

    format: str = Field(..., pattern="^(json|markdown|svg-badge)$")
    path: str = Field(..., min_length=1)


class Scenario(BaseModel):
    """Top-level scenario document loaded from YAML."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    description: Optional[str] = None
    mode: NetworkMode = NetworkMode.SIM
    agents: list[AgentDecl] = Field(min_length=1)
    flow: list[Step] = Field(min_length=1)
    reports: list[ReportSink] = Field(default_factory=list)
    # Optional path to an Agent Control Specification (ACS) manifest,
    # relative to the scenario file. When present (or supplied via the
    # `--acs` CLI flag), the runner evaluates each step's wire exchange
    # against the manifest's intervention points and records verdicts.
    acs: Optional[str] = Field(
        default=None,
        description="Path to an ACS manifest YAML (relative to the scenario file).",
    )
    # When True, ACS verdicts are *enforced*: a deny/escalate blocks the
    # handoff and halts the flow. When False (default), verdicts are
    # recorded and surfaced but the flow proceeds. The `--acs-enforce`
    # CLI flag overrides this.
    acs_enforce: bool = False
    # MCP servers that check extension semantics (`expect.extensions`):
    # a path to a delegates file (relative to the scenario file) or an
    # inline list of delegate entries. `--mcp-delegates` entries override
    # these per URI. See examples/mcp-delegates.yaml.
    mcp_delegates: Optional[Union[str, list[dict[str, Any]], dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


class StepResult(BaseModel):
    """Recorded outcome of executing one step."""

    model_config = ConfigDict(str_strip_whitespace=True)

    step_index: int
    step: Step
    passed: bool
    detail: str = ""
    response_status: Optional[int] = None
    response_body_excerpt: Optional[str] = None
    elapsed_ms: float = 0.0
    # ACS verdicts recorded for this step's wire exchange, one per
    # evaluated intervention point. Stored as plain dicts (the
    # serialized form of ``a2a_testbed.acs.types.Verdict``) so the
    # ``core`` layer stays decoupled from the ``acs`` package. Empty
    # unless the scenario runs with an ACS manifest.
    acs_verdicts: list[dict[str, Any]] = Field(default_factory=list)
    # True when ACS enforce mode blocked this step (a deny/escalate
    # verdict halted the handoff). Always False in record-only mode.
    acs_blocked: bool = False


class ContractFinding(BaseModel):
    """One conformance contract's outcome against a scenario.

    Decoupled from ``contracts.base.ContractResult`` (a stdlib
    dataclass) so the runtime-result shape stays JSON-serializable
    via Pydantic without a custom encoder. The runner converts
    `ContractResult` -> `ContractFinding` after evaluation.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: str
    category: str  # transport / network / extension
    passed: bool
    detail: str = ""
    spec_section: Optional[str] = None
    # When the contract scoped to one agent (transport contracts
    # all do; network contracts don't), record which agent it
    # ran against. Empty string for cross-agent contracts.
    agent_id: str = ""


class ScenarioResult(BaseModel):
    """Aggregated result for a whole scenario run."""

    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_name: str
    mode: NetworkMode
    started_at: datetime
    finished_at: datetime
    elapsed_ms: float
    steps: list[StepResult]
    # Spec-derived contract evaluations executed alongside the
    # scenario, when the runner has access to in-process agents.
    # Empty list when contracts couldn't be evaluated (e.g. all
    # agents are external — we don't probe third-party deployments
    # without explicit opt-in).
    contracts: list[ContractFinding] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        steps_ok = all(s.passed for s in self.steps)
        contracts_ok = all(c.passed for c in self.contracts)
        return steps_ok and contracts_ok

    @property
    def pass_count(self) -> int:
        return sum(1 for s in self.steps if s.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for s in self.steps if not s.passed)

    @property
    def contracts_pass_count(self) -> int:
        return sum(1 for c in self.contracts if c.passed)

    @property
    def contracts_fail_count(self) -> int:
        return sum(1 for c in self.contracts if not c.passed)

    @property
    def acs_verdicts(self) -> list[dict[str, Any]]:
        """All ACS verdicts across every step, flattened."""
        out: list[dict[str, Any]] = []
        for s in self.steps:
            for v in s.acs_verdicts:
                out.append({"step_index": s.step_index, **v})
        return out

    @property
    def acs_blocked_count(self) -> int:
        """Verdicts that would block the action (deny or escalate)."""
        blocking = {"deny", "escalate"}
        return sum(1 for v in self.acs_verdicts if v.get("decision") in blocking)
