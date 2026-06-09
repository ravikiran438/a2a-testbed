# ASSERT × a2a-testbed × ACS

Drive a live **A2A** agent with **[ASSERT](https://github.com/microsoft/ASSERT)**'s
spec-driven evaluation pipeline while an **Agent Control Specification
(ACS)** manifest governs every turn. ASSERT generates adversarial test
cases; this target POSTs them to your A2A agent, evaluates each wire
exchange against an ACS manifest, and hands the verdicts back to ASSERT's
judge as evidence.

This closes the loop the Build 2026 announcement describes — *ASSERT
finds the failure, ACS places the control, ASSERT re-runs* — at the A2A
inter-agent layer.

```
ASSERT test case ──► a2a_acs_target.chat ──► POST A2A message/send ──► your agent
                          │                                                │
                          │  ◄───────────── response ──────────────────────┘
                          ▼
                 evaluate turn vs. ACS manifest
                          ▼
        "<final text>\n\n<acs_governance>… deny/allow …</acs_governance>"
                          ▼
                   ASSERT judge cites the verdicts
```

## How it works

`a2a_acs_target.py` exposes an ASSERT
[`target.callable`](https://github.com/microsoft/ASSERT/blob/main/docs/targets/callable.md):
`chat(message, history) -> str`. For each turn it:

1. builds an A2A `message/send` request from the ASSERT-generated message,
2. POSTs it to your agent (`A2A_TARGET_URL`),
3. shapes the request+response into ACS canonical input and evaluates the
   manifest's wire-observable intervention points (`input` / `pre_tool_call`
   on the request; `post_tool_call` / `output` on the response),
4. returns the agent's final text plus a compact `<acs_governance>` block
   listing the verdicts, which the judge scores against the rubric in
   `eval_config.yaml`.

The ACS evaluation reuses the exact same engine the CLI and playground
use, so verdicts here match `a2a-testbed acs ...` and the scenario runner.

**Multi-turn.** ASSERT drives up to `max_turns` per scenario. The target
sends the latest user turn (`history[-1]`) under a stable A2A `contextId`
derived from the conversation's opening message, so a stateful A2A agent
threads the turns together; the same id is set as `session.id` on the OTel
spans for trace grouping.

## Run it

From a checkout that has both this repo and ASSERT installed
(`pip install -e .` here, plus ASSERT per its getting-started):

```bash
# point at any deployed A2A 1.0 agent — e.g. the reference math worker:
export A2A_TARGET_URL="https://math.a2a-testbed.com"    # or tasks.a2a-testbed.com
export A2A_RECEIVER="math"                              # tool/agent id for snapshots
export ACS_MANIFEST="examples/acs/dlp-evidence.acs.yaml" # any ACS manifest
# plus your model creds, e.g. AZURE_API_KEY / AZURE_API_BASE

assert-ai run --config examples/assert_integration/eval_config.yaml
```

Inspect the artifacts ASSERT writes (taxonomy, test set, per-trace
verdicts with rationale, metrics) under its `artifacts/results/…` dir.

## Richer judge evidence (OTel traces)

The target already emits **OpenInference OpenTelemetry spans** when
`opentelemetry` is installed and a tracer provider is configured: an
`AGENT` span for the turn, a `TOOL` span for the A2A handoff (name +
input + output), and each ACS verdict as a span attribute
(`acs.<point>.decision`) plus an `acs.verdict` event. With no provider
configured the spans are no-ops — zero overhead, nothing to disable.

To have ASSERT's judge read them, uncomment the `target.trace` block in
`eval_config.yaml` (and install ASSERT's Phoenix extra). The judge then
cites the tool call and the per-checkpoint verdicts directly, not just
the `<acs_governance>` text. The text block remains as a fallback and
works with or without traces.

## Files

| File | Purpose |
|---|---|
| `a2a_acs_target.py` | the ASSERT callable: A2A POST + ACS evaluation + judge rendering |
| `eval_config.yaml` | ASSERT eval spec (governance behavior, dimensions, judge rubric) |
