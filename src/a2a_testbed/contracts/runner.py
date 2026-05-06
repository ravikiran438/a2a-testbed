# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Contract runner: evaluate every applicable contract against a
scenario's agents and produce a structured report.

Usage::

    from a2a_testbed.contracts.runner import run_transport_contracts
    results = await run_transport_contracts(transport, agent_url)

The runner doesn't decide which contracts to apply on its own — that's
the caller's choice. We provide ``run_transport_contracts`` (every
spec-derived transport contract against one agent) and
``run_network_contracts`` (every multi-agent network contract against
a completed ScenarioResult). A future ``run_all`` orchestrates both.
"""

from __future__ import annotations

from collections.abc import Iterable

from a2a_testbed.contracts.base import Contract, ContractResult
from a2a_testbed.contracts.network.fault_recovery import (
    make_fault_recovery_contract,
)
from a2a_testbed.contracts.network.observer_receives_traffic import (
    make_observer_completeness_contract,
)
from a2a_testbed.contracts.network.time_advance_visibility import (
    make_time_advance_visibility_contract,
)
from a2a_testbed.contracts.transport.agent_card_capabilities_object import (
    make_agent_card_capabilities_contract,
)
from a2a_testbed.contracts.transport.agent_card_has_skills import (
    make_agent_card_skill_attributes_contract,
)
from a2a_testbed.contracts.transport.agent_card_https_urls import (
    make_agent_card_https_urls_contract,
)
from a2a_testbed.contracts.transport.agent_card_preferred_interface import (
    make_agent_card_preferred_interface_contract,
)
from a2a_testbed.contracts.transport.agent_card_protocol_version_format import (
    make_agent_card_protocol_version_format_contract,
)
from a2a_testbed.contracts.transport.agent_card_required_fields import (
    make_agent_card_required_fields_contract,
)
from a2a_testbed.contracts.transport.agent_card_security_schemes import (
    make_agent_card_security_schemes_contract,
)
from a2a_testbed.contracts.transport.agent_card_skill_id_unique import (
    make_agent_card_skill_id_unique_contract,
)
from a2a_testbed.contracts.transport.agent_card_supported_interfaces import (
    make_agent_card_supported_interfaces_contract,
)
from a2a_testbed.contracts.transport.agent_card_url_well_formed import (
    make_agent_card_url_well_formed_contract,
)
from a2a_testbed.contracts.transport.default_modes_distinct import (
    make_default_modes_distinct_contract,
)
from a2a_testbed.contracts.transport.error_data_atype import (
    make_error_data_atype_contract,
)
from a2a_testbed.contracts.transport.extended_card_capability_consistency import (
    make_extended_card_capability_consistency_contract,
)
from a2a_testbed.contracts.transport.extensions_uri_absolute import (
    make_extensions_uri_absolute_contract,
)
from a2a_testbed.contracts.transport.extensions_uri_unique import (
    make_extensions_uri_unique_contract,
)
from a2a_testbed.contracts.transport.iso8601_timestamps import (
    make_iso8601_timestamps_contract,
)
from a2a_testbed.contracts.transport.json_camel_case import (
    make_json_camel_case_contract,
)
from a2a_testbed.contracts.transport.jsonrpc_envelope import (
    make_jsonrpc_envelope_contract,
)
from a2a_testbed.contracts.transport.jsonrpc_error_code_range import (
    make_jsonrpc_error_code_range_contract,
)
from a2a_testbed.contracts.transport.jsonrpc_id_echo import (
    make_jsonrpc_id_echo_contract,
)
from a2a_testbed.contracts.transport.jsonrpc_result_xor_error import (
    make_jsonrpc_result_xor_error_contract,
)
from a2a_testbed.contracts.transport.jsonrpc_version_field import (
    make_jsonrpc_version_field_contract,
)
from a2a_testbed.contracts.transport.method_not_found import (
    make_method_not_found_contract,
)
from a2a_testbed.contracts.transport.provider_well_formed import (
    make_provider_well_formed_contract,
)
from a2a_testbed.contracts.transport.push_delete_removes import (
    make_push_delete_removes_contract,
)
from a2a_testbed.contracts.transport.push_fires_on_completion import (
    make_push_fires_on_completion_contract,
)
from a2a_testbed.contracts.transport.push_get_returns_config import (
    make_push_get_returns_config_contract,
)
from a2a_testbed.contracts.transport.push_get_task_not_found import (
    make_push_get_task_not_found_contract,
)
from a2a_testbed.contracts.transport.push_list_returns_all import (
    make_push_list_returns_all_contract,
)
from a2a_testbed.contracts.transport.push_notifications_capability_consistency import (
    make_push_notifications_capability_consistency_contract,
)
from a2a_testbed.contracts.transport.push_set_persists import (
    make_push_set_persists_contract,
)
from a2a_testbed.contracts.transport.push_set_task_not_found import (
    make_push_set_task_not_found_contract,
)
from a2a_testbed.contracts.transport.send_message_required_fields import (
    make_send_message_required_fields_contract,
)
from a2a_testbed.contracts.transport.signatures_well_formed import (
    make_signatures_well_formed_contract,
)
from a2a_testbed.contracts.transport.streaming_artifact_update_shape import (
    make_streaming_artifact_update_shape_contract,
)
from a2a_testbed.contracts.transport.streaming_capability_consistency import (
    make_streaming_capability_consistency_contract,
)
from a2a_testbed.contracts.transport.streaming_event_kinds import (
    make_streaming_event_kinds_contract,
)
from a2a_testbed.contracts.transport.streaming_first_event_is_task import (
    make_streaming_first_event_is_task_contract,
)
from a2a_testbed.contracts.transport.streaming_response_content_type import (
    make_streaming_response_content_type_contract,
)
from a2a_testbed.contracts.transport.streaming_status_update_shape import (
    make_streaming_status_update_shape_contract,
)
from a2a_testbed.contracts.transport.streaming_task_id_consistency import (
    make_streaming_task_id_consistency_contract,
)
from a2a_testbed.contracts.transport.streaming_terminal_state_closes import (
    make_streaming_terminal_state_closes_contract,
)
from a2a_testbed.contracts.transport.subscribe_capability_required import (
    make_subscribe_capability_required_contract,
)
from a2a_testbed.contracts.transport.subscribe_not_found import (
    make_subscribe_not_found_contract,
)
from a2a_testbed.contracts.transport.subscribe_replays_state import (
    make_subscribe_replays_state_contract,
)
from a2a_testbed.contracts.transport.subscribe_returns_stream import (
    make_subscribe_returns_stream_contract,
)
from a2a_testbed.contracts.transport.task_artifacts_shape import (
    make_task_artifacts_shape_contract,
)
from a2a_testbed.contracts.transport.task_context_id_echoed import (
    make_task_context_id_echoed_contract,
)
from a2a_testbed.contracts.transport.task_history_shape import (
    make_task_history_shape_contract,
)
from a2a_testbed.contracts.transport.task_id_uuid_format import (
    make_task_id_uuid_format_contract,
)
from a2a_testbed.contracts.transport.task_status_state_enum import (
    make_task_status_state_enum_contract,
)
from a2a_testbed.contracts.transport.task_status_timestamp_present import (
    make_task_status_timestamp_present_contract,
)
from a2a_testbed.contracts.transport.tasks_cancel_not_found import (
    make_tasks_cancel_not_found_contract,
)
from a2a_testbed.contracts.transport.tasks_cancel_sets_canceled import (
    make_tasks_cancel_sets_canceled_contract,
)
from a2a_testbed.contracts.transport.tasks_get_not_found import (
    make_tasks_get_not_found_contract,
)
from a2a_testbed.contracts.transport.tasks_get_returns_task import (
    make_tasks_get_returns_task_contract,
)
from a2a_testbed.contracts.transport.tasks_list_sorted_desc import (
    make_tasks_list_sorted_desc_contract,
)
from a2a_testbed.contracts.transport.well_known_card import (
    make_well_known_card_contract,
)
from a2a_testbed.core.observer import ObserverHub
from a2a_testbed.core.types import Scenario, ScenarioResult
from a2a_testbed.transport import Transport


def transport_contracts(transport: Transport, agent_url: str) -> list[Contract]:
    """Build every spec-derived transport contract for one agent."""
    return [
        # AgentCard discovery + structural shape (§4.4, §8)
        make_well_known_card_contract(transport, agent_url),
        make_agent_card_required_fields_contract(transport, agent_url),
        make_agent_card_skill_attributes_contract(transport, agent_url),
        make_agent_card_skill_id_unique_contract(transport, agent_url),
        make_agent_card_capabilities_contract(transport, agent_url),
        make_agent_card_supported_interfaces_contract(transport, agent_url),
        make_agent_card_preferred_interface_contract(transport, agent_url),
        make_agent_card_url_well_formed_contract(transport, agent_url),
        make_provider_well_formed_contract(transport, agent_url),
        make_default_modes_distinct_contract(transport, agent_url),
        # Extension declarations (§4.4.4)
        make_extensions_uri_absolute_contract(transport, agent_url),
        make_extensions_uri_unique_contract(transport, agent_url),
        # Signatures (§4.4 + §13)
        make_signatures_well_formed_contract(transport, agent_url),
        # Versioning (§3.6)
        make_agent_card_protocol_version_format_contract(transport, agent_url),
        # Security & transport (§7.1, §7.3)
        make_agent_card_https_urls_contract(transport, agent_url),
        make_agent_card_security_schemes_contract(transport, agent_url),
        # JSON serialization (§5.5, §5.6.1)
        make_json_camel_case_contract(transport, agent_url),
        make_iso8601_timestamps_contract(transport, agent_url),
        # JSON-RPC envelope + error semantics (§3.1.1, §9.3, §9.5)
        make_jsonrpc_envelope_contract(transport, agent_url),
        make_jsonrpc_version_field_contract(transport, agent_url),
        make_jsonrpc_id_echo_contract(transport, agent_url),
        make_jsonrpc_result_xor_error_contract(transport, agent_url),
        make_jsonrpc_error_code_range_contract(transport, agent_url),
        make_method_not_found_contract(transport, agent_url),
        make_send_message_required_fields_contract(transport, agent_url),
        # Error envelope (§3.3.2)
        make_error_data_atype_contract(transport, agent_url),
        # Capability ↔ method consistency (§3.1.2, §3.5, §3.1.7)
        make_streaming_capability_consistency_contract(transport, agent_url),
        make_push_notifications_capability_consistency_contract(transport, agent_url),
        make_extended_card_capability_consistency_contract(transport, agent_url),
        # Task lifecycle (§3.4, §4.1.1, §4.1.3)
        make_task_id_uuid_format_contract(transport, agent_url),
        make_task_status_state_enum_contract(transport, agent_url),
        make_task_status_timestamp_present_contract(transport, agent_url),
        make_task_history_shape_contract(transport, agent_url),
        make_task_artifacts_shape_contract(transport, agent_url),
        # GetTask / CancelTask / ListTasks (§3.1.3, §3.1.4, §3.1.5)
        make_tasks_get_returns_task_contract(transport, agent_url),
        make_tasks_get_not_found_contract(transport, agent_url),
        make_tasks_cancel_sets_canceled_contract(transport, agent_url),
        make_tasks_cancel_not_found_contract(transport, agent_url),
        make_tasks_list_sorted_desc_contract(transport, agent_url),
        # Multi-turn (§3.4.2)
        make_task_context_id_echoed_contract(transport, agent_url),
        # Streaming SSE (§3.1.2, §4.1.6, §4.1.7)
        make_streaming_response_content_type_contract(transport, agent_url),
        make_streaming_first_event_is_task_contract(transport, agent_url),
        make_streaming_event_kinds_contract(transport, agent_url),
        make_streaming_status_update_shape_contract(transport, agent_url),
        make_streaming_artifact_update_shape_contract(transport, agent_url),
        make_streaming_task_id_consistency_contract(transport, agent_url),
        make_streaming_terminal_state_closes_contract(transport, agent_url),
        # Subscribe-to-task (§3.1.6)
        make_subscribe_returns_stream_contract(transport, agent_url),
        make_subscribe_replays_state_contract(transport, agent_url),
        make_subscribe_not_found_contract(transport, agent_url),
        make_subscribe_capability_required_contract(transport, agent_url),
        # Push notifications (§3.1.7–§3.1.10, §3.5)
        make_push_set_persists_contract(transport, agent_url),
        make_push_get_returns_config_contract(transport, agent_url),
        make_push_list_returns_all_contract(transport, agent_url),
        make_push_delete_removes_contract(transport, agent_url),
        make_push_set_task_not_found_contract(transport, agent_url),
        make_push_get_task_not_found_contract(transport, agent_url),
        make_push_fires_on_completion_contract(transport, agent_url),
    ]


def network_contracts(
    scenario: Scenario,
    result: ScenarioResult,
    observer_hub: ObserverHub,
) -> list[Contract]:
    """Build the multi-agent network contracts for a completed scenario."""
    return [
        make_observer_completeness_contract(scenario, result, observer_hub),
        make_fault_recovery_contract(result),
        make_time_advance_visibility_contract(result),
    ]


async def run_contracts(
    contracts: Iterable[Contract],
) -> list[ContractResult]:
    """Run every contract sequentially and collect results."""
    results: list[ContractResult] = []
    for contract in contracts:
        results.append(await contract.verify())
    return results


async def run_transport_contracts(
    transport: Transport, agent_url: str
) -> list[ContractResult]:
    """Run every spec-derived transport contract against one agent."""
    return await run_contracts(transport_contracts(transport, agent_url))


async def run_network_contracts(
    scenario: Scenario,
    result: ScenarioResult,
    observer_hub: ObserverHub,
) -> list[ContractResult]:
    """Run every network contract against a completed scenario result."""
    return await run_contracts(network_contracts(scenario, result, observer_hub))


def summarize(results: Iterable[ContractResult]) -> dict[str, int]:
    """Return a short summary dict: total / passed / failed."""
    items = list(results)
    return {
        "total": len(items),
        "passed": sum(1 for r in items if r.passed),
        "failed": sum(1 for r in items if not r.passed),
    }
