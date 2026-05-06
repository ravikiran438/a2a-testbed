# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Scenario runner: orchestrates multi-tenant (sim) or per-process
(realistic) networks through a sequence of scripted protocol interactions.

The runner is wire-format-agnostic: it talks to agents only through the
active ``Transport``, never through A2A primitives directly. This is
the SOW §12.1 hedge against A2A protocol fade.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import httpx
import yaml

from a2a_testbed.core.faults import DroppedRequest, apply_fault
from a2a_testbed.core.loader import load_agent_card_from_path
from a2a_testbed.core.observer import ObserverHub, WireExchange
from a2a_testbed.core.time_controller import TimeController
from a2a_testbed.core.types import (
    AgentDecl,
    ContractFinding,
    Expectation,
    NetworkMode,
    RuntimeKind,
    Scenario,
    ScenarioResult,
    Step,
    StepKind,
    StepResult,
)
from a2a_testbed.network.multitenant import MultiTenantNetwork
from a2a_testbed.runtimes import (
    ExternalRuntime,
    GoRuntime,
    JavaRuntime,
    NodejsRuntime,
    PythonInProcRuntime,
    PythonSubprocRuntime,
    RuntimeUnavailable,
)
from a2a_testbed.transport import A2ATransport, Transport, WireMessage


logger = logging.getLogger(__name__)


class ScenarioLoadError(ValueError):
    """Raised when a scenario YAML cannot be parsed or validated."""


