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

## [0.1.0a1]

- Initial alpha: multi-agent A2A scenario runner, polyglot runtimes
  (Python/Go/Node.js), fault injection, virtual time, observer pattern,
  58 A2A 1.0 conformance contracts, extension-manifest validation, and the
  in-browser playground.
