# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""A2A 1.0 conformance + 0.3 backward compatibility, end to end.

The contract suite is validated against agents built on the official
a2a-sdk (``tests/oracles/sdk_agents.py``): a pure 1.0 agent and a 0.3
agent must pass every contract (skips only where a rule does not apply),
and an agent whose card advertises 1.0 while serving only 0.3 method
names — the drift reported in a2aproject/A2A#1826 — must be flagged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a_testbed.contracts.runner import run_transport_contracts
from a2a_testbed.scenario import run_scenario_file
from a2a_testbed.transport import A2ATransport
from tests.oracles.sdk_agents import build_push_receiver, build_sdk_agent, serve

REPO_ROOT = Path(__file__).resolve().parents[2]
MIXED_SCENARIO = REPO_ROOT / "examples" / "scenarios" / "mixed_versions.yaml"


async def _sweep(agent_url: str, transport: A2ATransport | None = None):
    results = await run_transport_contracts(transport or A2ATransport(), agent_url)
    return {r.contract_id: r for r in results}


@pytest.fixture
async def push_receiver(monkeypatch):
    async with serve(lambda _base: build_push_receiver()) as url:
        monkeypatch.setenv("A2A_TESTBED_PUSH_RECEIVER", url)
        yield url


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol_version", ["1.0", "0.3", "dual"])
async def test_official_sdk_agent_passes_every_contract(push_receiver, protocol_version):
    async with serve(lambda base: build_sdk_agent(base, protocol_version)) as url:
        results = await _sweep(url)
    failed = {cid: r.detail for cid, r in results.items() if not r.passed}
    assert not failed, failed
    # The positive-path contracts really ran (not skipped) — the oracle
    # produces Tasks, streams and webhooks.
    for cid in (
        "transport.tasks_get_returns_task",
        "transport.tasks_cancel_sets_canceled",
        "transport.streaming_first_event_is_task",
        "transport.streaming_terminal_state_closes",
        "transport.subscribe_replays_state",
        "transport.push_list_returns_all",
        "transport.push_fires_on_completion",
    ):
        assert "skip" not in (results[cid].detail or "").lower(), (cid, results[cid].detail)
    advertised = results["transport.advertised_version_served"].detail
    expected = "1.0" if protocol_version == "dual" else protocol_version
    assert f"A2A {expected}" in advertised


@pytest.mark.asyncio
async def test_v03_agent_skips_only_rules_that_postdate_it(push_receiver):
    async with serve(lambda base: build_sdk_agent(base, "0.3")) as url:
        results = await _sweep(url)
    skipped = {cid for cid, r in results.items() if "skip" in (r.detail or "").lower()}
    assert {
        "transport.version_not_supported",
        "transport.agent_card_protocol_version_format",
        "transport.tasks_list_sorted_desc",
    } <= skipped


def _drift_agent(base_url: str) -> Starlette:
    """Card advertises JSONRPC 1.0; the endpoint only knows 0.3 names."""

    async def card(_r: Request) -> JSONResponse:
        return JSONResponse(
            {
                "name": "Drifted",
                "description": "advertises 1.0, serves 0.3",
                "version": "1.0.0",
                "supportedInterfaces": [
                    {"url": base_url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
                ],
                "capabilities": {},
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text"],
                "skills": [{"id": "s", "name": "s", "description": "s", "tags": ["s"]}],
            }
        )

    async def rpc(request: Request) -> JSONResponse:
        body = await request.json()
        if body.get("method") != "message/send":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": -32601, "message": "nope"},
                }
            )
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "kind": "message",
                    "messageId": "r",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "ok"}],
                },
            }
        )

    return Starlette(
        routes=[
            Route("/.well-known/agent-card.json", card, methods=["GET"]),
            Route("/a2a/v1/", rpc, methods=["POST"]),
        ]
    )


@pytest.mark.asyncio
async def test_card_version_drift_is_flagged():
    async with serve(_drift_agent) as url:
        results = await _sweep(url)
    drift = results["transport.advertised_version_served"]
    assert not drift.passed
    assert "message/send" in drift.detail and "1.0" in drift.detail


@pytest.mark.asyncio
async def test_pinned_v03_sweep_of_a_dual_version_agent(push_receiver):
    """``--protocol-version 0.3`` exercises the legacy surface of an agent
    whose card prefers 1.0 (the SDK's own dual-version setup)."""
    async with serve(lambda base: build_sdk_agent(base, "dual")) as url:
        results = await _sweep(url, A2ATransport(protocol_version="0.3"))
    assert all(r.passed for r in results.values()), {
        cid: r.detail for cid, r in results.items() if not r.passed
    }


@pytest.mark.asyncio
async def test_mixed_version_scenario_speaks_each_receivers_version():
    result = await run_scenario_file(MIXED_SCENARIO, log_level="error")
    assert result.passed, [s.detail for s in result.steps if not s.passed]
    failed = [c for c in result.contracts if not c.passed]
    assert not failed, [(c.agent_id, c.contract_id, c.detail) for c in failed]
    assert all("fell back" not in s.detail for s in result.steps)


@pytest.mark.asyncio
async def test_scenario_falls_back_when_a_card_overstates_its_version(tmp_path):
    """Scenario runs still deliver to a drifted agent, and say so."""
    async with serve(_drift_agent) as url:
        card = tmp_path / "drift.json"
        card.write_text(
            '{"name": "Drifted", "description": "d", "version": "1",'
            f' "supportedInterfaces": [{{"url": "{url}", "protocolBinding": "JSONRPC",'
            ' "protocolVersion": "1.0"}], "capabilities": {}, "skills": [],'
            ' "defaultInputModes": ["text"], "defaultOutputModes": ["text"]}'
        )
        prober = tmp_path / "prober.json"
        prober.write_text(card.read_text().replace("Drifted", "Prober"))
        scenario = tmp_path / "s.yaml"
        scenario.write_text(
            "name: drift\nmode: realistic\nagents:\n"
            "  - id: prober\n    card: prober.json\n    runtime: python_inproc\n"
            f"  - id: drift\n    card: drift.json\n    runtime: external\n    url: {url}\n"
            "flow:\n  - from: prober\n    to: drift\n    action: ping\n    message: hi\n"
        )
        result = await run_scenario_file(scenario, log_level="error")
    step = result.steps[0]
    assert step.passed, step.detail
    assert "fell back" in step.detail
