# a2a-testbed playground

**Hosted at [a2a-testbed.com](https://a2a-testbed.com)** — no install
required. The instructions below are for running it locally.

In-browser playground for the a2a-testbed. Three coordinated tools:

- **Multi-agent scenario** — a node-graph canvas (powered by
  [`@xyflow/react`](https://reactflow.dev/)) that animates message
  flow. Pick any built-in scenario from the dropdown, or paste your
  own CLI-format YAML. Click any node or edge to inspect AgentCards
  and message payloads.
- **Live LLM agent validator** — drive a real, deployed LLM-backed
  A2A agent from the browser. The bundled "Cloudflare math agent"
  scenario POSTs A2A JSON-RPC to a live Cloudflare Worker (Llama 3.3
  via Groq, JSON mode) and evaluates each step's `expect` block
  against the actual HTTP response — the same checks the CLI runs.
  See [Live LLM agent validation](#live-llm-agent-validation) below.
- **AgentCard validator** — paste an AgentCard JSON and validate its
  declared `capabilities.extensions[]` payloads against the live
  JSON-Schema manifests published at each extension's URI. Pure
  browser-side via [`ajv`](https://ajv.js.org/); no backend.

## Live LLM agent validation

For scenarios where one or more agents declare `runtime: external`
with a `url:`, the playground makes **real HTTP calls** instead of
the animation-only path. The execution model:

1. The playground builds an A2A 1.0 JSON-RPC `message/send` envelope
   from the step's `message:` text.
2. It POSTs the envelope to `<agent.url>/a2a/v1/`.
3. It evaluates the step's `expect` block against the raw response:
   - `response_status: '2xx'` (or an exact code) — checked against
     the HTTP status.
   - `response_contains: '<substring>'` — literal substring match
     against the raw response body. Same matcher semantics as the
     CLI runner (`a2a-testbed run`).
4. The Inspector renders per-check ✓/✗ with the actual response
   body (first 400 chars), so failures are diagnosable in place.

### Bundled live scenario: Cloudflare math agent

Open the playground, switch to **Scenario** mode, and pick
**"Cloudflare math agent (live LLM) — live HTTP"** from the dropdown
above the canvas. A green banner appears confirming the run will hit
a real deployment (`https://math.a2a-testbed.com`).
Click **Run scenario**. Three steps fire in sequence; each sends a
math question, the worker calls Llama 3.3 in JSON mode, and the
playground checks the response shape (`"answer": <N>`) against the
expected number.

The same scenario file (`examples/scenarios/cloudflare_math_demo.yaml`)
runs identically through the CLI: `just math-demo`.

### Adding your own live scenario

1. Drop a YAML in `examples/scenarios/`. Declare each external agent
   with `runtime: external` and a `url:` field.
2. Drop the AgentCards in `examples/agent-cards/<group>/`.
3. Register the scenario in `playground/src/builtins/index.ts` —
   one Vite `?raw` import per file, append to `BUILTIN_SCENARIOS`.

The dropdown renders new entries automatically.

## Run locally

```bash
npm install
npm run dev      # http://localhost:5173/
npm run build    # static dist/ ready to host on any static-file CDN
```

## Privacy and persistence

- **Validator textarea content is saved to your browser's
  `localStorage`** under `a2a-testbed.playground.validator.card_v1`.
  This lets you keep working on a card across reloads. **Use the
  "Clear saved" button** to remove it; the data never leaves your
  machine.
- **Manifests are fetched over HTTPS** from each declared extension
  URI when you click *Validate*. The browser caches them per session
  via `manifestCache` in `validator.ts`.
- No analytics is loaded by default. To enable Cloudflare Web
  Analytics on your hosted deployment, see below.

## Cloudflare Web Analytics (optional)

Privacy-respecting, cookie-less, GDPR/CCPA-friendly. Off by default;
opt-in per build.

1. Create a free Web Analytics site at
   <https://dash.cloudflare.com> → Analytics → Web Analytics → Add
   site.
2. Copy the site token from Cloudflare's snippet.
3. Set `VITE_CF_ANALYTICS_TOKEN` either as a build-time env var or in
   `.env.production`:

   ```bash
   cp .env.example .env.production
   # edit .env.production to fill in VITE_CF_ANALYTICS_TOKEN
   npm run build
   ```

   The `.env.*` files are git-ignored; the token isn't a secret per
   Cloudflare's docs but doesn't need to live in source.
4. In dev (`npm run dev`) the token stays unset, so analytics never
   fires while you're working locally.

The integration lives in `src/CloudflareAnalytics.tsx` (mounts a
single `<script defer>` once). When `VITE_CF_ANALYTICS_TOKEN` is
empty, the component is a no-op.

## Project layout

```
playground/
├── README.md
├── .env.example
├── package.json
├── index.html
├── vite.config.ts
├── tsconfig.*.json
└── src/
    ├── App.tsx               # mode router + persistent header / footer
    ├── HomePage.tsx          # landing page
    ├── AgentNode.tsx         # custom xyflow node
    ├── Inspector.tsx         # side-panel inspector
    ├── ValidatePanel.tsx     # AgentCard validator UI
    ├── CloudflareAnalytics.tsx  # opt-in analytics loader
    ├── scenario.ts           # hardcoded three-party scenario data
    ├── validator.ts          # manifest fetch + ajv validation
    ├── App.css               # all UI styles
    ├── index.css             # base reset
    └── main.tsx              # entrypoint
```

## SEO and crawler files

`public/robots.txt` and `public/sitemap.xml` ship with the static
build (`vite copy public/` happens at build time). The site is a
single-page app at `https://a2a-testbed.com/`, so the sitemap has
exactly one entry and `robots.txt` allows all well-behaved
crawlers with a `Crawl-delay: 5`.

Page-level SEO lives in `index.html`:

- `<link rel="canonical">` pinning the canonical domain.
- OpenGraph + Twitter Card meta for link-preview cards.
- A `SoftwareApplication` + `WebSite` JSON-LD block so search
  engines render rich-result tiles (free tool, browser-based,
  Apache 2.0, GitHub repo).

## Bot protection

The playground itself is static HTML/JS — there's nothing to abuse
on the playground origin. The defendable surface is the **live LLM
agent** at `https://math.a2a-testbed.com/` that the
"Cloudflare math agent" scenario calls into. Three layers protect
the Groq token budget:

1. **CORS origin allowlist** in the Worker — only requests from
   `a2a-testbed.com` (and dev localhost) get the
   `access-control-allow-origin` header reflected back; browsers
   on other domains can't proxy traffic.
2. **Per-IP rate limit** via Cloudflare's built-in Rate Limiting
   binding (`MATH_RATE_LIMITER` in `wrangler.toml`) — 30 calls per
   60 seconds per IP. Bots get 429 with `retry-after: 60`.
3. **Cloudflare dashboard knobs** (Bot Fight Mode, WAF, Turnstile)
   for cases where the per-IP limit isn't enough.

CORS only stops *browser* abuse; CLI bots ignore it, so the rate
limiter is the layer that actually caps spend. Full details and
tuning notes:
[`examples/hosted-agents/cloudflare-math/README.md`](../examples/hosted-agents/cloudflare-math/README.md#defending-the-llm-endpoint-from-rogue-bots).

## License

Apache 2.0. See the [repository LICENSE](../LICENSE). Hosted at
[a2a-testbed.com](https://a2a-testbed.com).
