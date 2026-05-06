# Node.js subprocess agent template

Used by `runtime: nodejs` in scenario YAML.

## Setup

Requires Node 20+. The bundled implementation has zero external
dependencies (uses `node:http` directly). If you upgrade to
`@a2a-js/sdk`, run `npm install` first.

## Run standalone

```bash
node index.js \
  --agent-card ../examples/agent-cards/three-party/alice.json \
  --scripts /tmp/scripts.json \
  --port 9000
```

## Contract

Same as the Python and Go templates — see `python-template/README.md`.

## Upgrading to @a2a-js/sdk

The bundled implementation uses Node's `node:http` directly. To swap
in the official SDK:

1. `npm install @a2a-js/sdk`
2. Replace the request handlers with the SDK's server primitives.
3. The orchestrator contract (CLI flags, ready handshake) remains
   the same.
