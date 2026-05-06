# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for core/types.py — scenario parsing and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from a2a_testbed.core.types import (
    AgentDecl,
    Fault,
    FaultKind,
    NetworkMode,
    ReportSink,
    RuntimeKind,
    Scenario,
    Step,
    StepKind,
)


def _step(**overrides):
    base = {"from": "a", "to": "b", "action": "ping"}
    base.update(overrides)
    return Step.model_validate(base)


def test_step_alias_and_defaults():
    s = _step()
    assert s.from_ == "a"
    assert s.to == "b"
    assert s.action == "ping"
    assert s.kind == StepKind.SEND


def test_advance_time_step():
    s = Step.model_validate(
        {"kind": "advance_time", "advance_seconds": 60}
    )
    assert s.kind == StepKind.ADVANCE_TIME
    assert s.advance_seconds == 60


def test_fault_drop():
    f = Fault(kind=FaultKind.DROP)
    assert f.kind == FaultKind.DROP
    assert f.delay_ms == 0


def test_fault_delay():
    f = Fault(kind=FaultKind.DELAY, delay_ms=500)
    assert f.delay_ms == 500


def test_scenario_defaults_to_sim_mode():
    sc = Scenario.model_validate(
        {
            "name": "x",
            "agents": [{"id": "a", "card": "a.json"}],
            "flow": [{"from": "a", "to": "b", "action": "p"}],
        }
    )
    assert sc.mode == NetworkMode.SIM


def test_agent_runtime_defaults_to_python_inproc():
    decl = AgentDecl(id="a", card="a.json")
    assert decl.runtime == RuntimeKind.PYTHON_INPROC


def test_agent_runtime_external_takes_url():
    decl = AgentDecl(id="ext", card="x.json", runtime="external", url="http://x:8000")
    assert decl.runtime == RuntimeKind.EXTERNAL


def test_report_sink_format_constrained():
    with pytest.raises(ValidationError):
        ReportSink(format="csv", path="x")
    ok = ReportSink(format="json", path="x.json")
    assert ok.format == "json"
