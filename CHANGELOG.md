# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
aims to follow [Semantic Versioning](https://semver.org/) (pre-1.0: minor
versions may include breaking changes).

## [0.2.0a1] — unreleased

### Added — Agent Control Specification (ACS) runtime governance

- **ACS module** (`a2a_testbed.acs`): manifest model, the wire-seam canonical
  input shaper mapping A2A exchanges to ACS intervention points, and a
  fail-closed evaluator with a dependency-free builtin rule engine.
- **Local validator** with a CLI: `a2a-testbed acs validate` (structural +
  semantic findings), plus `acs spec` (human-readable governance summary) and
  `acs init` (starter manifest scaffold). No `generate` — ACS manifests are
  authored intent, not a projection of a model.
- **Scenario integration**: `acs:` scenario field and `--acs` flag evaluate
  every step's wire exchange; verdicts surface in the CLI table, the JSON and
  Markdown reports, and the SVG badge.
- **Enforce mode** (`--acs-enforce` / `acs_enforce:` field): a deny/escalate
  blocks the handoff before dispatch and halts the flow.
- **Real evidence providers** (`acs.evidence`, e.g. `keyword_dlp`), auto-
  registered by the runner when a manifest references them.
- **OPA/Rego policy backend** (`acs.rego`) for `type: rego` manifests.
- **Playground**: a Validator-tab ACS mode (browser validator at parity with
  Python) and a Scenario-tab "Preview ACS" / "Enforce ACS" overlay that colors
  edges by verdict and evaluates the *real* response for live external agents.
- **ASSERT integration** (`examples/assert_integration`): an ASSERT
  `target.callable` that drives an A2A agent with ACS verdicts as judge
  evidence, OpenInference OTel spans (optional `[otel]` extra), and multi-turn
  `contextId` threading.

### Added — other

- **Java reference agent** (`agents/java-template`), completing the
  Python/Go/Node.js/Java polyglot subprocess story, with a gated polyglot test.
- **Browser↔Python parity guard** (`tests/test_browser_parity.py`) that fails
  on drift between the Python and TypeScript registries (contract ids + ACS
  finding-kinds / decisions / intervention points / ops).
- **CI** (`.github/workflows/ci.yml`): ruff + pytest on a Python 3.12/3.13
  matrix, and Biome + tsc + build for the playground.

### Changed

- **Playground tooling**: migrated to **pnpm**, replaced ESLint/Prettier with
  **Biome**, and added **Lefthook** git hooks.
- Mobile-friendly header/footer + touch-friendly canvas in the playground.
- SEO/discoverability: ACS-aware metadata, JSON-LD, and an `llms.txt` for
  AI-crawler discovery.

### Changed — A2A 1.0 (spec v1.0.1, a2a-sdk 1.2.2) with A2A 0.3 compatibility

