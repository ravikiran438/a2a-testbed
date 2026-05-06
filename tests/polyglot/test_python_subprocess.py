# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Polyglot smoke test: spawn the python subprocess agent template
and exchange one message with it through the testbed orchestrator.

This validates the SubprocessRuntime base + Python subprocess adapter
+ the agent-template ready handshake. It does NOT use sim mode (sim
mode is in-process only); it goes through realistic mode so the
subprocess agent stands up its own HTTP server.
"""

from __future__ import annotations

import shutil
import sys
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
PYTHON_TEMPLATE = REPO_ROOT / "agents" / "python-template"


pytestmark = pytest.mark.polyglot


def _scenario() -> Scenario:
    return Scenario(
        name="python-subprocess-smoke",
        mode=NetworkMode.REALISTIC,
        agents=[
            # Driver: in-process, talks to the subprocess agent via realistic
            AgentDecl(id="driver", card=str(THREE_PARTY / "carol.json")),
            AgentDecl(
                id="echo",
                card=str(THREE_PARTY / "alice.json"),
                runtime=RuntimeKind.PYTHON_SUBPROC,
                source=str(PYTHON_TEMPLATE),
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
async def test_python_subprocess_agent_round_trip():
    if shutil.which(sys.executable) is None:
        pytest.skip("python interpreter not on PATH (?)")
    runner = ScenarioRunner(log_level="error")
    result = await runner.run(_scenario())
    assert len(result.steps) == 1
    assert result.passed, [s.detail for s in result.steps if not s.passed]
    # The Python subprocess agent prepends "[Alice] " before its
    # script-matched response; check the body excerpt.
    step = result.steps[0]
    assert step.response_status == 200
    assert "Alice" in (step.response_body_excerpt or "")
