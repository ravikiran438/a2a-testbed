# A2A reference task runner (Cloudflare Workers)

A spec-compliant A2A 1.0 reference agent (also serving A2A 0.3) implementing the full 1.0
JSON-RPC method surface, with 1.0 ProtoJSON payloads (so the official
`a2a-sdk` 1.x clients interoperate unmodified):

- `SendMessage` (blocking by default; `configuration.returnImmediately: true` for async)
- `SendStreamingMessage` (SSE; each frame is a JSON-RPC response wrapping a `StreamResponse`)
- `GetTask`, `ListTasks` (filter by `contextId` / `status`, `pageSize` + `pageToken`), `CancelTask`
- `SubscribeToTask` (streams the task, then every update until it is terminal)
- `{Create,Get,List,Delete}TaskPushNotificationConfig`, plus inline
  `configuration.taskPushNotificationConfig` on `SendMessage`
- `GetExtendedAgentCard` (returns `-32007`; no extended card is published)

Errors use the 1.0 codes (`-32001` task not found, `-32002` not
cancelable, `-32004` unsupported operation, ...) with a
`google.rpc.ErrorInfo` entry in `error.data`. Version negotiation
follows A2A 1.0 §3.6.2: a 1.0 method must carry `A2A-Version: 1.0`
(an absent header means 0.3, which has no `SendMessage`, so it gets
`-32009` VersionNotSupported), and any request for a version this
agent does not serve gets `-32009` too.

### A2A 0.3 clients

The same URL serves A2A 0.3, and the AgentCard says so: it lists a
`"protocolVersion": "1.0"` JSONRPC interface first (preferred) and a
`"0.3"` one on the same URL. 0.3 callers (no `A2A-Version` header) use
the 0.3 method names and get 0.3 payloads — `kind` discriminators,
lower-case task states, bare Task/Message results, `kind:
"status-update"` / `"artifact-update"` stream events — exactly what the
a2a-sdk's own 0.3 client (`CompatJsonRpcTransport`) parses:

- `message/send`, `message/stream`
- `tasks/get`, `tasks/cancel`, `tasks/resubscribe`
- `tasks/pushNotificationConfig/{set, get, list, delete}`
- `tasks/list` (not part of 0.3; kept because earlier releases served it)

Tasks are stored in a version-neutral shape and rendered per request,
so a task created over 1.0 can be read over 0.3 and vice versa.
Webhooks follow the version the push config was registered with: a
1.0 config receives a `StreamResponse` (`{"task": ...}`, §4.3.3) with
the token in `X-A2A-Notification-Token`; a 0.3 config receives the bare
0.3 Task.

> Earlier releases answered the 0.3 method names with a hybrid shape
> (1.0 enum values, bare `{"task": ...}` SSE frames without a JSON-RPC
> envelope) that neither version's SDK accepts; that hybrid is gone.

The agent does no actual LLM work — it echoes the input back over
N artifact updates spaced 50ms apart, so it has no external API
dependency and runs on Cloudflare's free Workers tier. Its purpose
is to give the contract suite a known-conformant target for the
positive cases.

## Why this agent exists

