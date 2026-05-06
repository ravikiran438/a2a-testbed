# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Conformance contracts for A2A networks.

Public surface for the contract registry. Each contract is derived
from the published A2A specification (see ``CATALOG.md``); section
citations live in each contract module's docstring.
"""

from a2a_testbed.contracts.base import (
    Contract,
    ContractCategory,
    ContractResult,
)
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
from a2a_testbed.contracts.transport.agent_card_required_fields import (
    make_agent_card_required_fields_contract,
)
from a2a_testbed.contracts.transport.agent_card_supported_interfaces import (
    make_agent_card_supported_interfaces_contract,
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
from a2a_testbed.contracts.transport.send_message_required_fields import (
    make_send_message_required_fields_contract,
)
from a2a_testbed.contracts.transport.well_known_card import (
    make_well_known_card_contract,
)

__all__ = [
    "Contract",
    "ContractCategory",
    "ContractResult",
    # Transport contracts (spec-derived from A2A 1.0 + JSON-RPC 2.0)
    "make_agent_card_capabilities_contract",
    "make_agent_card_required_fields_contract",
    "make_agent_card_skill_attributes_contract",
    "make_agent_card_supported_interfaces_contract",
    "make_json_camel_case_contract",
    "make_jsonrpc_envelope_contract",
    "make_jsonrpc_error_code_range_contract",
    "make_jsonrpc_id_echo_contract",
    "make_jsonrpc_result_xor_error_contract",
    "make_jsonrpc_version_field_contract",
    "make_method_not_found_contract",
    "make_send_message_required_fields_contract",
    "make_well_known_card_contract",
    # Network contracts (original to a2a-testbed)
    "make_fault_recovery_contract",
    "make_observer_completeness_contract",
    "make_time_advance_visibility_contract",
]
