# Contract catalog (spec-derived)

Every contract in this directory is derived from the published A2A
specification. The authoritative source is the LF AI & Data
Foundation [A2A repository](https://github.com/a2aproject/A2A) — the
spec text itself lives at
[`docs/specification.md`](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
in that repo.

## Sourcing principle

Each contract cites:

```
Spec:    A2A 1.0 §<section>
Source:  https://github.com/a2aproject/A2A/blob/main/docs/specification.md
Clause:  <one-sentence paraphrase of the MUST/SHALL>
```

Contracts are derived from the spec text rather than from any
implementation. This keeps them stable across SDK releases and avoids
encoding implementation-specific choices like custom URI namespaces,
project-specific command-keyword routing, or invented extension
semantics.

## Coverage

A full sweep of the A2A spec produced ~81 testable conformance
requirements across 13 categories. The current bundle covers **61**:
58 transport contracts spanning AgentCard discovery + structure,
extension declarations, signatures, versioning, transport-level
security, JSON serialization, JSON-RPC envelope/error semantics,
capability ↔ method consistency, task lifecycle, GetTask /
CancelTask / ListTasks, multi-turn (contextId), **streaming (SSE)**,
**subscribe-to-task**, and **push notifications**, plus 3 network
contracts (observer completeness, fault recovery, time-advance
visibility), plus **manifest-based extension validation** that checks
any extension's AgentCard payload against a published
`ExtensionManifest` with **zero protocol-specific code**. The
remaining open clauses are largely capability-validation edge cases
and authorization scheme negotiation.

**Live coverage:** run `a2a-testbed coverage` for a current
implemented-vs-roadmap breakdown with the spec-pin header.

## Manifest-based extension validation

Every A2A extension URI in `capabilities.extensions[]` is expected
to resolve to a JSON manifest at `<URI>/manifest.json`. The manifest
carries metadata, a JSON Schema for the AgentCard payload
(auto-generated from a pydantic model via `model_json_schema()`),
optional wire-artefact descriptors, and human-readable invariants.
The testbed fetches the manifest and validates the declared payload
against the schema dynamically.

This means:
- The testbed has **no hard-coded knowledge of any extension URI**.
- Any extension that publishes a manifest is validated automatically.
- Extensions that augment runtime behavior without adding card
  fields use a permissive `OpaquePayload` schema and are still
  discoverable.

CLI: `a2a-testbed card <agent-url>` validates a live agent's card.
`a2a-testbed manifest generate` produces a manifest from any pydantic
model. `a2a-testbed manifest validate <path>` checks a manifest file.

## Implemented contracts

Transport (13) + network (3). Each row is a Python module under
`src/a2a_testbed/contracts/<category>/<id>.py` whose docstring
carries the canonical spec citation (the `Spec:` line). The runner
extracts that section at evaluation time and the report writer
renders it as the per-row "Spec §" column.

### AgentCard discovery + structural shape

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.well_known_card` | §8.2 — Agent Card discovery | RFC 8615 well-known URI; `/.well-known/agent-card.json` |
| `transport.agent_card_required_fields` | §4.4.1 + §8.1 | name, description, version, supportedInterfaces, capabilities, defaultInputModes, defaultOutputModes, skills |
| `transport.agent_card_skill_attributes` | §4.4.1 | Each skill carries id, name, description, tags |
| `transport.agent_card_skill_id_unique` | §4.4.1 | Skill ids unique within the card |
| `transport.agent_card_capabilities_object` | §4.4.1 | capabilities is an object (not list); enforces shape |
| `transport.agent_card_supported_interfaces` | §8.3.1 | supportedInterfaces[*] has protocolBinding + url |
| `transport.agent_card_preferred_interface` | §8.3.1 | supportedInterfaces[0] is well-formed (preferred) |
| `transport.agent_card_url_well_formed` | §4.4.1 | All URLs on the card are absolute, parseable |
| `transport.provider_well_formed` | §4.4.1 | provider object (when present) carries organization + valid URL |
| `transport.default_modes_distinct` | §4.4.1 | defaultInputModes / defaultOutputModes contain no duplicates |

### Extension declarations

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.extensions_uri_absolute` | §4.4.4 | capabilities.extensions[*].uri values are absolute http(s) URLs |
| `transport.extensions_uri_unique` | §4.4.4 | capabilities.extensions[*].uri values are unique within the card |

### Signatures

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.signatures_well_formed` | §4.4 + §13 | AgentCard.signatures (when present) follow JWS shape: `protected` + `signature` are base64url, `header` is an object |

### Versioning

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.agent_card_protocol_version_format` | §3.6 | protocolVersion is Major.Minor (no patch) |

### Transport-level security

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.agent_card_https_urls` | §7.1 | Non-loopback supportedInterfaces URLs use https/wss |
| `transport.agent_card_security_schemes` | §7.3 | Declared securitySchemes use recognized OpenAPI types |

### JSON serialization

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.json_camel_case` | §5.5 | JSON field names use camelCase, not snake_case |
| `transport.iso8601_timestamps` | §5.6.1 | Response timestamps end with 'Z' (UTC) |

### JSON-RPC envelope + error semantics

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.jsonrpc_envelope` | §3.1.1 + JSON-RPC 2.0 §5 | jsonrpc field, id matching, exactly one of result/error |
| `transport.jsonrpc_version_field` | §9.3 + JSON-RPC 2.0 §5 | Every response carries `jsonrpc: "2.0"` |
| `transport.jsonrpc_id_echo` | §9.3 | Response id matches the request id |
| `transport.jsonrpc_result_xor_error` | JSON-RPC 2.0 §5 | Exactly one of result / error per response |
| `transport.jsonrpc_error_code_range` | §9.5 | A2A-specific errors live in `-32001..-32099` |
| `transport.method_not_found` | §9 + JSON-RPC 2.0 §5.1 | Unknown method returns `-32601` |
| `transport.send_message_required_fields` | §3.1.1 | `message/send` request shape constraints |
| `transport.error_data_atype` | §3.3.2 | error.data[*] entries carry `@type` per ProtoJSON Any |

### Capability ↔ method consistency

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.streaming_capability_consistency` | §3.1.2, §9.5 | When `capabilities.streaming=false`, `message/stream` MUST return `-32004` (UnsupportedOperationError) |
| `transport.push_notifications_capability_consistency` | §3.5, §9.5 | When `capabilities.pushNotifications=false`, push config ops MUST return `-32003` (PushNotificationNotSupportedError) |
| `transport.extended_card_capability_consistency` | §3.1.7, §9.5 | When `capabilities.extendedAgentCard=false`, `agent/getAuthenticatedExtendedCard` MUST return `-32004` |

The capability-consistency contracts pass strictly when the
spec-mandated error code is returned; they pass with a deviation
detail (visible in the report) when the agent honored the
capability but used a different error code (e.g. `-32601`). A 200
result against any of these methods when the capability is `false`
fails the contract — that's the agent lying about its capabilities.

### Task lifecycle

Skip-gracefully: contracts probe with `message/send` and inspect the
response. If the agent returns a Message instead of a Task, the
contract reports a "skipped" detail and passes.

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.task_id_uuid_format` | §3.4 + §4.1.1 | Task.id is a server-generated UUID |
| `transport.task_status_state_enum` | §4.1.3 + §5.5 | Task.status.state is a recognized TaskState (TASK_STATE_*) |
| `transport.task_status_timestamp_present` | §3.4 + §5.6.1 | Task.status.timestamp is ISO 8601 UTC |
| `transport.task_history_shape` | §4.1.1 + §4.1.4 | Task.history (when present) is well-formed Message array |
| `transport.task_artifacts_shape` | §4.1.1 + §4.1.5 | Task.artifacts (when present) carry artifactId + parts |

### GetTask / CancelTask / ListTasks

Each contract checks for `-32601` (method not implemented) before
running its assertion; agents that don't support tasks/* skip
gracefully. The not-found contracts use the same strict / soft-pass
model as the capability contracts (200+result fails; -32001 is a
strict pass; other error codes are soft passes).

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.tasks_get_returns_task` | §3.1.3 | tasks/get returns the Task identified by id |
| `transport.tasks_get_not_found` | §3.1.3 + §9.5 | unknown id returns TaskNotFoundError (-32001) |
| `transport.tasks_cancel_sets_canceled` | §3.1.5 | tasks/cancel transitions task to TASK_STATE_CANCELED (or another terminal state) |
| `transport.tasks_cancel_not_found` | §3.1.5 + §9.5 | unknown id returns TaskNotFoundError |
| `transport.tasks_list_sorted_desc` | §3.1.4 | tasks/list returns tasks sorted desc by status.timestamp |

### Multi-turn (contextId)

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.task_context_id_echoed` | §3.4.2 | Client-provided contextId is preserved on response Task or rejected with error (silent substitution is non-conformant) |

### Streaming (SSE)

Verified end-to-end against the reference task runner at
`examples/hosted-agents/cloudflare-task-runner/`. Each contract
short-circuits with a "skipped" detail when the AgentCard reports
`capabilities.streaming: false`, so the suite stays clean against
agents that only do `message/send`.

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.streaming_response_content_type` | §3.1.2 | message/stream returns Content-Type text/event-stream |
| `transport.streaming_first_event_is_task` | §3.1.2 | first SSE event carries the Task envelope |
| `transport.streaming_event_kinds` | §3.1.2 | events carry task / statusUpdate / artifactUpdate |
| `transport.streaming_status_update_shape` | §4.1.6 | TaskStatusUpdateEvent has taskId + status{state, timestamp} |
| `transport.streaming_artifact_update_shape` | §4.1.7 | TaskArtifactUpdateEvent has taskId + Artifact |
| `transport.streaming_task_id_consistency` | §3.1.2 | every SSE event references the same taskId as the initial task envelope |
| `transport.streaming_terminal_state_closes` | §3.1.2 + §4.1.3 | stream closes after a terminal-state statusUpdate |

### Subscribe-to-task

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.subscribe_returns_stream` | §3.1.6 | tasks/resubscribe returns Content-Type text/event-stream |
| `transport.subscribe_replays_state` | §3.1.6 | first event reflects the subscribed task's current state |
| `transport.subscribe_not_found` | §3.1.6 + §9.5 | unknown id returns TaskNotFoundError (-32001) |
| `transport.subscribe_capability_required` | §3.1.6 + §9.5 | tasks/resubscribe returns -32004 when streaming=false |

### Push notifications

The `push_fires_on_completion` contract drives the agent through a
real send → set-config → completion → webhook delivery cycle, using
the companion `cloudflare-push-receiver` worker as the webhook
target. Override the receiver via the `A2A_TESTBED_PUSH_RECEIVER`
env var when testing on networks where the default URL isn't
reachable.

| Contract id | Spec section | Notes |
|---|---|---|
| `transport.push_set_persists` | §3.1.7 | pushNotificationConfig/set returns the stored config with id |
| `transport.push_get_returns_config` | §3.1.8 | get retrieves the stored config |
| `transport.push_list_returns_all` | §3.1.9 | list returns every stored config for a task |
| `transport.push_delete_removes` | §3.1.10 | delete removes the config from list |
| `transport.push_set_task_not_found` | §3.1.7 + §9.5 | set on unknown taskId returns -32001 |
| `transport.push_get_task_not_found` | §3.1.8 + §9.5 | get on unknown taskId returns -32001 |
| `transport.push_fires_on_completion` | §3.5 | agent POSTs the Task to the registered URL on completion |

### Network contracts (original to a2a-testbed)

| Contract id | Spec section | Notes |
|---|---|---|
| `network.observer_completeness` | Original — A2A is a per-agent protocol; multi-agent contracts are our differentiator | Observer wire history covers every completed send step |
| `network.fault_recovery` | Original | Network handles drop/delay/corrupt without losing state |
| `network.time_advance_visibility` | Original | Virtual-clock advances are recorded in observer history |

## Roadmap contracts (planned, gated on capability landing)

| Category | Spec sections | Count |
|---|---|---|
| Streaming (SSE) | §3.1.2, §3.5.2 | ~7 |
| Task lifecycle | §3.4, §4.1.3 | ~7 |
| Multi-turn (contextId / taskId) | §3.4.1, §3.4.2, §3.4.3 | ~5 |
| Push notifications | §3.1.7–§3.1.10, §13.2 | ~7 |
| GetTask / ListTasks / CancelTask | §3.1.3, §3.1.4, §3.1.5 | ~10 |
| Subscribe to task | §3.1.6 | ~4 |
| Extensions | §4.4.4, §4.6 | ~6 |
| Versioning | §3.6 | ~3 |
| Authorization / security | §13 | ~4 |
| Capability validation | §3.3.4 | ~5 |

## Network contracts (original to a2a-testbed)

A2A is a per-agent specification — it normatively constrains how a
single agent must behave on the wire, not how a network of agents must
coordinate. Multi-agent flow contracts are therefore our original
contribution and clearly marked as such.

Planned network contracts include:

| Contract id | Concept |
|---|---|
| `network.observer_completeness` | observer agents see every completed wire exchange |
| `network.consent_chain_audit` | ACAP-extension-aware: every consent step appears in the chain |
| `network.fault_recovery_drop` | network handles `drop` faults without losing state |
| `network.fault_recovery_delay` | network handles `delay` faults; deadlines respected |
| `network.cross_sdk_interop` | identical scenario produces identical observable behavior across Python / Go / Node.js / Java agents |

These are protocol-stack-aware (they sometimes depend on declared
extensions) but the structural contracts above operate purely on what
the A2A spec mandates.

## Citing the spec in a new contract

Add this header block to every new contract module:

```python
"""<one-sentence summary of what this contract verifies>

  Spec:    A2A 1.0 §<section>
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  <paraphrased MUST/SHALL>
"""
```

If the contract is original to a2a-testbed (network-level, not
derivable from A2A), the header reads:

```python
"""<summary>

  Spec:    Original to a2a-testbed
  Rationale: <one paragraph on why this contract exists>
"""
```

This convention keeps the contract suite traceable when the A2A spec
revises and makes the original-vs-derived distinction unambiguous.
