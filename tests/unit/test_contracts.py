# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Smoke tests for the conformance-contract scaffolding.

Verifies that the contract type system and the bundled sample
contracts are registerable, callable, and produce results in the
expected shape. Substantive contract behavior is covered by the
scenario-level integration tests.
"""

from __future__ import annotations

import pytest

from a2a_testbed.contracts import (
    Contract,
    ContractCategory,
    ContractResult,
    make_agent_card_required_fields_contract,
    make_jsonrpc_envelope_contract,
    make_jsonrpc_error_code_range_contract,
    make_method_not_found_contract,
    make_observer_completeness_contract,
    make_well_known_card_contract,
)
from a2a_testbed.transport import A2ATransport


@pytest.mark.asyncio
async def test_contract_passing_returns_passed():
    async def verify():
        return  # success path

    contract = Contract(
        id="test.passing",
        description="trivial passing contract",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
    result = await contract.verify()
    assert result.passed is True
    assert result.contract_id == "test.passing"
    assert isinstance(result, ContractResult)


@pytest.mark.asyncio
async def test_contract_assertion_error_records_message():
    async def verify():
        assert False, "boom"

    contract = Contract(
        id="test.failing",
        description="trivial failing contract",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
    result = await contract.verify()
    assert result.passed is False
    assert "boom" in result.detail


@pytest.mark.asyncio
async def test_contract_unexpected_exception_records_traceback():
    async def verify():
        raise RuntimeError("kaboom")

    contract = Contract(
        id="test.crashy",
        description="trivial crashing contract",
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
    result = await contract.verify()
    assert result.passed is False
    assert "RuntimeError" in result.detail
    assert "kaboom" in result.detail
    assert result.traceback is not None


def test_well_known_card_factory_returns_contract():
    transport = A2ATransport()
    contract = make_well_known_card_contract(transport, "http://x:1")
    assert contract.category == ContractCategory.TRANSPORT
    assert contract.id == "transport.well_known_card"


def test_jsonrpc_envelope_factory_returns_contract():
    transport = A2ATransport()
    contract = make_jsonrpc_envelope_contract(transport, "http://x:1")
    assert contract.category == ContractCategory.TRANSPORT
    assert contract.id == "transport.jsonrpc_envelope"


def test_agent_card_required_fields_factory():
    transport = A2ATransport()
    contract = make_agent_card_required_fields_contract(transport, "http://x:1")
    assert contract.category == ContractCategory.TRANSPORT
    assert contract.id == "transport.agent_card_required_fields"


def test_jsonrpc_error_code_range_factory():
    transport = A2ATransport()
    contract = make_jsonrpc_error_code_range_contract(transport, "http://x:1")
    assert contract.category == ContractCategory.TRANSPORT
    assert contract.id == "transport.jsonrpc_error_code_range"


def test_method_not_found_factory():
    transport = A2ATransport()
    contract = make_method_not_found_contract(transport, "http://x:1")
    assert contract.category == ContractCategory.TRANSPORT
    assert contract.id == "transport.method_not_found"


def test_observer_completeness_factory_returns_contract():
    from a2a_testbed.core.observer import ObserverHub
    from a2a_testbed.core.types import (
        AgentDecl,
        NetworkMode,
        Scenario,
        ScenarioResult,
        Step,
    )
    from datetime import datetime, timezone

    scenario = Scenario(
        name="x",
        agents=[AgentDecl(id="a", card="a.json")],
        flow=[Step.model_validate({"from": "a", "to": "a", "action": "p"})],
    )
    result = ScenarioResult(
        scenario_name="x",
        mode=NetworkMode.SIM,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        elapsed_ms=1.0,
        steps=[],
    )
    contract = make_observer_completeness_contract(scenario, result, ObserverHub())
    assert contract.category == ContractCategory.NETWORK
    assert contract.id == "network.observer_completeness"
