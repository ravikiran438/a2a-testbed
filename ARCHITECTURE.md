# Architecture

This document describes how `a2a-testbed` is put together and the
design choices that distinguish it from existing A2A tooling.

## Three-layer split

```
┌───────────────────────────────────────────────────────────────┐
│  CLI (typer)                                                  │
│  Reads YAML, drives the runner, prints + writes reports.      │
└─────────────────┬─────────────────────────────────────────────┘
                  │
┌─────────────────▼─────────────────────────────────────────────┐
│  ScenarioRunner                                               │
│  Loads scenario YAML, builds runtimes, boots the network,     │
│  drives the flow step-by-step, applies faults, evaluates      │
│  expectations, records observer history.                      │
└─┬─────────────────┬───────────────────────┬───────────────────┘
  │                 │                       │
  ▼                 ▼                       ▼
┌────────┐   ┌──────────────────┐   ┌─────────────────────┐
│ Loader │   │ Network          │   │ Runtimes            │
│ AgentCard JSON │ ↳ MultiTenant │   │ ↳ python_inproc    │
│ → protobuf     │   (sim mode)  │   │ ↳ python_subproc   │
│ → validated.   │ ↳ PerProcess  │   │ ↳ go               │
│                │   (realistic) │   │ ↳ nodejs           │
└────────────────┘                  │ ↳ java              │
                                     │ ↳ external          │
                                     └─────────────────────┘
```

### Layer 1: Loader (`core/loader.py`)

Reads JSON, validates against the official `a2a.types.AgentCard` proto
schema (via `google.protobuf.json_format.Parse`). Surfaces clear
errors for schema mismatch, JSON syntax errors, and missing files.

The loader is **deliberately minimal**: no extension-specific
knowledge. Extensions are validated at the conformance-contract
layer.

### Layer 2: Network (`network/multitenant.py`, `network/perprocess.py`)

**Sim mode** is the testbed's default network topology. One
Starlette + uvicorn server hosts N agents under path prefixes:

```
http://127.0.0.1:<port>/agents/<agent_id>/.well-known/agent-card.json
http://127.0.0.1:<port>/agents/<agent_id>/a2a/v1/        (JSON-RPC)
```

Compared to N-servers-on-N-ports:

- Faster scenario boot (no port allocation race per agent)
- Single log stream — easier debugging
- Shared in-process state available for observer agents
- Card URLs are deterministic from the path; no patching needed

Sim mode requires `runtime: python_inproc` for every agent because
subprocess agents are independent processes by definition.

**Realistic mode**: each agent gets its own runtime + port. Used
for cross-SDK conformance runs and production-topology validation.
Mixes runtime kinds within one scenario.

### Layer 3: Runtimes (`runtimes/`)

Polyglot lifecycle adapters. Each implements `start()` / `stop()` /
`url` / `agent_card` and is constructed from an `AgentDecl`.

| Runtime | Kind | Mechanism |
|---|---|---|
| `python_inproc` | in-process | Registered with the multi-tenant network; routed by path |
| `python_subproc` | subprocess | `python main.py --agent-card ...` |
| `go` | subprocess | `go run ./agents/go-template/ --agent-card ...` |
| `nodejs` | subprocess | `node ./agents/nodejs-template/index.js --agent-card ...` |
| `java` | subprocess | `java -jar ./agents/java-template/agent.jar --agent-card ...` *(reference jar not shipped yet; adapter exists, runtime kind reserved)* |
| `external` | none | Already running; testbed only points at the URL |

Subprocess runtimes share `subprocess_base.SubprocessRuntimeBase`
which:
- verifies the toolchain is on PATH (`go`, `node`, `java`)
- writes the AgentCard + scripts to a tempdir
- launches the subprocess with deterministic CLI flags
- waits for the `A2A_TESTBED_READY: <url>` line on stdout
- terminates cleanly on stop

The ready handshake is the polyglot contract: any language can play if
its agent prints that one line when its server is listening.

## Cross-cutting concerns

### Faults (`core/faults.py`)

Applied **client-side** at the orchestrator's HTTP seam, so the
agent under test sees a real wire-level anomaly indistinguishable
from a real network problem. Supported faults:

- `drop`: never sends the request; a `DroppedRequest` exception
  surfaces in the step result
- `delay`: sleeps `delay_ms` then sends normally
- `corrupt`: scrambles a substring (or a fallback random text part)
  before sending
- `http_error`: returns a synthetic JSON-RPC error response without
  contacting the agent

### Time controller (`core/time_controller.py`)

