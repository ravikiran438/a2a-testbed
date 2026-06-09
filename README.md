# a2a-testbed

[![CI](https://github.com/ravikiran438/a2a-testbed/actions/workflows/ci.yml/badge.svg)](https://github.com/ravikiran438/a2a-testbed/actions/workflows/ci.yml)

**Live at [a2a-testbed.com](https://a2a-testbed.com)** · CLI on
[GitHub](https://github.com/ravikiran438/a2a-testbed) · Apache 2.0

A polyglot, JSON-driven, multi-agent [A2A](https://a2a-protocol.org/)
network simulator with scenario runner, observer agents, virtual time
control, failure injection, and an in-browser playground for live
AgentCard validation.

## What it does

You drop your A2A `AgentCard` JSON files in a directory, write a YAML
scenario that names the agents and the messages flowing between them,
and the testbed boots a real multi-agent network for the duration of
the run, drives the scenario, and reports pass/fail per step plus a
JSON / Markdown / SVG-badge artefact. Agents are polyglot: each agent
in a scenario picks its runtime independently, so a Python principal
can interoperate with a Go service provider and a Node.js guardian
inside the same scenario. The result is a focused test environment
for multi-agent A2A protocol extensions and cross-runtime
interoperability.

The testbed also ships an extension-validation layer that follows a
small convention: each extension publishes a JSON Schema manifest at
its URI, and a generic validator checks any AgentCard payload against
that schema with **zero protocol-specific code**. See `manifest/` and
`extensions/` for the convention's reference types and the manifest
generator.

## What this tool focuses on

`a2a-testbed` is built around a specific set of multi-agent testing
capabilities:

- Spin up a multi-agent network from JSON AgentCard files.
- Run scripted YAML scenarios across that network.
- Compose Python + Go + Node.js agents in one scenario (Java
  runtime adapter scaffolded; reference agent on roadmap).
- Inject failures (drop, delay, corrupt, HTTP error) at the message
  layer.
- Advance a virtual clock to test TTLs and refresh cadences.
- Drive observer agents for cross-agent integrity testing (an
  optional testbed primitive — A2A 1.0 itself defines bilateral
  exchanges only).
- Validate `capabilities.extensions[]` payloads against published
  JSON-Schema manifests.
- Validate **Agent Control Specification (ACS)** manifests and map their
  runtime-control checkpoints onto the A2A wire seam, with fail-closed
  checks — offline (CLI) and in-browser. See [docs/ACS.md](docs/ACS.md).

## Quick start

```bash
git clone https://github.com/ravikiran438/a2a-testbed.git
cd a2a-testbed
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"

# 1. Run the bundled three-party guardian-mediated consent scenario
a2a-testbed run examples/scenarios/three_party_consent.yaml

# 2. Run a live A2A 1.0 transport-contract sweep against any deployed
#    agent. 58 spec-derived contracts; cites the spec section for
#    each row. Use for your own Cloudflare/Lambda/GKE deployments.
a2a-testbed conformance https://my-agent.example.com

# 3. Run a multi-agent scenario AND probe its `runtime: external`
#    agents with the contract sweep in the same pass.
a2a-testbed run --probe-external examples/scenarios/my_scenario.yaml

# 4. Validate a live agent's AgentCard + every declared extension
#    against its published manifest
a2a-testbed card https://my-agent.example.com

# 5. Statically validate an AgentCard JSON file (offline; no network)
a2a-testbed validate path/to/agent-card.json --manifest-dir ./manifests

# 6. Static AgentCard compatibility check against A2A 1.0 (built-in)
#    or against a user-supplied dialect file (-f some-dialect.json)
a2a-testbed compat path/to/card.json

# 7. Show contract coverage with the spec pin (which A2A commit, last
#    review date, % of clauses covered)
a2a-testbed coverage

# 8. Generate an ExtensionManifest from a pydantic model
a2a-testbed manifest generate \
  --extension-uri https://example.org/my-protocol/v1 \
  --name "My Protocol" \
  --version 1.0.0 \
  --ref-class my_protocol.types:MyServiceRef \
  --output ./manifest.json

# 9. Author + validate an Agent Control Specification (ACS) manifest.
#    `init` scaffolds, `validate` checks (--strict for CI), `spec`
#    renders a human-readable governance summary. See docs/ACS.md.
a2a-testbed acs init --name my-agent -o my-agent.acs.yaml
a2a-testbed acs validate examples/acs/email-agent.acs.yaml
a2a-testbed acs spec examples/acs/three-party-governance.acs.yaml

# 10. Apply ACS runtime governance to a scenario. Evaluates every
#     handoff against the manifest and prints per-step verdicts
#     (allow/warn/deny). Use the scenario's `acs:` field or --acs.
a2a-testbed run examples/scenarios/three_party_governed.yaml
a2a-testbed run --acs examples/acs/three-party-governance.acs.yaml \
  examples/scenarios/three_party_consent.yaml

# 11. Enforce ACS: a deny/escalate blocks the handoff before dispatch
#     and halts the flow (instead of just recording the verdict).
a2a-testbed run --acs-enforce \
  --acs examples/acs/three-party-governance.acs.yaml \
  examples/scenarios/three_party_consent.yaml
```

The bundled three-party scenario produces a colored step table and
written reports under `examples/scenarios/reports/`.

## Common tasks

The repo ships a [`Justfile`](Justfile) that orchestrates work across
all the apps (Python testbed, in-browser playground, hosted demo
agents). Install [Just](https://just.systems) once
(`brew install just` on macOS, or see the install page for other
platforms), then:

```bash
just                 # list every recipe
just install         # install Python + JS deps for every app
just doctor          # report which toolchains are on PATH
just test            # run every test (Python + playground typecheck)
just build           # build production artifacts for every JS app
just dev             # start the playground at http://localhost:5173
just math-deploy     # deploy the Cloudflare math agent
just clean           # wipe every build artefact + node_modules / cache
```

Recipes are thin wrappers — every app stays independently buildable
with its native toolchain (`pip`, `npm`, `wrangler`). The Justfile
just removes the need to remember each one.

## In-browser playground

The `playground/` directory is a Vite + React + TypeScript app with
two modes:

- **Scenario** — render a multi-agent flow as a node graph
  (powered by [`@xyflow/react`](https://reactflow.dev/)), animate
  message edges as the scenario runs, click any node or edge to
  inspect its AgentCard / message payload. Pick a built-in scenario
  from the dropdown (including the **live LLM agent validator** —
  see below) or paste your own CLI-format YAML.
- **Validate AgentCard** — paste an AgentCard JSON, click **Validate
  against live manifests**, and see per-extension findings rendered
  via in-browser JSON Schema validation. No backend required.

When a scenario declares an agent with `runtime: external` and a
`url:`, the playground makes **real HTTP calls** to that deployment
and enforces each step's `expect` block (`response_status`,
`response_contains`) against the actual response — same checks the
CLI runs. The bundled `cloudflare_math_demo` scenario drives a live
LLM-backed A2A agent on Cloudflare Workers (Llama 3.3 via Groq, JSON
mode) end-to-end. See
[`playground/README.md`](playground/README.md#live-llm-agent-validation)
for the full execution model and how to add your own live scenario.

Run it locally:

```bash
cd playground
corepack enable   # activates the pinned pnpm
pnpm install
pnpm dev
```

## Repository layout

```
a2a-testbed/
├── pyproject.toml
├── README.md            (this file)
├── ARCHITECTURE.md      (the design)
├── CONTRIBUTING.md      (how to contribute)
├── LICENSE              (Apache 2.0)
├── src/a2a_testbed/
│   ├── core/            (types, loader, time controller, faults, observer)
│   ├── runtimes/        (python_inproc, python_subproc, go, nodejs, java, external)
│   ├── network/         (multitenant — sim mode; perprocess — realistic mode)
│   ├── transport/       (Transport protocol abstraction + A2ATransport)
│   ├── contracts/       (61 spec-derived A2A 1.0 conformance contracts: 58 transport + 3 network + runner)
│   ├── manifest/        (ExtensionManifest types, generator, store, validator)
│   ├── extensions/      (MCP delegation glue for richer semantic validation)
│   ├── vendors/         (AgentCard dialect framework + A2A native checker)
│   ├── scenario.py      (orchestrator: sim and realistic modes)
│   ├── reporter.py      (JSON, Markdown, SVG output)
│   ├── spec_meta.py     (A2A spec pin + coverage metadata)
│   └── cli/             (typer CLI)
├── agents/
│   ├── python-template/ (subprocess Python reference agent)
│   ├── go-template/     (subprocess Go reference agent)
│   ├── nodejs-template/ (subprocess Node.js reference agent)
│   └── java-template/   (placeholder; contract documented)
├── examples/
│   ├── agent-cards/three-party/  (3 example AgentCards)
│   └── scenarios/                (bundled YAML scenarios)
├── playground/          (Vite + React in-browser playground)
└── tests/
    ├── unit/            (loader, types, time, observer, faults, manifest)
    ├── integration/     (end-to-end scenario, MCP delegation)
    └── polyglot/        (cross-SDK; requires language toolchains)
```

## Concepts at a glance

**Scenario.** A YAML file that names agents and a flow of message
steps. Optional fault injection per step, virtual time advance, and
observer agents.

**Agent.** Identified by id, declared with an AgentCard JSON file
and a runtime kind. Default runtime is `python_inproc` (in the
orchestrator process); cross-SDK scenarios pick `go`, `nodejs`, or
`external`. (`java` is reserved — adapter exists but no reference
jar ships yet; see [`agents/java-template/`](agents/java-template/).)

**Mode.** A scenario picks one. `sim` (default) runs all agents in a
single Starlette server with path-prefix routing — fast, dev-friendly.
`realistic` spawns one process per agent — used for cross-SDK
conformance and production-topology validation.

**Runtime.** A polyglot adapter: `python_inproc`, `python_subproc`,
`go`, `nodejs`, `external`. Each adapter knows how to bring its
language's agent up, route the AgentCard JSON in, capture the ready
handshake, and tear down on scenario exit. (A `java` adapter is
scaffolded but inactive until a reference jar ships.)

**Fault.** Declared on a step. `drop`, `delay <ms>`, `corrupt`,
`http_error <status>`. Injected client-side so the agent under test
can't tell it's being faulted from the wire.

**Time controller.** Per-scenario virtual clock with explicit
`advance(seconds)`. Required for testing protocol TTLs and refresh
cadences without sleeping in the test.

**Observer.** An agent declared with `role: observer`. The runner
records every step against the observer's history; a semantic
validator can be plugged in for invariants like "audit trail is
complete" or "no behavioral drift detected across this scenario."

## Extension manifest convention

A2A 1.0 specifies `capabilities.extensions[]` with a `uri`, but does
not yet specify how a third-party validator should understand the
entry's payload. This testbed proposes a small convention: each
extension publishes a self-describing manifest at its URI.

```
GET <extension_uri>/manifest.json   →   ExtensionManifest (JSON Schema for the payload)
```

A generic validator can:

1. Read `capabilities.extensions[].uri` from the AgentCard
2. Fetch `<uri>/manifest.json`
3. Validate the entry's `params` against the manifest's JSON Schema
4. Report findings — without any protocol-specific code

The `manifest/` package contains the typed envelope, a generator that
builds a manifest from any pydantic model, a store abstraction
(in-memory / filesystem / HTTP / composite), a JSON-Schema validator,
and a markdown spec generator. The `playground/` app demonstrates the
same flow in pure browser JS via [`ajv`](https://ajv.js.org/).

The convention is experimental; it is not part of the A2A 1.0
specification.

## Cross-SDK polyglot example

```yaml
name: "polyglot interop"
mode: realistic

agents:
  - id: principal
    card: ./cards/alice.json
    runtime: python_inproc      # in the testbed
  - id: guardian
    card: ./cards/bob.json
    runtime: nodejs             # subprocess
    source: ./agents/nodejs-template/
  - id: provider
    card: ./cards/carol.json
    runtime: go                 # subprocess
    source: ./agents/go-template/

flow:
  - from: provider
    to: principal
    action: request_consent
  - from: principal
    to: guardian
    action: forward_consent
  - from: guardian
    to: provider
    action: grant_consent
```

Runs three agents in three different languages talking via real
HTTP+JSON-RPC. The Python subprocess path is validated end-to-end
in `tests/polyglot/`; Go and Node.js work the same way given their
toolchain on PATH.

## Other example scenarios

Bundled under `examples/scenarios/`:

| Scenario | Demonstrates |
|---|---|
| `three_party_consent.yaml` | 5-step three-party guardian-mediated flow across 3 in-process agents |
| `fault_injection.yaml` | Drop / delay / corrupt / synthetic HTTP error at the orchestrator's wire seam |
| `time_advance.yaml` | Virtual clock advanced explicitly between message steps for TTL / refresh testing |
| `observer_audit.yaml` | Observer agent receives every wire exchange via traffic taps |
| `polyglot_smoke.yaml` | Polyglot architecture demo (in-process Python; subprocess scenarios in `tests/polyglot/`) |
| `cloudflare_math_demo.yaml` | Live LLM-backed math agent on Cloudflare Workers (Llama 3.3 via Groq, JSON mode); semantic field-level assertions |
| `task_runner_demo.yaml` | Live A2A 1.0 task-runner agent at `tasks.a2a-testbed.com`; full Tasks / SSE / push lifecycle, pairs with `--probe-external` for the contract sweep |
| `three_party_governed.yaml` | The three-party flow with an ACS manifest attached (`acs:` field); per-step governance verdicts |
| `cloudflare_math_governed.yaml` | ACS runtime governance against the **live** Cloudflare math agent: DLP on the real request, error-check on the real response |

ACS manifests under `examples/acs/`: `email-agent.acs.yaml` (builtin),
`email-agent-rego.acs.yaml` (OPA/Rego), `dlp-evidence.acs.yaml` (evidence
provider), `three-party-governance.acs.yaml`, and
`cloudflare-math-governance.acs.yaml`. See [docs/ACS.md](docs/ACS.md).

## Project goals

- Be the test environment for protocol extensions on top of A2A.
- Catch cross-SDK conformance bugs that single-language tools can't
  see.
- Stay tiny — keep the value in the architecture, not the volume.

## Project non-goals

- **Not a single-agent debugger.** This tool operates at the network
  layer — message flow between cooperating agents — not at the
  internals of any one running agent.
- **Not a security scanner.** Adversarial input fuzzing and YARA-style
  pattern detection are out of scope.
- **Not a production runtime.** We test agents that already exist (or
  agents you spin up just for the scenario); we do not deploy them
  permanently.

## Status

Alpha. The CLI surface, scenario format, and manifest envelope may
change while the convention is being explored. Tests cover the core
runtime, the manifest layer, and one end-to-end scenario; cross-SDK
toolchains are exercised in `tests/polyglot/`.

## Related projects

| Project | What it does |
|---|---|
| [a2aproject/a2a-tck](https://github.com/a2aproject/a2a-tck) | Single-agent compliance validator. Local CLI, targets A2A v0.3.0. |
| [a2aproject/a2a-inspector](https://github.com/a2aproject/a2a-inspector) | Interactive debugger UI for one agent at a time. Local launch. |
| [a2aproject/a2a-samples](https://github.com/a2aproject/a2a-samples) | Reference sample agents in Python, JavaScript, Go, Java. |
| [A2A-StoryLab](https://github.com/A2A-StoryLab/A2A-StoryLab) | Educational multi-agent demo (Orchestrator + Creator + Critic). |

a2a-testbed targets A2A 1.0 and adds: multi-agent scenarios,
network fault injection, virtual time, the extension manifest
convention, and a hosted browser playground at
<https://a2a-testbed.com>.

The reference task-runner at
[`examples/hosted-agents/cloudflare-task-runner/`](examples/hosted-agents/cloudflare-task-runner/),
deployed at `https://tasks.a2a-testbed.com`, can also serve as the
SUT for an a2a-tck run:

```bash
git clone https://github.com/a2aproject/a2a-tck.git
cd a2a-tck
uv venv && source .venv/bin/activate && uv pip install -e .
./run_tck.py --sut-url https://tasks.a2a-testbed.com --category all
```

Some tests will fail because TCK enforces A2A v0.3.0 mandatory
surfaces (notably `tasks/list` pagination + filtering and
multi-transport equivalence) that this agent does not implement.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Issues and pull requests
welcome.

## License

Apache 2.0. See [`LICENSE`](LICENSE). Hosted playground:
[a2a-testbed.com](https://a2a-testbed.com).
