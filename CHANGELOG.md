# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
aims to follow [Semantic Versioning](https://semver.org/) (pre-1.0: minor
versions may include breaking changes).

## [Unreleased]

### Fixed

- **The corrupt fault always changes the payload.** It shuffled the
  pattern's characters, and a shuffle can reproduce the input (1 in 60 for
  "hello"); a palindrome reversed to itself in the fallback path. The
  fault was then a silent no-op, and `test_corrupt_mutates_payload` failed
  intermittently.

### Changed

- **Website brought up to date** (a2a-testbed.com): install from PyPI, the
  CI gate (GitHub Action, `conformance`, `lint-card`, baseline) and
  extension checks on MCP servers; contract count corrected to 62; the
  a2a-tck description no longer pins it to A2A 0.3.0. `llms.txt` and the
  page's structured data follow.

## [0.3.0a2] — 2026-10-11

### Fixed

- **MCP servers inherit the full environment.** A delegate without `env:`
  was started with the MCP SDK's minimal default environment, which drops
  `HTTPS_PROXY` and the other proxy variables, so a server fetched at
  start-up (the pinned `uvx --from git+...` PACE delegate) could not reach
  GitHub behind a proxy and every check failed with "MCP server
  unavailable (Connection closed)". `env:` entries still override.

### Changed

- `examples/mcp-delegates.yaml` pins the PACE MCP server to PACE v0.2.0
  through uvx, and `examples/scenarios/extension_checks.yaml` follows its
  time-zone-aware rules (`interaction_rules.timezone`, `at` timestamps).
  The example was written against an older PACE and failed two steps on
  v0.2.0. `docs/scenarios.md` explains why delegate versions should be
  pinned.
- The real-server example test runs only with `A2A_TESTBED_REAL_MCP=1`
  (it needs uvx and network access).

## [0.3.0a1] — 2026-10-11

### Changed (breaking) — scenario extension expectations are checked

- **Fixed: extension expectations always passed.** Up to 0.2.0a1 a step's
  `acap:`, `phala:`, `nerve:` and `pace:` blocks were copied into the step
  detail and never evaluated, so a step passed whatever they asserted.
  Results from scenarios that relied on them should be re-run.
- **New schema: `expect.extensions`**, keyed by extension URI. Each check
  names a tool on that extension's MCP server, its arguments and the
  expected verdict (`ok`, `violation` or `rejected`); a URI can carry a
  list of checks. The step fails closed on a wrong verdict, an
  unconfigured URI, a missing server or tool, a dead or silent server, or
  a malformed answer. The old field names are a load error with a
  migration hint, and unknown `expect:` keys are now rejected. See
  `docs/scenarios.md`.
- **MCP delegates are configuration.** The four built-in delegates and
  `make_default_registry()` are gone; the testbed source names no
  protocol. Delegates come from a scenario's `mcp_delegates:` (file or
  inline list), `run --mcp-delegates FILE` (overrides per URI) and
  `validate --via-mcp --mcp-delegates FILE` (now required with
  `--via-mcp`). `examples/mcp-delegates.yaml` carries the four reference
  protocols. `MCPDelegate.payload_validator_tool` / `payload_arg_name`
  are now `card_validator_tool` / `card_arg_name`.
- **MCP SDK 2.x.** Error results are read from `is_error` as well as
  `isError`; under SDK 2.x the old code never saw them, so card checks
  that a server rejected with an error were not reported as failures.
- `examples/scenarios/three_party_consent.yaml` lost its unchecked
  extension blocks; `examples/scenarios/extension_checks.yaml` shows real
  checks against the PACE server.
- The release workflow only runs for full version tags (`v*.*.*`), so
  moving the Action's `v0` tag no longer starts a failing release run.

## [0.2.0a1] — 2026-10-11

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

### Added — conformance gate for CI

- **GitHub Action** (`action.yml`, `uses: ravikiran438/a2a-testbed@v0`):
  sweeps a live `url` and/or lints a `card` file, writes the job summary,
  uploads SARIF to code scanning and fails the check on violations.
  Self-tested in `.github/workflows/action-selftest.yml`. Usage in
  `docs/ci.md`; the stories it was built for in `docs/consumer.md`.
- **Report formats**: `--format table|json|junit|sarif|markdown` for stdout
  and repeatable `-o PATH` files (`.json`, `.xml` JUnit, `.sarif`, `.md`);
  a Markdown summary is appended to `$GITHUB_STEP_SUMMARY` when set.
- **Baseline** (`.a2a-conformance.yaml`, `--baseline`, `--write-baseline`):
  accepted failures, each with a required reason and optional owner and
  expiry. Accepted rows stay visible (suppressed in SARIF); stale and
  expired entries are reported. Under `--strict`, deviations can be
  accepted too.
- **SARIF for code scanning**: findings anchor to a repository file
  (`--sarif-location`), fingerprints use the contract and file rather than
  the agent URL (per-PR preview URLs do not reopen alerts), and
  `--sarif-category` / the `sarif-category` input separate agents checked
  by one workflow.
- **`a2a-testbed lint-card FILE`**: the 15 card-only contracts of the live
  sweep against an AgentCard file, no server needed.
- **`--only CONTRACT_ID`** to run part of the live sweep.
- **Release workflow** (`.github/workflows/release.yml`): builds, checks and
  smoke-tests the wheel, then publishes to PyPI with trusted publishing on
  a `v*` tag.

### Changed — conformance results for CI

- **Result status.** Every contract result now carries a status: `pass`,
  `warn` (passed with a deviation), `skip`, `fail`, or `error` (the agent
  did not answer). `passed` is unchanged. Contracts can return `Info(...)`
  for a passing detail that is not a deviation; the version-served,
  0.3 result-shape and message-only-stream notes now do, so `--strict` no
  longer fails a conformant agent on them, nor on skipped contracts.
- **Timeouts and retries.** Each contract has a time limit (`--timeout`,
  45s). Timeouts and connection errors are `error`, retried once
  (`--retries`); wrong answers are never retried. An SSE stream that
  opens and then goes silent without closing is the agent's answer, so
  it is a `fail`, not an `error`.
- **Missing methods stay deviations.** "does not implement … (-32601)"
  details (a method the agent advertises or A2A 1.0 requires) are `warn`,
  so `--strict` still fails them; they are not "does not apply" skips.
- **Exit codes.** `0` conformant, `1` a contract failed, `3` no failures but
  some checks went unanswered, `2` usage error or agent unreachable. A dead
  URL is caught up front (exit 2) instead of producing 62 failures.
- **Push receiver.** `--push-receiver auto|local|hosted|off|URL`: loopback
  agents get an in-process receiver on 127.0.0.1 (no external service);
  remote agents use the hosted one. An unreachable or disabled receiver
  skips push delivery instead of failing it.
- **Installable from PyPI.** The A2A spec pin ships inside the package
  (`spec_pin.toml`), so a wheel reports the right spec instead of
  `unknown` or another project's `pyproject.toml`. README links are
  absolute so they work on PyPI, and the package ships `py.typed`.
- Two inconclusive outcomes are now reported as skips (`tasks_list_sorted_desc`
  with fewer than two tasks, `streaming_artifact_update_shape` with no
  artifact updates), in Python and the playground.

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