A per-scenario virtual clock with explicit `advance(seconds)`. Lets
scenarios test protocol TTLs, refresh cadences, and other time-bound
invariants without sleeping in tests. In-process agents can read the
controller's `now()`; subprocess agents see real wall-clock time
(they have no shared memory).

### Observers (`core/observer.py`)

Agents declared with `role: observer` receive every step's record via
an in-process hub. Observers don't appear as `from` / `to` in the
flow but accumulate history that scenario expectations can query.
Semantic validators can be plugged in for invariants like
"no behavioral drift accumulated across this scenario" or "audit
chain is complete and sealed."

## Wire protocol details

The testbed's **in-process multi-tenant network shim** (the HTTP
server `multitenant.py` boots when a scenario uses sim mode with
`runtime: python_inproc` agents) currently exposes:

- `GET /agents/<id>/.well-known/agent-card.json` → AgentCard JSON
- `POST /agents/<id>/a2a/v1/` → JSON-RPC `message/send`

Other A2A surface area (streaming, multi-turn, push notifications,
extended cards) is on the roadmap **for the in-process shim**. This
scope limit applies only to scenarios that route through the
testbed's own server; the conformance contract suite probes
streaming / subscribe / push against any external agent that
advertises the matching capability, and the reference task-runner
([`examples/hosted-agents/cloudflare-task-runner/`](examples/hosted-agents/cloudflare-task-runner/))
implements every spec surface the contracts probe. The minimal
in-process scope is deliberate: it's enough for protocol-extension
scenario testing and keeps the in-process codebase auditable.

## What we deliberately don't do

- We don't reimplement the A2A spec. The `a2a-sdk` library does the
  heavy lifting for AgentCard parsing and JSON-RPC primitives.
- We don't simulate at the message layer (queues, in-process objects).
  The whole point is exercising the real HTTP wire format with real
  AgentCards.
- We don't enforce semantic extension content in scenario step
  results yet. Extension expectations declared on a step are recorded
  but not enforced — the manifest layer (`manifest/`) and per-protocol
  MCP delegation (`extensions/`) are the available paths for that
  enforcement; wiring them into scenario step expectations is on the
  roadmap.

## Capability surface

The capabilities below fall out of the multi-agent + polyglot +
scenario design rather than being retrofitted. They are the focus
areas of this testbed:

- **Single-agent inspection** — partial; the testbed records but does
  not deeply introspect a single running agent.
- **Multi-agent orchestration** — full. JSON AgentCards declare the
  cohort; the scenario YAML drives the flow.
- **Cross-runtime polyglot** — full for Python, Go, Node.js in the
  same scenario; Java adapter scaffolded but inactive (reference
  jar pending — see
  [`agents/java-template/`](agents/java-template/)).
- **Failure injection** — full. Drop, delay, corrupt, HTTP-error at
  the wire seam, declared per step.
- **Virtual time control** — full. Per-scenario clock with explicit
  `advance(seconds)` for TTL/refresh testing.
- **Observer pattern** — full. Optional `role: observer` agent that
  taps every wire exchange (testbed primitive; A2A 1.0 itself defines
  bilateral exchanges only).
- **Reports** — JSON, Markdown, SVG-badge per-scenario.

## Conformance subsystem

The testbed has a first-class conformance layer: every behavior the
A2A 1.0 spec MUST/SHALL/REQUIREs is encoded as a small dataclass
+ async verify function under `src/a2a_testbed/contracts/`. Each
contract module's docstring carries the canonical citation
(`Spec: A2A 1.0 §<n>`, `Source:`, `Clause:`); the runner extracts
the citation at evaluation time and reports cite the spec section
on every row.

### Where coverage is anchored

The pinned A2A spec commit lives in `pyproject.toml` under
`[tool.a2a_testbed.spec]`:

```toml
[tool.a2a_testbed.spec]
name = "A2A"
version = "1.0"
commit = "<full-40-char-sha>"
last_reviewed = "<YYYY-MM-DD>"
source_repo = "https://github.com/a2aproject/A2A"
specification_path = "docs/specification.md"
```

`a2a_testbed.spec_meta` reads the block and exposes a typed
`SpecMeta` object that the CLI surfaces (`coverage`, `run`,
`conformance` outputs all stamp the commit short-SHA). The pin is
deliberate — bumping it without a contract sweep risks shipping
stale conformance claims. CONTRIBUTING.md "Tracking the upstream
A2A spec" describes the quarterly review checklist
(diff-against-upstream → classify changes → bump pin → re-run
suite).

