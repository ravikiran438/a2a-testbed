# Agent Control Specification (ACS) support

The testbed can load, validate, and evaluate **Agent Control
Specification (ACS)** manifests. ACS is an open, vendor-neutral standard
for *runtime governance* of AI agents: deterministic safety/security
controls placed at fixed checkpoints in an agent's lifecycle, expressed
as a portable YAML manifest that travels with the agent independent of
framework, runtime, or policy engine. It is part of Microsoft's
[Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit).

ACS is to guardrails what MCP is to tools and A2A is to agent-to-agent
messaging: one declarative contract any framework can adopt. This
testbed treats an ACS manifest as a first-class artifact alongside the
A2A AgentCard — validated **offline** (the Python CLI) and **online**
(the in-browser playground), with the same checks and the same verdicts
on both surfaces.

> ACS tracked here: **`0.3.1-beta`** (pinned in
> `a2a_testbed.acs.types.ACS_SPEC_VERSION`). Bump deliberately, the same
> way the A2A spec commit is pinned in `pyproject.toml`.

## Why it lives in a2a-testbed

The testbed already taps every inter-agent request/response pair as a
`WireExchange` (see `core/observer.py`) and already injects wire-level
faults (`core/faults.py`). Those two capabilities are exactly what an
ACS *control layer* needs to be exercised: a source of runtime context
to evaluate, and a way to make evidence/policy calls fail so you can
prove the layer denies rather than fails open.

## The eight intervention points and the A2A wire seam

ACS defines eight lifecycle checkpoints. The testbed operates at the A2A
*inter-agent* layer, not inside an agent's model loop, so it can observe
six of them directly from a wire exchange; the two model-call points
live inside an agent's process and are out of scope unless the agent
emits them itself.

| Intervention point | Observable at A2A wire seam? | Testbed mapping |
|---|---|---|
| `agent_startup`   | yes | synthetic snapshot from the AgentCard / boot |
| `input`           | yes | inbound `message/send` before the receiver acts |
| `pre_model_call`  | no  | inside the agent process — agent must emit it |
| `post_model_call` | no  | inside the agent process — agent must emit it |
| `pre_tool_call`   | yes | an A2A handoff, **remote agent as the tool** (name = receiver, args = params) |
| `post_tool_call`  | yes | the handoff result re-entering the caller's context |
| `output`          | yes | the response before it leaves the receiver |
| `agent_shutdown`  | yes | synthetic end-of-session snapshot |

The mapping is **version-agnostic by construction**: snapshots are
derived from the wire bodies as-is and never branch on the A2A protocol
version. The same manifest yields the same verdict whether the handoff
used A2A 1.0, 0.3, or a non-A2A transport. (A2A 1.0 is the testbed
default — see `[tool.a2a_testbed.spec]` in `pyproject.toml`.)

## Manifest format

```yaml
agent_control_specification_version: "0.3.1-beta"

metadata:
  name: "email-agent"

policies:
  email_policy:
    type: builtin            # 'builtin' (deps-free) or 'rego' (external backend)
    default_decision: allow
    rules:
      - name: deny-external-domain
        field: "policy_target.value.message.to"   # dotted path into canonical input
        op: endswith                               # equals/in/contains/endswith/exists/…
        value: "@external.example"
        decision: deny

intervention_points:
  pre_tool_call:
    policy_target: "$.tool_call.args"
    policy_target_kind: tool_args
    tool_name_from: "$.tool_call.name"
    policy: email_policy
    evidence:
      - recipient_classifier   # evidence-provider ids resolved on the evaluator

tools:
  send_email:
    type: Tool
    id: send_email
    clearance: internal
    security_labels: [internal]
```

A full worked example ships at
[`examples/acs/email-agent.acs.yaml`](../examples/acs/email-agent.acs.yaml).

### Policy backends

- **`builtin`** — a dependency-free, deterministic rule engine.
  Structured conditions (no expression `eval`), first-match-wins, with a
  `default_decision` otherwise. Lets the testbed exercise ACS end-to-end
  with no external services.
