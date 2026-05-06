# A2A math agent (Cloudflare Workers + Groq)

A minimal A2A 1.0 compliant agent that answers arithmetic and short
word-math problems via Groq's Llama 3.3 in JSON mode. Deployed as a
single Cloudflare Worker; runs on the free tier with zero cold start.

The agent is a deterministic JSON-emitter: every reply is a JSON
object of the form

```json
{ "answer": 4, "explanation": "Two plus two equals four." }
```

That makes it a clean target for end-to-end conformance testing —
the test runner can match exact fields without worrying about prose
variability.

## Cost

| Service | Free tier | Cost at demo scale |
|---|---|---|
| Cloudflare Workers | 100 K requests / day | $0 |
| Groq API (Llama 3.3 70B) | ~30 req/min, generous daily allowance | $0 |
| HTTPS / DNS | included | $0 |

Total: **$0** until you exceed Groq's per-minute quota or Workers'
daily request count.

## Prerequisites

1. A Cloudflare account (free).
2. A Groq API key — sign up at <https://console.groq.com/> and
   create a key (free).
3. Node.js 20+.

## Deploy

```bash
cd examples/hosted-agents/cloudflare-math
npm install

# Authenticate Wrangler with your Cloudflare account.
npx wrangler login

# Store the Groq API key as a Cloudflare secret (encrypted at rest;
# never checked in).
npx wrangler secret put GROQ_API_KEY
# (paste the key when prompted)

# Deploy. Wrangler prints the public URL on success.
npx wrangler deploy
```

You'll get back a URL like:

```
https://math.a2a-testbed.com
```

## Verify it works

```bash
# 1. AgentCard discovery
curl https://math.a2a-testbed.com/.well-known/agent-card.json

# 2. Round-trip a math question
curl -X POST https://math.a2a-testbed.com \
  -H 'content-type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "ROLE_USER",
        "parts": [{"kind": "text", "text": "What is 12 * 7?"}]
      }
    }
  }'
```

Expected: a JSON-RPC envelope whose `result.message.parts[0].text` is
the JSON string `{"answer": 84, "explanation": "..."}`.

## Test against the testbed

From the testbed root:

```bash
# Validate the published AgentCard against A2A 1.0 + any declared
# extensions.
a2a-testbed card https://math.a2a-testbed.com

# Run an end-to-end scenario that sends real math questions and
# checks the structured JSON response against expected values.
a2a-testbed run examples/scenarios/cloudflare_math_demo.yaml
```

The bundled scenario at `examples/scenarios/cloudflare_math_demo.yaml`
sends three arithmetic questions and asserts each response contains
the right `"answer": <number>` field.

## Local development

```bash
cp .dev.vars.example .dev.vars
# edit .dev.vars and paste your Groq API key
npx wrangler dev
```

Wrangler starts a local server at <http://localhost:8787>. Both the
AgentCard endpoint and the JSON-RPC endpoint work the same as in
production.

## Custom domain vs. `*.workers.dev`

`workers_dev = false` in `wrangler.toml` disables Cloudflare's
default subdomain so the worker only answers traffic from the
custom domain you bind to it. Hosting on a zone you control gives
you access to Cloudflare's full security toolkit (WAF rules, zone
rate limits, transform rules, analytics) — none of which apply on
`*.workers.dev`. If you fork this worker, swap the
`[[routes]]` block for your own hostname or remove it to fall
back to a `workers.dev` URL.

## Cost defenses (tunable)

The worker is a public LLM endpoint, so cost-control is on the
operator:

- **CORS origin allowlist** — edit `ALLOWED_ORIGINS` in
  `src/index.ts` to whichever origins your UI runs on. Server-side
  callers ignore CORS, so this is browser-only.
- **Per-IP rate limit** — the `MATH_RATE_LIMITER` binding in
  `wrangler.toml` (`simple = { limit, period }`) caps requests
  per IP. `period` accepts only `10` or `60`. Tune to your usage.
  Returns HTTP 429 + a JSON-RPC error envelope when tripped.
- **Cloudflare dashboard knobs** — Bot Fight Mode, WAF custom
  rules, and Turnstile are all configurable per-zone if you want
  defenses that apply before the worker is invoked.

What this worker deliberately doesn't do:

- **No shared-secret auth.** Any client-side token is public the
  moment the page loads. Real auth requires a server-side proxy
  or per-user issuance after sign-in — overkill for a public
  reference agent.
- **No prompt-content filtering.** The JSON-mode system prompt
  pins the output schema; off-topic inputs return
  `{"answer": null, ...}`. The rate limiter is the cost cap; the
  schema is the output cap.

## Operational notes

- **Free-tier limits.** Groq's free tier rate-limits at roughly
  30 requests/minute. If your demo gets a traffic spike, the worker
  will start returning JSON-RPC errors with code `-32000` and the
  Groq error message. For higher capacity, swap in a paid Groq plan
  or move the LLM call to Cloudflare Workers AI (free tier inside
  Cloudflare's allowance).
- **Model choice.** Default is `llama-3.3-70b-versatile` (most
  accurate for word problems). For lower latency, switch
  `GROQ_MODEL` in `wrangler.toml` to `llama-3.1-8b-instant`.
- **Determinism.** Temperature is pinned to 0 and JSON mode is
  enforced server-side. The same input produces the same JSON shape
  on every call. Numerical answers are stable for well-formed math;
  the `explanation` string can vary in wording (the test runner
  should match against `answer`, not the explanation).
- **Logs.** `npx wrangler tail` streams real-time logs from the
  deployed worker.

## Project layout

```
cloudflare-math/
├── package.json            # wrangler + types
├── tsconfig.json
├── wrangler.toml           # Worker config
├── .dev.vars.example       # Local-dev secret template
├── .gitignore
├── README.md               # this file
└── src/
    └── index.ts            # the entire worker (~250 lines)
```

## License

Apache 2.0 (matches the testbed root).
