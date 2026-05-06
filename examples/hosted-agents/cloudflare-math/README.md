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

## Custom domain instead of `*.workers.dev`

The worker is bound to `math.a2a-testbed.com`, not the default
`*.workers.dev` subdomain. This is deliberate — `workers.dev` lives
on Cloudflare's shared zone where customers can't add WAF rules,
zone-level rate limits, or custom transform rules. Routing through
a subdomain on a zone you own unlocks the full Cloudflare security
toolkit:

- Custom WAF rules (block by ASN, country, User-Agent regex, etc.)
- Zone-level rate limiting (more flexible than the binding here)
- Transform Rules / Cache Rules
- Per-route analytics

`workers_dev = false` in `wrangler.toml` disables the default
subdomain entirely so the only ingress is via the custom domain
where your zone-level rules apply.

### Recommended dashboard rules to add

Once the worker is deployed, in the Cloudflare dashboard for
`a2a-testbed.com`:

1. **Security → Bots → Bot Fight Mode: ON.** Free, blocks known
   scraper signatures before they reach the worker.
2. **Security → WAF → Custom rules → Add rule:**
   - Name: `block-non-browser-on-math`
   - Expression:
     `(http.host eq "math.a2a-testbed.com")
        and (cf.bot_management.score lt 30)
        and not (http.user_agent contains "a2a-testbed")`
   - Action: Block
   - Cuts off cheap automated scrapers without blocking the
     testbed's own conformance probes.
3. **Security → WAF → Rate limiting rules → Add:**
   - Name: `math-burst-limit`
   - Match: `http.host eq "math.a2a-testbed.com"`
   - Rate: 100 requests / 1 minute / IP
   - Action: Block (1 minute mitigation)
   - Layers on top of the per-Worker `MATH_RATE_LIMITER` binding.

These rules apply BEFORE the worker code runs, so a blocked
request doesn't burn a Worker invocation.

## Defending the LLM endpoint from rogue bots

The agent's URL is public and CORS doesn't stop server-side scrapers.
Three layers — applied in order of cost-to-add — keep the Groq token
budget under control:

1. **CORS origin allowlist (in this worker).** `corsHeaders()` only
   reflects an `access-control-allow-origin` header back to origins
   on the allowlist (`a2a-testbed.com`, dev `localhost`). Browsers
   on other domains can't proxy traffic through the worker. Edit
   `ALLOWED_ORIGINS` in `src/index.ts` if you fork this for your
   own deployment.

2. **Per-IP rate limit (in this worker).** The
   `MATH_RATE_LIMITER` binding declared in `wrangler.toml` caps any
   single IP at 30 LLM calls per 60 seconds via Cloudflare's
   built-in Rate Limiting API (free tier, no Durable Objects
   required). When tripped, the worker returns HTTP 429 with a
   JSON-RPC error envelope; legitimate users see "rate limit
   exceeded — try again in a minute," bots get throttled. Tune the
   `simple = { limit, period }` line in `wrangler.toml` to match
   your traffic. Per-period values are restricted to **10 or 60**
   seconds.

3. **Cloudflare dashboard knobs (no code changes).** The defenses
   below are toggled in the Cloudflare dashboard for the worker's
   route — they apply *before* your Worker code runs, so a blocked
   request doesn't burn an invocation:
   - **Bot Fight Mode** (Security → Bots): free, blocks known
     scraper signatures. Recommended on for any public LLM agent.
   - **WAF custom rules** (Security → WAF): block by ASN, country,
     or User-Agent if you see abuse pile up from one source.
   - **Cloudflare Turnstile** (Turnstile → Add site): free CAPTCHA
     replacement. If you ever expose this agent to a UI form, gate
     the request behind a Turnstile token to prove a human clicked.

What we deliberately *don't* do:

- **No shared-secret auth.** The playground is open-source and the
  bundle ships to every visitor; any token in the JS would be public
  the moment the page loads. Auth requires a server-side proxy
  (which defeats the "live demo" framing) or a per-user token issued
  after a sign-in flow (overkill for a side project).
- **No prompt-content filtering.** The system prompt pins the
  output schema; off-topic inputs get `{"answer": null, ...}`. We
  don't try to detect or block adversarial prompts beyond that —
  the rate limiter is the cost cap, and the JSON-mode constraint
  is the output cap.

If costs spike anyway: rotate the Groq API key, lower the
rate-limit `limit`, or temporarily set the `Bot Fight Mode` to
"super bot fight mode" while you investigate the Cloudflare
analytics tab to find the offending ASN/UA pattern.

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