- **`rego`** — the ACS reference shape (Open Policy Agent). Register the
  bundled OPA backend and a `type: rego` manifest evaluates unchanged:

  ```python
  from a2a_testbed.acs import AcsEvaluator
  from a2a_testbed.acs.rego import register_rego_backend

  evaluator = AcsEvaluator(fail_closed=True)
  register_rego_backend(evaluator)        # uses `opa` on PATH
  ```

  The canonical policy input is passed to OPA as the `input` document, so
  a rule reads e.g. `input.policy_target.value.message.to`; the policy's
  `query` must return a decision string or `{decision, reasons, rule}`.
  Requires the OPA binary. With no backend registered (or OPA absent),
  evaluation **fails closed** (deny) — the safe default for a control
  layer. See [`examples/acs/email-agent-rego.acs.yaml`](../examples/acs/email-agent-rego.acs.yaml)
  and [`examples/acs/rego/email.rego`](../examples/acs/rego/email.rego).

### Canonical policy input

At each intervention point the evaluator shapes the host snapshot into
the ACS canonical input — `intervention_point`, `policy_target`,
`snapshot`, `annotations`, `tool` — the bridge between the agent runtime
and the policy engine. Rule `field` paths resolve against this object,
so a rule can read the snapshot, the resolved policy target, tool
metadata, or evidence annotations.

## Fail-closed semantics

The signature testbed check. When evidence collection, the policy
backend, or verdict processing raises, the evaluator returns `deny` with
`failed_closed=True` — never a silent `allow`. This pairs naturally with
fault injection: corrupt or error an evidence/policy call (the same way
`fault: http_error` corrupts a wire response) and assert the control
still denies. A control layer that fails *open* under those conditions
is a critical defect — exactly the gap ACS exists to close.

The `policy.acs_fail_closed.*` contract encodes this; the
`policy.acs_enforcement.*` contract proves the happy-path allow/deny.

## Running ACS against a scenario

ACS can be applied to **existing scenarios with no changes to the agents
or the flow** — every scenario step already produces a wire exchange,
which is exactly what ACS evaluates. The runner shapes each step into a
snapshot and evaluates the manifest's wire-observable intervention points
(`input` / `pre_tool_call` use the request; `post_tool_call` / `output`
use the response), recording a verdict per point.

Two attach mechanisms:

- **Scenario field** — declare `acs: <path>` in the scenario YAML
  (relative to the scenario file). Travels with the scenario, versioned.
  See [`examples/scenarios/three_party_governed.yaml`](../examples/scenarios/three_party_governed.yaml).
- **CLI flag** — `--acs <manifest>` applies a manifest to any scenario
  ad-hoc, overriding the scenario field. Non-invasive.

```bash
# scenario field
a2a-testbed run examples/scenarios/three_party_governed.yaml

# ad-hoc against the stock scenario (no edits to it)
a2a-testbed run --acs examples/acs/three-party-governance.acs.yaml \
  examples/scenarios/three_party_consent.yaml
```

The run prints a per-step verdict table (colored allow / warn / deny /
escalate) alongside the step and conformance tables, and the verdicts
are included in the JSON report.

### Record mode vs. enforce mode

By default ACS runs in **record mode**: verdicts are surfaced but the
flow proceeds — a `deny` tells you the control layer *would* have blocked
the action without changing the run.

**Enforce mode** makes verdicts binding. A `deny` or `escalate` is
evaluated *before the request is dispatched* (`input` / `pre_tool_call`),
blocks that handoff so it never goes out, fails the step, and halts the
remaining flow — mirroring a real control layer stopping a workflow at
the denied action. Turn it on with the `--acs-enforce` flag or the
`acs_enforce: true` scenario field (the flag wins):

```bash
a2a-testbed run --acs-enforce \
  --acs examples/acs/three-party-governance.acs.yaml \
  examples/scenarios/three_party_consent.yaml
# -> steps 0–1 run (warn/allow), step 2 (bob→carol) blocked, flow halts
```

