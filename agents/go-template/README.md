# Go subprocess agent template

Used by `runtime: go` in scenario YAML.

## Setup

Requires Go 1.22+. The bundled implementation has zero external
dependencies (uses `net/http` directly). If you upgrade to
`github.com/a2aproject/a2a-go`, run `go mod tidy`.

## Run standalone

```bash
go run . \
  --agent-card ../examples/agent-cards/three-party/alice.json \
  --scripts /tmp/scripts.json \
  --port 9000
```

## Contract

Same as the Python and Node.js templates — see `python-template/README.md`.

## Upgrading to a2a-go

The bundled implementation uses `net/http` directly. To swap in the
official SDK:

1. `go get github.com/a2aproject/a2a-go@latest`
2. Replace the handler functions with the SDK's server primitives.
3. The orchestrator contract (CLI flags, ready handshake) remains
   the same.