### Two surfaces, one source of truth

The contract suite runs in two places, and produces the same
verdict on the same agent:

- **Python (CLI + scenario runner)** —
  `src/a2a_testbed/contracts/`. The canonical implementation. Used
  by `a2a-testbed run` (auto-evaluates against in-process agents),
  `a2a-testbed run --probe-external` (also probes external URLs in
  scenarios), and `a2a-testbed conformance <url>` (standalone
  sweep against any deployed agent). Each contract uses the
  `a2a-sdk` library's protobuf parser for AgentCard validation,
  which gives field-by-field schema enforcement for free.

- **TypeScript (browser playground)** —
  `playground/src/conformance/`. Same 58 transport contracts, same
  ordering, same id strings, same spec citations, same strict /
  soft-pass / fail verdict model. Bundled into the static
  playground; runs in the browser when a scenario declares an
  agent with `runtime: external` + `url:`. The playground is
  deployed as static files to Cloudflare Pages, so no backend is
  involved — the user's browser calls the deployed agent
  directly, evaluates expectations + contract assertions, and
  renders results inline.

### Why TypeScript port instead of a hosted endpoint

The browser surface needed conformance checks for `runtime:
external` agents (today's playground does animation + YAML
expectation matching, but doesn't run the spec contracts). Two
ways to add it:

1. **Hosted endpoint** — keep the Python contracts as the only
   implementation; the playground POSTs to a small Python
   service that runs the sweep and returns results.
2. **TypeScript port** — duplicate the contracts in TS so they
   run in the visitor's browser.

We chose the TS port. The playground is pure static (Cloudflare
Pages, no backend) and a hosted endpoint would break that — adding
deploy infrastructure, ongoing cost, and an HTTP hop on every
sweep. The duplication is bounded (~58 short modules) and the
correctness story is "run the same agent through both, prove
equivalent verdicts" — validated by sweeping the live hosted
agents under [`examples/hosted-agents/`](examples/hosted-agents/)
through both surfaces and confirming pass / soft-pass / fail rows
match. Capabilities the agent doesn't advertise (e.g. the math
worker has `streaming: false, pushNotifications: false`) skip
cleanly through the same skip-gracefully pattern in both surfaces,
keeping verdicts identical regardless of agent feature set.

**The only Python-specific bit is the SDK's protobuf parser**
(used by `well_known_card` + `agent_card_required_fields` for
AgentCard schema validation). The TS port replaces this with
direct JSON-shape validation: the A2A spec defines AgentCard
fields by name in §4.4.1, so we don't need the `.proto` — we
assert the same field presence + types in TS. Every other
contract is a vanilla HTTP probe + JSON assertion that ports
directly.

### Quarterly drift discipline

The TS port can drift from the Python source of truth if a
contract is added in one place and not the other. Two safeguards:

- **Same id strings + ordering** — `playground/src/conformance/contracts/index.ts`
  mirrors `src/a2a_testbed/contracts/runner.py#transport_contracts`
  in the same order. A reviewer can `diff` the two lists at a
  glance.
- **Quarterly review (CONTRIBUTING.md)** — when bumping the spec
  pin, the checklist explicitly flags adding new contracts to
  *both* surfaces. Skipping the TS port surfaces in `coverage`
  command output (which counts the Python implementation only)
  but doesn't break tests, so the review is the only safety net.
  Future hardening: a `tests/test_browser_parity.py` that
  fingerprints both registries and fails on drift.

### What's covered

Run `a2a-testbed coverage` for the live count. Spec-derived
contracts span: AgentCard discovery + structural shape (§4.4,
§8), extension declarations (§4.4.4), signatures (§4.4 + §13),
versioning (§3.6), transport-level security (§7.1, §7.3), JSON
serialization (§5.5, §5.6.1), JSON-RPC envelope + error
semantics (§3.1.1, §9.3, §9.5), capability ↔ method consistency
(§3.1.2, §3.5, §3.1.7), Task lifecycle (§3.4, §4.1.1, §4.1.3),
GetTask / CancelTask / ListTasks (§3.1.3–§3.1.5), multi-turn
contextId (§3.4.2), **streaming SSE** (§3.1.2, §4.1.6, §4.1.7),
**subscribe-to-task** (§3.1.6), and **push notifications**
(§3.1.7–§3.1.10, §3.5). Network-layer contracts (observer
completeness, fault recovery, time-advance visibility) are
testbed-original — A2A is a per-agent spec and doesn't constrain
multi-agent flows.