### Against a live agent (real traffic)

For a `runtime: external` agent, ACS evaluates the **real** request the
runner sends and the **real** JSON-RPC response the deployed agent
returns — request-side points (`input` / `pre_tool_call`, with any
evidence providers) before dispatch, response-side points
(`post_tool_call` / `output`) against the actual response body. This is
the ACS analog of running the conformance sweep against a live
deployment.

```bash
# governs the live math agent (math.a2a-testbed.com): DLP on the outbound
# question, error-check on the real response.
a2a-testbed run examples/scenarios/cloudflare_math_governed.yaml
a2a-testbed run --acs-enforce examples/scenarios/cloudflare_math_governed.yaml
```

**Evidence providers.** Manifests can declare `evidence:` ids that run
before the policy and contribute facts into `annotations`. The runner
auto-registers the built-ins in `a2a_testbed.acs.evidence` (e.g.
`keyword_dlp`, a keyword + SSN/credit-card DLP classifier) when a manifest
references them; unknown ids fall back to a permissive no-op. A policy
then reads e.g. `annotations.dlp.flagged` — see
[`examples/acs/dlp-evidence.acs.yaml`](../examples/acs/dlp-evidence.acs.yaml).

In the **playground**, toggle **Preview ACS** in the Scenario tab (and
**Enforce ACS** beside it for binding mode). Each handoff is evaluated
in-browser (the TS evaluator, at parity with Python); verdicts color the
edges and appear in the Inspector. For a live (`runtime: external`) agent
the `output` verdict is computed from the agent's **real** response body,
not a placeholder. In enforce mode a blocking verdict stops the animation
and shows a "flow halted by ACS" banner. The demo manifest mirrors
`examples/acs/three-party-governance.acs.yaml`; author and validate your
own in the Validator tab.

## Validating a manifest — offline (CLI)

```bash
# install the package once
pip install -e ".[dev]"

# validate
a2a-testbed acs validate examples/acs/email-agent.acs.yaml

# CI gating: fail on warnings too
a2a-testbed acs validate examples/acs/email-agent.acs.yaml --strict
```

A valid manifest prints a green findings table and exits `0`; any
error-level finding exits `1`. From the repo without installing the
entry point: `PYTHONPATH=src python -m a2a_testbed.cli.main acs validate
<file>`.

### Authoring helpers: `acs init` and `acs spec`

```bash
# scaffold a starter manifest to edit (one checkpoint, a sample rule, a tool)
a2a-testbed acs init --name my-agent -o my-agent.acs.yaml

# render a plain-English governance summary for review / audit
a2a-testbed acs spec my-agent.acs.yaml -o ACS-SUMMARY.md
```

`acs spec` turns the manifest into Markdown — which checkpoints, which
policy, what each rule decides, evidence, and tools — serving ACS's
"auditable, not a black box" intent. There is deliberately **no
`generate`** command: an ACS manifest is authored governance intent, not
a mechanical projection of a data model the way an extension manifest's
JSON Schema is.

## Validating a manifest — online (playground)

Open the playground's **Validator** tab and switch to **ACS manifest**
(or click "Validate an ACS manifest" on the home page). Paste a manifest
and validate entirely in your browser — no backend. The browser
validator (`playground/src/acsValidator.ts`) mirrors the Python
validator's structural and semantic checks and emits the **same finding
kinds**, the same way the AgentCard validator mirrors its Python
counterpart. This is the testbed's "two surfaces, one source of truth"
discipline applied to ACS: a check added in one place must be added in
both.

## Findings