def load_scenario(path: Union[str, Path]) -> Scenario:
    p = Path(path)
    if not p.exists():
        raise ScenarioLoadError(f"Scenario file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioLoadError(f"invalid YAML in {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ScenarioLoadError(f"scenario root must be a mapping in {p}")
    try:
        return Scenario.model_validate(raw)
    except Exception as exc:
        raise ScenarioLoadError(f"scenario schema mismatch in {p}: {exc}") from exc


def scripts_from_steps(steps: Iterable[Step]) -> dict[str, dict[str, str]]:
    """Build per-receiver scripts from scenario flow."""
    out: dict[str, dict[str, str]] = {}
    for step in steps:
        if step.to in (None, "*"):
            continue
        if not step.action:
            continue
        bucket = out.setdefault(step.to, {})
        bucket.setdefault(
            step.action, f"[{step.to}] handled action: {step.action}"
        )
    return out


# ---------------------------------------------------------------------------
# Runtime construction
# ---------------------------------------------------------------------------


def _build_runtime(
    decl: AgentDecl,
    *,
    scenario_dir: Path,
    inferred_scripts: dict[str, str],
):
    if not Path(decl.card).is_absolute():
        card_path = (scenario_dir / decl.card).resolve()
    else:
        card_path = Path(decl.card)
    card = load_agent_card_from_path(card_path)

    scripts = dict(inferred_scripts)
    if decl.scripts:
        scripts.update(decl.scripts)

    if decl.runtime == RuntimeKind.PYTHON_INPROC:
        return PythonInProcRuntime(decl.id, card, scripts=scripts)
    if decl.runtime == RuntimeKind.EXTERNAL:
        if not decl.url:
            raise ValueError(f"agent {decl.id!r}: runtime=external requires url")
        return ExternalRuntime(decl.id, card, url=decl.url)
    # subprocess flavors
    source = decl.source or ""
    if not source:
        raise ValueError(f"agent {decl.id!r}: runtime={decl.runtime.value} requires source")
    if decl.runtime == RuntimeKind.PYTHON_SUBPROC:
        return PythonSubprocRuntime(decl.id, card, source=source, scripts=scripts)
    if decl.runtime == RuntimeKind.GO:
        return GoRuntime(decl.id, card, source=source, scripts=scripts)
    if decl.runtime == RuntimeKind.NODEJS:
        return NodejsRuntime(decl.id, card, source=source, scripts=scripts)
    if decl.runtime == RuntimeKind.JAVA:
        return JavaRuntime(decl.id, card, source=source, scripts=scripts)
    raise ValueError(f"unhandled runtime kind: {decl.runtime}")


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------


class ScenarioRunner:
    def __init__(
        self,
        *,
        http_timeout: float = 10.0,
        log_level: str = "warning",
        transport: Optional[Transport] = None,
        probe_external: bool = False,
    ) -> None:
        self._timeout = http_timeout
        self._log_level = log_level
        self._transport: Transport = transport or A2ATransport()
        # When True, the contract evaluator runs the transport
        # contract suite against agents declared `runtime: external`
        # too — opt-in because their CORS allowlist / rate limit /
        # TOS are out of our hands and we'd be impolite to spray a
        # 23-probe sweep at them on every scenario run.
        self._probe_external = probe_external

    async def run_file(self, scenario_path: Union[str, Path]) -> ScenarioResult:
        scenario = load_scenario(scenario_path)
        scenario_dir = Path(scenario_path).resolve().parent
        return await self.run(scenario, scenario_dir=scenario_dir)

    async def run(
        self,
        scenario: Scenario,
        *,
        scenario_dir: Optional[Path] = None,
    ) -> ScenarioResult:
        scenario_dir = scenario_dir or Path.cwd()
        if scenario.mode == NetworkMode.SIM:
            return await self._run_sim(scenario, scenario_dir)
        if scenario.mode == NetworkMode.REALISTIC:
            return await self._run_realistic(scenario, scenario_dir)
        raise NotImplementedError(f"unknown network mode {scenario.mode!r}")

    async def _run_sim(self, scenario: Scenario, scenario_dir: Path) -> ScenarioResult:
        inferred = scripts_from_steps(scenario.flow)
        time_ctrl = TimeController()
        observer_hub = ObserverHub()

        # Construct runtimes
        runtimes = []
        in_proc_runtimes: list[PythonInProcRuntime] = []
        for decl in scenario.agents:
            runtime = _build_runtime(
                decl,
                scenario_dir=scenario_dir,
                inferred_scripts=inferred.get(decl.id, {}),
            )
            runtimes.append((decl, runtime))
            if decl.role == "observer":
                observer_hub.register(decl.id)
            if isinstance(runtime, PythonInProcRuntime):
                in_proc_runtimes.append(runtime)

        # Sim mode requires every agent be in-process. Subprocess and
        # external runtimes go through realistic mode.
        for decl, runtime in runtimes:
            if not isinstance(runtime, PythonInProcRuntime):
                raise ValueError(
                    f"agent {decl.id!r}: sim mode requires runtime=python_inproc; "
                    f"use mode: realistic for {decl.runtime.value} agents"
                )

        net = MultiTenantNetwork(log_level=self._log_level, transport=self._transport)
        for r in in_proc_runtimes:
            net.register(r)

        # Wire observer agents to the network's traffic taps so they
        # see every request/response that flows through the wire.
        if observer_hub.observers():
            net.attach_traffic_tap(self._make_observer_tap(observer_hub))

        async with net:
            agent_url: dict[str, str] = {
                decl.id: net.url_of(decl.id) for decl, _ in runtimes
            }
            scenario_result = await self._drive_flow(
                scenario, agent_url, time_ctrl, observer_hub
            )
            scenario_result.contracts = await self._evaluate_contracts(
                scenario, agent_url, scenario_result, observer_hub,
            )
            return scenario_result

    async def _run_realistic(
        self, scenario: Scenario, scenario_dir: Path
    ) -> ScenarioResult:
        """Per-process realistic mode: each agent gets its own HTTP server.

        Used for cross-SDK conformance and production-topology validation.
        Mixes runtime kinds within one scenario.
        """
        from a2a_testbed.network.perprocess import PerProcessNetwork

        inferred = scripts_from_steps(scenario.flow)
        time_ctrl = TimeController()
        observer_hub = ObserverHub()

        runtimes = []
        for decl in scenario.agents:
            runtime = _build_runtime(
                decl,
                scenario_dir=scenario_dir,
                inferred_scripts=inferred.get(decl.id, {}),
            )
            runtimes.append((decl, runtime))
            if decl.role == "observer":
                observer_hub.register(decl.id)

        net = PerProcessNetwork(transport=self._transport)
        for decl, runtime in runtimes:
            net.register(decl, runtime)

        async with net:
            agent_url = net.urls()
            scenario_result = await self._drive_flow(
                scenario, agent_url, time_ctrl, observer_hub
            )
            # Build a per-agent runtime-kind map so the contract
            # evaluator can skip external agents (we don't probe
            # third-party deployments without explicit opt-in).
            runtime_by_id = {
                decl.id: decl.runtime for decl, _ in runtimes
            }
            scenario_result.contracts = await self._evaluate_contracts(
                scenario,
                agent_url,
                scenario_result,
                observer_hub,
                runtime_by_id=runtime_by_id,
            )
            return scenario_result

    async def _drive_flow(
        self,
        scenario: Scenario,
        agent_url: dict[str, str],
        time_ctrl: TimeController,
        observer_hub: ObserverHub,
    ) -> ScenarioResult:
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        results: list[StepResult] = []

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for index, step in enumerate(scenario.flow):
                result = await self._run_step(
                    client, agent_url, time_ctrl, observer_hub, index, step,
                )
                observer_hub.record(index, step, result)
                results.append(result)

        finished_at = datetime.now(timezone.utc)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return ScenarioResult(
            scenario_name=scenario.name,
            mode=scenario.mode,
            started_at=started_at,
            finished_at=finished_at,
            elapsed_ms=elapsed_ms,
            steps=results,
        )

    async def _evaluate_contracts(
        self,
        scenario: Scenario,
        agent_url: dict[str, str],
        scenario_result: ScenarioResult,
        observer_hub: ObserverHub,
        *,
        runtime_by_id: Optional[dict[str, RuntimeKind]] = None,
    ) -> list[ContractFinding]:
        """Run the spec-derived contract suite against the live network.

        Sim mode runs all transport contracts (every agent is
        in-process and already up). Realistic mode skips agents
        whose runtime is ``external`` — we don't conformance-test
        third-party deployments without explicit opt-in. Network
        contracts always run; they evaluate the scenario_result +
        observer_hub, not live agents.
        """
        # Local import keeps the contract subsystem optional —
        # tests / minimal embeddings that don't want it can stub
        # this method without pulling in the runner dependency tree.
        from a2a_testbed.contracts.runner import (
            run_network_contracts,
            run_transport_contracts,
        )

        runtime_by_id = runtime_by_id or {}
        findings: list[ContractFinding] = []

        # Transport contracts — per agent.
        for agent_id, url in agent_url.items():
            if (
                runtime_by_id.get(agent_id) == RuntimeKind.EXTERNAL
                and not self._probe_external
            ):
                # Skip third-party deployments by default; their CORS
                # allowlist / rate limit / TOS are out of our hands.
                # Pass --probe-external on `run` (or use the
                # `conformance` CLI command) to opt in.
                continue
            try:
                results = await run_transport_contracts(self._transport, url)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "transport-contract evaluation failed for agent %r: %s",
                    agent_id,
                    exc,
                )
                continue
            for r in results:
                findings.append(
                    ContractFinding(
                        contract_id=r.contract_id,
                        category=r.category.value if r.category else "transport",
                        passed=r.passed,
                        detail=r.detail,
                        spec_section=r.spec_section,
                        agent_id=agent_id,
                    )
                )

        # Network contracts — multi-agent flow invariants. Always run.
        try:
            net_results = await run_network_contracts(
                scenario, scenario_result, observer_hub,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("network-contract evaluation failed: %s", exc)
            net_results = []
        for r in net_results:
            findings.append(
                ContractFinding(
                    contract_id=r.contract_id,
                    category=r.category.value if r.category else "network",
                    passed=r.passed,
                    detail=r.detail,
                    spec_section=r.spec_section,
                    agent_id="",
                )
            )

        return findings

    @staticmethod
    def _make_observer_tap(observer_hub: ObserverHub):
        """Build a network traffic tap that funnels into the observer hub."""
        def tap(receiver_id: str, request_body: dict, response_body: dict) -> None:
            observer_hub.record_wire(
                WireExchange(
                    receiver_id=receiver_id,
                    request_body=request_body,
                    response_body=response_body,
                )
            )
        return tap

    async def _run_step(
        self,
        client: httpx.AsyncClient,
        agent_url: dict[str, str],
        time_ctrl: TimeController,
        observer_hub: ObserverHub,
        index: int,
        step: Step,
    ) -> StepResult:
        if step.kind == StepKind.ADVANCE_TIME:
            seconds = step.advance_seconds or 0
            time_ctrl.advance(seconds)
            return StepResult(
                step_index=index,
                step=step,
                passed=True,
                detail=f"advanced virtual clock by {seconds}s; now={time_ctrl.now().isoformat()}",
            )

        if step.kind == StepKind.OBSERVE:
            observer_id = step.from_ or ""
            history = observer_hub.history(observer_id)
            return StepResult(
                step_index=index,
                step=step,
                passed=True,
                detail=f"observer {observer_id!r} has seen {len(history)} prior records",
            )

        if step.kind == StepKind.BROADCAST:
            return StepResult(
                step_index=index,
                step=step,
                passed=False,
                detail="broadcast-kind steps are not yet supported",
            )

        # SEND
        if not step.to:
            return StepResult(
                step_index=index, step=step, passed=False,
                detail="step kind=send requires `to`",
            )
        if step.to not in agent_url:
            return StepResult(
                step_index=index, step=step, passed=False,
                detail=f"unknown receiver agent {step.to!r}",
            )

        url = agent_url[step.to].rstrip("/") + self._transport.rpc_endpoint_path()
        wire = WireMessage(
            sender_id=step.from_ or "",
            receiver_id=step.to,
            action_label=step.action or "",
            text=step.message or step.action or "",
            metadata={
                "request_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
            },
        )
        payload = self._transport.encode_request(wire)
        t0 = time.perf_counter()
        try:
            response = await apply_fault(step.fault, "POST", url, payload, client)
        except DroppedRequest:
            return StepResult(
                step_index=index, step=step, passed=False,
                detail="fault: drop (no response)",
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )
        except httpx.HTTPError as exc:
            return StepResult(
                step_index=index, step=step, passed=False,
                detail=f"HTTP error: {exc}",
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        body_excerpt = self._excerpt(response.text)
        passed, detail = self._evaluate(step.expect, response, body_excerpt)
        return StepResult(
            step_index=index,
            step=step,
            passed=passed,
            detail=detail,
            response_status=response.status_code,
            response_body_excerpt=body_excerpt,
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def _build_send_message_request_LEGACY(step: Step) -> dict:
        """Deprecated: kept only as a reference; the live path uses
        ``self._transport.encode_request`` instead."""
        message_text = step.message or step.action or ""
        return {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": [{"kind": "text", "text": message_text}],
                },
                "configuration": {"blocking": True},
            },
        }

    @staticmethod
    def _excerpt(text: str, *, limit: int = 1024) -> str:
        return text if len(text) <= limit else text[:limit] + "...(truncated)"

    @staticmethod
    def _evaluate(
        expect: Optional[Expectation],
        response: httpx.Response,
        body: str,
    ) -> tuple[bool, str]:
        if expect is None:
            ok = 200 <= response.status_code < 300
            return ok, f"status {response.status_code}"

        if expect.response_status:
            kw = expect.response_status.strip()
            status = response.status_code
            if kw == "2xx" and not (200 <= status < 300):
                return False, f"expected 2xx, got {status}"
            if kw == "4xx" and not (400 <= status < 500):
                return False, f"expected 4xx, got {status}"
            if kw == "5xx" and not (500 <= status < 600):
                return False, f"expected 5xx, got {status}"
            if kw.isdigit() and status != int(kw):
                return False, f"expected exact status {kw}, got {status}"

        if expect.response_contains and expect.response_contains not in body:
            return False, f"response did not contain {expect.response_contains!r}"

        recorded: list[str] = []
        for label in ("acap", "phala", "nerve", "pace"):
            spec = getattr(expect, label, None)
            if spec:
                recorded.append(f"{label}={json.dumps(spec, sort_keys=True)}")
        if recorded:
            return True, "passed; extension expectations recorded: " + ", ".join(recorded)
        return True, "passed"


async def run_scenario_file(
    path: Union[str, Path],
    *,
    log_level: str = "warning",
    probe_external: bool = False,
) -> ScenarioResult:
    runner = ScenarioRunner(log_level=log_level, probe_external=probe_external)
    return await runner.run_file(path)
