# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Integration test for realistic mode (per-process network).

In realistic mode each in-process Python agent gets its own uvicorn
server on its own port. This exercises a different code path from sim
mode (single uvicorn with path-prefix routing).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2a_testbed.core.types import (
    AgentDecl,
    NetworkMode,
    Scenario,
    Step,
)
from a2a_testbed.scenario import ScenarioRunner


REPO_ROOT = Path(__file__).resolve().parents[2]
THREE_PARTY = REPO_ROOT / "examples" / "agent-cards" / "three-party"


def _scenario() -> Scenario:
    return Scenario(
        name="realistic-mode-smoke",
        mode=NetworkMode.REALISTIC,
        agents=[
            AgentDecl(id="alice", card=str(THREE_PARTY / "alice.json")),
            AgentDecl(id="bob", card=str(THREE_PARTY / "carol.json")),
        ],
        flow=[
            Step.model_validate(
                {
                    "from": "bob",
                    "to": "alice",
                    "action": "ping",
                    "message": "ping: please respond",
                    "expect": {"response_status": "2xx"},
                }
            ),
            Step.model_validate(
                {
                    "from": "alice",
                    "to": "bob",
                    "action": "pong",
                    "message": "pong: ack",
                    "expect": {"response_status": "2xx"},
                }
            ),
        ],
    )


@pytest.mark.asyncio
async def test_realistic_mode_runs_two_agents():
    runner = ScenarioRunner(log_level="error")
    result = await runner.run(_scenario())
    assert result.scenario_name == "realistic-mode-smoke"
    assert result.mode == NetworkMode.REALISTIC
    assert len(result.steps) == 2
    assert result.passed, [f"step {s.step_index}: {s.detail}" for s in result.steps if not s.passed]


@pytest.mark.asyncio
async def test_realistic_mode_assigns_distinct_ports():
    """In realistic mode, each agent gets its own bound port."""
    from a2a_testbed.core.loader import load_agent_card_from_path
    from a2a_testbed.network.perprocess import PerProcessNetwork
    from a2a_testbed.runtimes import PythonInProcRuntime

    a_card = load_agent_card_from_path(THREE_PARTY / "alice.json")
    b_card = load_agent_card_from_path(THREE_PARTY / "carol.json")
    a_decl = AgentDecl(id="a", card=str(THREE_PARTY / "alice.json"))
    b_decl = AgentDecl(id="b", card=str(THREE_PARTY / "carol.json"))

    a_rt = PythonInProcRuntime("a", a_card, scripts={})
    b_rt = PythonInProcRuntime("b", b_card, scripts={})

    net = PerProcessNetwork(log_level="error")
    net.register(a_decl, a_rt)
    net.register(b_decl, b_rt)

    async with net:
        urls = net.urls()
        assert "a" in urls and "b" in urls
        assert urls["a"] != urls["b"], "each agent should have a distinct URL"
        # Each URL should look like http://127.0.0.1:<port>
        for url in urls.values():
            assert url.startswith("http://127.0.0.1:")