| Kind | Level | Meaning |
|---|---|---|
| `ok` | pass | manifest valid, no issues |
| `error_parse` | error | not valid YAML / not a mapping |
| `error_schema` | error | structural/type problems (with a per-field error list) |
| `error_policy_ref` | error | an intervention point references an undeclared policy |
| `error_no_intervention` | error | no intervention points — nothing to enforce |
| `warn_version_mismatch` | warn | manifest's ACS version differs from the pinned one |
| `warn_rego_backend_required` | warn | a `rego` policy needs an external backend, else fails closed |
| `warn_non_observable_point` | warn | a model-call point can't be observed at the A2A wire seam |
| `warn_tool_ref` | warn | `tool_name_from` set but the manifest declares no tools |

## Programmatic use

```python
from a2a_testbed.acs import (
    validate_manifest, AcsEvaluator, InterventionPoint, snapshot_for,
)
from a2a_testbed.core.observer import WireExchange

# validate
result = validate_manifest("examples/acs/email-agent.acs.yaml")
assert result.ok

# evaluate a wire exchange against the manifest
manifest = result.manifest
evaluator = AcsEvaluator(fail_closed=True)
evaluator.register_evidence("recipient_classifier", my_classifier)

exchange = WireExchange(
    receiver_id="send_email",
    request_body={"method": "message/send",
                  "params": {"message": {"to": "x@external.example"}}},
    response_body={"result": {}},
)
verdict = await evaluator.evaluate_exchange(
    manifest, InterventionPoint.PRE_TOOL_CALL, exchange,
)
print(verdict.decision, verdict.reasons)   # Decision.DENY, ['recipient address is outside the org']
```

## Module layout

| File | Responsibility |
|---|---|
| `src/a2a_testbed/acs/types.py` | manifest model, intervention points, decisions, canonical input, verdict |
| `src/a2a_testbed/acs/canonical.py` | `WireExchange` → snapshot/canonical-input (the wire seam) |
| `src/a2a_testbed/acs/evaluator.py` | fail-closed evaluator, builtin engine, evidence + backend registries |
| `src/a2a_testbed/acs/manifest.py` | local validator (structural + semantic findings) |
| `src/a2a_testbed/acs/rego.py` | OPA/Rego policy backend for `type: rego` manifests |
| `src/a2a_testbed/acs/evidence.py` | built-in evidence providers (e.g. `keyword_dlp`) |
| `src/a2a_testbed/contracts/policy/` | `acs_fail_closed`, `acs_enforcement` contracts (`ContractCategory.POLICY`) |
| `playground/src/acsValidator.ts` | browser validator, parity with `manifest.py` |
| `playground/src/acsEvaluator.ts` | browser evaluator, parity with `evaluator.py` |
| `examples/acs/*.acs.yaml` | worked manifests (email-agent, three-party-governance) |
| `examples/assert_integration/` | ASSERT `target.callable` wrapping an A2A agent + ACS |
| `tests/unit/test_acs.py` | validation, allow/deny, fail-closed, enforce, wire-seam parity |

## Status

Experimental / alpha. Implemented today: the manifest model, the local
validator (CLI + browser), the wire-seam mapping, the fail-closed
evaluator with a builtin engine, the policy contracts, per-step
evaluation wired into the `ScenarioRunner` + CLI (`--acs` / `acs:` field)
and the playground scenario view (Preview ACS), and **enforce mode**
(`--acs-enforce` / `acs_enforce:` field / playground Enforce toggle) that
blocks denied handoffs before dispatch and halts the flow.

ASSERT interop ships as a worked example
([`examples/assert_integration/`](../examples/assert_integration/)): an
ASSERT `target.callable` that drives a live A2A agent and hands per-turn
ACS verdicts to ASSERT's judge as evidence.

Verdicts now also render in the Markdown report (an ACS governance
section) and the SVG badge (amber when blocking verdicts are present),
and the ASSERT target emits OpenInference OTel spans. Rego policies
execute via the OPA backend (`a2a_testbed.acs.rego`), failing closed when
OPA isn't available.

## References

- [Introducing Agent Control Specification](https://commandline.microsoft.com/agent-control-specification-runtime-governance/)
- [Build 2026: open evals and a control standard](https://devblogs.microsoft.com/foundry/build-2026-open-trust-stack-ai-agents/)
- [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit)
