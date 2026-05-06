# Python subprocess agent template

Used by `runtime: python_subproc` in scenario YAML. Most scenarios use
`runtime: python_inproc` instead (faster, runs inside the orchestrator
process). This template exists for parity with the Go / Node.js / Java
subprocess adapters — useful when you want to validate the polyglot
runtime path with a Python agent that lives outside the orchestrator.

## Run standalone

```bash
python main.py \
  --agent-card ../examples/agent-cards/three-party/alice.json \
  --scripts /tmp/scripts.json \
  --port 9000
```

## Contract

The orchestrator passes:

- `--agent-card <path>` — AgentCard JSON file
- `--scripts <path>` — JSON object `{"action": "response", ...}`
- `--port <int>` — bind port (`0` = random; use `0` for testbed scenarios)

The agent must print exactly:

```
A2A_TESTBED_READY: http://127.0.0.1:<actual-port>
```

on stdout when its server is listening.

## Implementation notes

- Uses Python stdlib `http.server` (no external deps).
- Implements only `message/send`; other methods return JSON-RPC `-32601`.
- Substring + case-insensitive script match; falls back to a default ack.