The streaming, subscribe, and Task contracts use a **skip-gracefully**
pattern: each first probes whether the agent advertises the
matching capability or produces the relevant envelope; if not,
the contract reports a "skipped" detail and passes. The same
contract suite therefore runs cleanly against agents that
support the full surface AND agents that only do `message/send`.

### Reference task runner

The `examples/hosted-agents/cloudflare-task-runner/` worker is a
spec-compliant A2A 1.0 reference agent — it implements every
method the contracts probe (message/send + message/stream,
tasks/get/list/cancel/resubscribe, all four
pushNotificationConfig methods) plus genuine async semantics
(`configuration.blocking: false` schedules work via
`ctx.waitUntil` so clients can register push configs before
completion). The companion `cloudflare-push-receiver/` worker
captures incoming webhooks per probe-token so the
`push_fires_on_completion` contract can verify delivery
end-to-end. Together they exist for one purpose: the contract
suite has something to prove its positive case against. Any
third-party A2A agent passing the same suite is conforming
against the same evidence.

## Implementation status (alpha)

| ☑ | Component |
|---|---|
| ☑ | Loader (JSON AgentCard → validated typed object) |
| ☑ | Multi-tenant network (sim mode) |
| ☑ | Per-process network (realistic mode) |
| ☑ | Transport abstraction — `A2ATransport` is the only implementation today; alternative inter-agent protocols plug in as `Transport` subclasses |
| ☑ | Polyglot runtime adapters — Python in-process, Python subprocess, Go, Node.js, external URL; Java template documented (jar pending contributor) |
| ◐ | Polyglot subprocess end-to-end — Python verified; Go / Node.js / Java exercised in `tests/polyglot/` when the toolchain is on `PATH` |
| ☑ | Faults: drop / delay / corrupt / http_error |
| ☑ | Virtual time controller |
| ☑ | Observer agents + wire-level traffic taps |
| ☑ | Reports: JSON / Markdown / SVG badge |
| ☑ | CLI (typer) |
| ☑ | Conformance contract suite — 58 spec-derived transport contracts + 3 network contracts, each citing its A2A 1.0 spec section; pin + quarterly review process documented |
| ☑ | Reference task-runner agent + push receiver (`examples/hosted-agents/cloudflare-task-runner/` and `cloudflare-push-receiver/`) — exists so the contract suite can verify its positive case against a known-conformant agent |
| ☑ | Spec-pin metadata (`pyproject.toml` `[tool.a2a_testbed.spec]`) + `coverage` CLI + `conformance <url>` standalone sweep |
| ☑ | Browser-side conformance port (`playground/src/conformance/`) — same 58 transport contracts in TS, runs against `runtime: external` agents in the visitor's browser |
| ☑ | Extension manifest convention + JSON-Schema validator |
| ☑ | MCP delegation for richer per-extension semantic checks |
| ☑ | In-browser playground (canvas + AgentCard validator + live LLM scenario + conformance sweep) |

Legend: ☑ shipped · ◐ partial · ☐ planned

## Roadmap

> The "vendor compatibility" track means *static compatibility
> reports* (would this AgentCard deploy cleanly on Foundry / ADK /
> Bedrock?) plus *deployment scaffolds* (generate Bicep / Terraform /
> gcloud files the user runs themselves). It does **not** mean
> one-click deploy: the testbed does not take credentials, provision
> infrastructure, or manage state. Real deployment automation
> belongs to Pulumi, AWS CDK, Azure Bicep, Terraform Cloud, and
> equivalent tools.


| ☑ | Track | What lands |
|---|---|---|
| ☑ | Core runtime | Sim mode, realistic mode, faults, virtual time, observers, multi-tenant network, polyglot runtime adapters, transport abstraction, spec-derived conformance contracts |
| ◐ | Cross-SDK polyglot end-to-end | Go, Node.js subprocess agents (Python verified end-to-end); Java reference agent pending |
| ☑ | Extension validation | ExtensionManifest convention, generic JSON-Schema validator, MCP delegation glue for richer per-extension semantic checks |
| ☑ | Vendor compatibility | Static AgentCard compatibility check against A2A 1.0 + user-pluggable dialect-file framework for non-A2A platforms |
| ☑ | In-browser playground | React + xyflow canvas + animation + browser-side AgentCard validator (alpha) |
| ☐ | Scenario-level enforcement | Per-step extension-expectation enforcement; richer scenario-level invariant validators |

Legend: ☑ shipped · ◐ partial · ☐ planned
