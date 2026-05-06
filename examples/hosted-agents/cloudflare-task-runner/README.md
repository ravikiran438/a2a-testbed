# A2A reference task runner (Cloudflare Workers)

A spec-compliant A2A 1.0 reference agent implementing every method
the conformance contract suite probes:

- `message/send` (synchronous + `configuration.blocking: false` async)
- `message/stream` (SSE)
- `tasks/get`, `tasks/list`, `tasks/cancel`, `tasks/resubscribe`
- `tasks/pushNotificationConfig/{set, get, list, delete}`

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

Each `message/send` writes 1–2 keys (initial WORKING state on entry,
COMPLETED on finish). DOs serialize concurrent updates per instance,
so there are no consistency races between `tasks/get` reading mid-flight
state and `processTaskWork` updating it.

The list endpoint bounds enumeration to 50 newest entries to keep
response times tight.

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

# Synchronous send (blocking=true, default)
curl -X POST https://tasks.a2a-testbed.com/a2a/v1/ \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send",
       "params":{"message":{"messageId":"t1","role":"user",
       "parts":[{"kind":"text","text":"count: 3"}]}}}'

# SSE streaming
curl -X POST https://tasks.a2a-testbed.com/a2a/v1/ \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/stream",
       "params":{"message":{"messageId":"t2","role":"user",
       "parts":[{"kind":"text","text":"count: 3"}]}}}'
```

## Run the conformance suite

```bash
# Standalone — just the agent under test
a2a-testbed conformance https://tasks.a2a-testbed.com

# Or with the bundled scenario (matches the playground built-in)
a2a-testbed run --probe-external examples/scenarios/task_runner_demo.yaml

# Or via Justfile shortcuts:
just task-runner-demo
```

## License

Apache 2.0.
