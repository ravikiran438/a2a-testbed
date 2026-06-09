# Contributing

Thanks for considering a contribution.

## Setup

```bash
git clone https://github.com/ravikiran438/a2a-testbed.git
cd a2a-testbed
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Optional polyglot toolchains needed only if you change the
corresponding adapter:

- Go 1.22+ for the `go` runtime adapter
- Node.js 20+ for the `nodejs` runtime adapter
- JDK 21+ for the `java` runtime adapter

## Layout convention

- Spec / design changes → `ARCHITECTURE.md`
- Implementation → `src/a2a_testbed/`
- Reference agents → `agents/<lang>-template/`
- Sample AgentCards / scenarios → `examples/`
- Tests → `tests/{unit,integration,polyglot}/`

## Pull request expectations

- Tests pass (`pytest`); polyglot tests skip cleanly when their
  toolchain isn't installed
- Public APIs have type hints
- One logical change per PR; aim for small, reviewable diffs
- New runtime adapters follow the `subprocess_base.SubprocessRuntimeBase`
  contract and document their CLI flags + ready handshake

## Adding a new runtime adapter

1. Add a new `runtimes/<name>.py` subclassing
   `SubprocessRuntimeBase`. Set `binary_check`, `binary_hint`, and
   `cmd_template`.
2. Add a reference agent under `agents/<lang>-template/` that:
   - reads `--agent-card`, `--scripts`, `--port`
   - prints `A2A_TESTBED_READY: <url>` on stdout when listening
   - serves AgentCard at `/.well-known/agent-card.json`
   - implements `message/send` JSON-RPC at the root path
3. Wire it into `RuntimeKind` (in `core/types.py`) and the runtime
   factory (in `scenario.py`).
4. Add a polyglot smoke test under `tests/polyglot/` marked with
   `@pytest.mark.skipif(shutil.which(...))`.
5. Document the install steps in the agent template's README.

## Adding a new fault kind

1. Extend `FaultKind` in `core/types.py`.
2. Implement the new branch in `core/faults.apply_fault`.
3. Add unit tests in `tests/unit/test_faults.py`.
4. Document the kind in the README's "Fault" section.

## Adding a new conformance contract

Contracts live under `src/a2a_testbed/contracts/transport/` (wire-level
invariants), `network/` (multi-agent flow invariants), or
`extensions/` (semantic invariants delegated to a protocol's MCP
server). Each contract is a small dataclass describing the
invariant plus an async run callable. See
`src/a2a_testbed/contracts/base.py` for the base types and the
existing `transport/` directory for sample contracts. Cite the A2A
spec section the contract derives from in its docstring — the
report writer extracts the `Spec:    A2A 1.0 §<n>` line at runtime
to render the per-step "Spec §" column.

## Tracking the upstream A2A spec

The A2A specification is governed by the LF AI & Data Foundation
and lives at <https://github.com/a2aproject/A2A>. Our contracts
are derived from a **specific commit** of that repo, pinned in
`pyproject.toml` under `[tool.a2a_testbed.spec]`:

```toml
[tool.a2a_testbed.spec]
name = "A2A"
version = "1.0"
commit = "<full-40-char-sha>"
last_reviewed = "<YYYY-MM-DD>"
source_repo = "https://github.com/a2aproject/A2A"
specification_path = "docs/specification.md"
```

`a2a-testbed coverage` reads this block and tells the user which
spec commit the contracts are derived against; `a2a-testbed run`
cites the commit short-SHA in the compliance section header. The
pin is intentional — bumping it without a contract sweep risks
shipping stale conformance claims.

### Quarterly review checklist

Schedule: **every three months**, or sooner if A2A cuts a minor
version. The review takes ~1–2 hours.

1. **Diff upstream against the pin.** From a local A2A clone:
   ```bash
   cd /path/to/A2A
   git fetch origin
   git log --oneline <pinned-sha>..origin/main -- docs/specification.md
   ```
   If the log is empty, you're up-to-date — bump
   `last_reviewed` to today's date and stop.

2. **Read the diff.** For each commit that touched
   `docs/specification.md`:
   ```bash
   git show <commit> -- docs/specification.md
   ```
   Look specifically for new `MUST` / `SHALL` / `REQUIRED` clauses,
   removed clauses, and section renumbering.

3. **For each changed clause:**
   - If a contract already covers the section: open the contract
     file, re-read the docstring `Clause:` line against the new
     spec text, update the paraphrase if needed, re-run
     `pytest tests/unit/test_contracts.py`.
   - If the section is new and no contract covers it: open an
     issue tagged `contract-gap` with the section number and a
     one-paragraph clause summary. (Don't write the contract
     during the review — keep the review fast.)
   - If a section was *removed*: mark the corresponding contract
     deprecated; don't delete it the same day (someone may still
     be running an older spec version).

4. **Catch up `CATALOG.md`.** Update the coverage table in
   `src/a2a_testbed/contracts/CATALOG.md` if the count of
   implemented vs. roadmap contracts changed.

5. **Bump the pin.** Update `commit` to the latest reviewed SHA
   and `last_reviewed` to today's date in `pyproject.toml`.
   Commit with `chore(spec): bump A2A pin to <short-sha>` — the
   PR description should list every clause that was reviewed.

6. **Re-run the contract suite end-to-end.**
   ```bash
   pytest tests/unit/test_contracts.py
   a2a-testbed run examples/scenarios/three_party_consent.yaml
   a2a-testbed coverage
   ```
   `coverage` should show the new pin in its header.

If you discover a clause the testbed currently misreports as
passing — i.e. an agent satisfies our contract but the new spec
text says it shouldn't — file the bug as `contract-bug` rather
than `contract-gap`; that's a higher-priority fix.

### When NOT to bump the pin

- A2A pre-release branches or RC tags: stay on the last cut
  release commit. The testbed claims conformance against
  *published* spec text, not draft text.
- Cosmetic-only commits (typos, formatting) — feel free to bump
  but don't claim a re-sweep happened in the PR description.

## Tracking the ACS spec

The testbed also supports the **Agent Control Specification (ACS)**,
part of Microsoft's
[Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit).
The ACS revision the manifest model + validator track is pinned in
`a2a_testbed.acs.types.ACS_SPEC_VERSION` (currently `0.3.1-beta`) and
mirrored on the TypeScript side in `playground/src/acsValidator.ts` and
`acsEvaluator.ts`.

When bumping it:

1. Update `ACS_SPEC_VERSION` in `acs/types.py` **and** both TS files.
2. Reconcile the manifest model / validator findings / evaluator ops
   with any spec changes (a new intervention point, op, or field).
3. Run `pytest tests/test_browser_parity.py` — it fails if the Python
   and TypeScript registries drift apart, so it will catch a one-sided
   edit.

ACS is `0.x` and pre-GA; expect more churn here than in the A2A pin.

## License

By contributing, you agree your work is licensed under Apache 2.0.

## Questions

Open an issue at <https://github.com/ravikiran438/a2a-testbed/issues>.