Most contracts can verify violations against any agent (e.g. "does
the JSON-RPC envelope have the right fields?"). But the streaming,
subscribe, and push contracts need a positive-case target — an
agent that genuinely supports the surface — to validate that the
*correct* shape passes. This worker is that target.

The companion `cloudflare-push-receiver/` worker captures incoming
webhooks per probe-token so the `push_fires_on_completion`
contract can verify delivery end-to-end.

## Storage

A single global Durable Object (`TaskRunnerDO`) owns every task and
push config. All requests route to the same DO instance, which
holds state in transactional storage keyed by:

- `task:<id>` → Task object
- `push:<taskId>` → PushNotificationConfig[]

Each send writes the initial WORKING state on entry, one update per
work unit (so `GetTask` / `SubscribeToTask` see progress mid-flight),
and the COMPLETED state on finish. DOs serialize concurrent updates per instance,
so there are no consistency races between `GetTask` reading mid-flight
state and `processTaskWork` updating it.

`ListTasks` scans at most 500 stored tasks (legacy `tasks/list`: 50)
before filtering and sorting newest-first, to keep response times tight.

## Cost

| Service | Free tier | Paid tier ($5/mo Workers) |
|---|---|---|
| Worker requests | 100K/day | 10M included, then $0.30 / 1M |
| Durable Object requests | Not on free tier | 1M included, then $0.15 / 1M |
| Durable Object storage | Not on free tier | 1 GB included, then $0.20 / GB-month |

DOs require Workers Paid. There is no per-day write cap on DO
storage (only request rate limits per DO instance, which serialize
naturally). The previous design used KV and hit the free-tier
1K/day write quota during iterative testing — DO removes that wall
entirely.

## Deploy

```bash
cd examples/hosted-agents/cloudflare-task-runner
npm install
npx wrangler login
npx wrangler deploy   # the [[migrations]] block creates the DO class on first deploy
```

Then deploy the companion receiver so `push_fires_on_completion`
has a webhook target:

```bash
cd ../cloudflare-push-receiver
npm install
npx wrangler kv namespace create RECEIVED   # if not already created
# Paste id into wrangler.toml's [[kv_namespaces]] entry.
npx wrangler deploy
```

## Verify

```bash
# AgentCard
curl https://tasks.a2a-testbed.com/.well-known/agent-card.json

# SendMessage (A2A 1.0; blocks until the task completes)
curl -X POST https://tasks.a2a-testbed.com/a2a/v1/ \
  -H 'content-type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage",
       "params":{"message":{"messageId":"t1","role":"ROLE_USER",
       "parts":[{"text":"count: 3"}]}}}'

# SendStreamingMessage (SSE)
curl -N -X POST https://tasks.a2a-testbed.com/a2a/v1/ \
  -H 'content-type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendStreamingMessage",
       "params":{"message":{"messageId":"t2","role":"ROLE_USER",
       "parts":[{"text":"count: 3"}]}}}'

# A2A 0.3 client (no A2A-Version header) gets a 0.3 Task back
curl -X POST https://tasks.a2a-testbed.com/a2a/v1/ \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send",
       "params":{"message":{"messageId":"t3","role":"user",
       "parts":[{"kind":"text","text":"count: 3"}]}}}'
```

### Official SDK interop check

`sdk_interop_check.py` drives the agent through both official a2a-sdk
JSON-RPC clients — the 1.0 client and the SDK's 0.3 compatibility
client — which parse responses strictly, so any drift from either wire
format fails loudly:

```bash
pip install "a2a-sdk[http-server]>=1.2.2"
python sdk_interop_check.py                          # live endpoint
python sdk_interop_check.py http://127.0.0.1:8787    # against `wrangler dev`
```

## Run the conformance suite

```bash
# Standalone — just the agent under test (probes A2A 1.0, the card's
# preferred version)
a2a-testbed conformance https://tasks.a2a-testbed.com

# The same sweep over the agent's A2A 0.3 surface
a2a-testbed conformance https://tasks.a2a-testbed.com --protocol-version 0.3

# Or with the bundled scenario (matches the playground built-in)
a2a-testbed run --probe-external examples/scenarios/task_runner_demo.yaml

# Or via Justfile shortcuts:
just task-runner-demo
```

## Use as a SUT for a2aproject/a2a-tck

This agent can serve as the System Under Test for
[a2aproject/a2a-tck](https://github.com/a2aproject/a2a-tck):

```bash
git clone https://github.com/a2aproject/a2a-tck.git
cd a2a-tck
uv venv && source .venv/bin/activate
uv pip install -e .

./run_tck.py --sut-url https://tasks.a2a-testbed.com --category all
```

Or from the testbed root, assuming a2a-tck is checked out as a
sibling directory:

```bash
just tck-against-task-runner
```

Some tests fail because a2a-tck enforces A2A v0.3.0 mandatory
surfaces — multi-transport (gRPC + REST) equivalence among them —
that this JSON-RPC-only agent does not implement.

## License

Apache 2.0.