The testbed advertised A2A 1.0 but spoke the pre-1.0 wire format (slash
method names, `kind` parts, bare Task results) almost everywhere — the
drift reported against the reference agent in
[a2aproject/A2A#1826](https://github.com/a2aproject/A2A/discussions/1826#discussioncomment-18226134).
Everything now speaks A2A 1.0 and stays backward compatible with 0.3.

- **Protocol dialects** (`transport/dialect.py`, mirrored by
  `playground/src/conformance/dialect.ts`): 1.0 and 0.3 method tables,
  request builders, `A2A-Version` handling, and 0.3 → 1.0 normalizers.
  Clients negotiate the version per agent from its AgentCard (1.0 unless
  the card is 0.3 or lists only 0.x JSONRPC interfaces).
- **Conformance suite** (CLI and browser): every contract probes in the
  agent's own version and checks 1.0-shaped results; 0.3 results are
  normalized first, 1.0 results never are. Rules introduced by 1.0 skip
  for 0.3 agents with an explicit detail. Contract ids are unchanged.
  `a2a-testbed conformance --protocol-version {1.0,0.3}` (and a selector
  in the playground) pins the version, e.g. to sweep the 0.3 surface of
  a dual-version agent.
- **4 new contracts** (62 transport contracts in total):
  `advertised_version_served` (catches the #1826 drift),
  `version_not_supported` (§3.6.2, `-32009`), `send_message_result_shape`
  (`{task}` / `{message}`, §9.4.1) and `streaming_jsonrpc_framing`
  (SSE frames are JSON-RPC responses, §9.4.2).
- **Contract fixes found while upgrading**: the SSE parser now accepts
  CRLF framing (the a2a-sdk's sse-starlette emits it — streams from any
  SDK-built agent previously parsed as empty); stream contracts unwrap
  JSON-RPC envelopes and accept message-only streams (§3.1.2);
  `tasks_cancel_sets_canceled` and the subscribe contracts act on a task
  that is still running (completed tasks are not cancelable /
  subscribable in 1.0) and accept `TaskNotCancelable`;
  `subscribe_replays_state` requires the Task as the first event for 1.0
  agents (§3.1.6);
  `agent_card_security_schemes` checks the 1.0 SecurityScheme oneof (the
  OpenAPI `type` form is 0.3's); card checks evaluate 0.3 cards in the 1.0
  layout via the a2a-sdk compat converter; push contracts accept 1.0
  StreamResponse webhooks.
- **Scenario runner**: sends `SendMessage` + `A2A-Version: 1.0` (or
  `message/send` to 0.3 agents); a 1.0 request answered with
  MethodNotFound is retried in 0.3 and the step detail says so (never
  under an injected fault, and drop / http_error steps still never
  contact the agent).
- **Testbed-hosted agents** (in-process agents, Python / Go / Node / Java
  templates) answer 1.0 and 0.3 callers in their own wire format; 1.0
  methods require `A2A-Version: 1.x` (absent = 0.3, §3.6.2). An agent
  declared with a 0.3 card behaves like a pre-1.0 deployment. In-process
  agents now return the spec's capability errors for streaming / push /
  extended card and TaskNotFound for task lookups instead of `-32601`.
- **Loader / card parsing** accept A2A 0.3 AgentCards (validated and
  converted with the a2a-sdk compat layer) and ignore unrecognized card
  fields, as the spec and the SDK's card resolver do — so the merged
  1.0 + 0.3 cards that a2a-sdk agents serving both versions publish load
  and sweep correctly. A card that claims 1.0 in the old top-level layout
  is treated as a (malformed) 1.0 card, not silently as 0.3. Cards that
  list a 0.3 interface are served with the 0.3 fields merged in, like the
  SDK does, so 0.3 clients can read them.
- **Reference task runner** (`examples/hosted-agents/cloudflare-task-runner`):
  implements every 1.0 method with 1.0 ProtoJSON payloads, 1.0 error codes
  with `google.rpc.ErrorInfo` details, strict `A2A-Version` negotiation,
  live `SubscribeToTask`, StreamResponse webhooks (also fired on cancel),
  and tasks that keep running if a streaming client disconnects; serves true 0.3
  payloads to 0.3 clients on the same URL (replacing the earlier hybrid),
  and advertises both versions in its card. `sdk_interop_check.py`
  drives it with both official a2a-sdk clients (1.0 and the SDK's 0.3
  compat client).
- **Math agent** (`examples/hosted-agents/cloudflare-math`): serves 1.0
  and 0.3, replies with a Message (it is stateless, so a Task would
  promise a GetTask it cannot honor), and returns the spec's capability
  errors for everything else.
- **Oracle agents** (`tests/oracles/sdk_agents.py`): a2a-sdk-built 1.0 and
  0.3 agents the suite is validated against; both pass every contract.
- New example: `examples/scenarios/mixed_versions.yaml` (a 1.0 and a 0.3
  agent talking both ways).
- `a2a-sdk[http-server]>=1.2.2`; spec pin moved to the v1.0.1 release
  (`3303592`).

**Upgrade notes.** Verdicts can change for agents whose card advertises
1.0 while they still serve 0.3 method names — they now fail
`advertised_version_served` instead of silently passing as 0.3. ACS
manifests that read an in-process agent's *response* see the 1.0
`{"message": {...}}` wrapper, and `input.method` / `tool_call.method`
is `SendMessage` rather than `message/send` (request-side paths such as
`message.parts.0.text` are unchanged).

### Changed — AG-UI 1.0 for the ACS verdict projection

- **Valid AG-UI 1.0 events.** An escalation's `RUN_FINISHED` interrupt now
  carries the required `threadId` and `runId` (`project_verdict(...,
  thread_id=, run_id=)` / `projectVerdict(v, { threadId, runId })`, with
  placeholder defaults for standalone use).
- **Unique interrupt ids.** Each escalation gets its own id
  (`acs-escalate-<point>-<random>`), so two escalations at the same
  intervention point in one thread can no longer answer each other's resume.
- **Resume arrays.** `resolve_escalation` / `resolveEscalation` accept the
  AG-UI 1.0 `RunAgentInput.resume` array and pick the entry whose
  `interruptId` matches. No matching entry, or a single entry addressed to a
  different interrupt, fails closed to `deny`; a single entry without an
  `interruptId` is still accepted.
- **Checked against the official SDK.** `ag-ui-protocol` (1.x) joins the
  `test`/`dev` extras, and every projected event and resume entry is
  validated against its models; Python and playground output are identical.

## [0.1.0a1]

- Initial alpha: multi-agent A2A scenario runner, polyglot runtimes
  (Python/Go/Node.js), fault injection, virtual time, observer pattern,
  58 A2A 1.0 conformance contracts, extension-manifest validation, and the
  in-browser playground.
