# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Polyglot smoke test: spawn the Node.js subprocess agent and exchange one
message with it through the testbed orchestrator.

Gated on a Node runtime (`node`) being on PATH. The template is
interpreted, so there is nothing to build first (unlike the Java jar).
Mirrors test_python_subprocess.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from a2a_testbed.core.types import (
    AgentDecl,
    NetworkMode,
    RuntimeKind,
    Scenario,
    Step,
)
from a2a_testbed.scenario import ScenarioRunner


REPO_ROOT = Path(__file__).resolve().parents[2]
THREE_PARTY = REPO_ROOT / "examples" / "agent-cards" / "three-party"
NODEJS_TEMPLATE = REPO_ROOT / "agents" / "nodejs-template"


pytestmark = pytest.mark.polyglot


def _scenario() -> Scenario:
    return Scenario(
        name="nodejs-subprocess-smoke",
        mode=NetworkMode.REALISTIC,
        agents=[
            AgentDecl(id="driver", card=str(THREE_PARTY / "carol.json")),
            AgentDecl(
                id="echo",
                card=str(THREE_PARTY / "alice.json"),
                runtime=RuntimeKind.NODEJS,
                source=str(NODEJS_TEMPLATE),
            ),
        ],
        flow=[
            Step.model_validate(
                {
                    "from": "driver",
                    "to": "echo",
                    "action": "ping",
                    "message": "ping: from-driver",
                    "expect": {"response_status": "2xx"},
                }
            ),
        ],
    )


@pytest.mark.asyncio
async def test_nodejs_subprocess_agent_round_trip():
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    runner = ScenarioRunner(log_level="error")
    result = await runner.run(_scenario())
    assert len(result.steps) == 1
    # Round-trip smoke test (not a conformance gate): assert the message
    # exchange succeeded. The minimal template isn't a full-conformance
    # target; the contract suite is exercised against the reference agents.
    assert all(s.passed for s in result.steps), [s.detail for s in result.steps if not s.passed]
    step = result.steps[0]
    assert step.response_status == 200
    # The agent prepends "[Alice] " (the AgentCard name) to its response.
    assert "Alice" in (step.response_body_excerpt or "")
