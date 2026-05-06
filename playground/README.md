# a2a-testbed playground

**Hosted at [a2a-testbed.com](https://a2a-testbed.com)** — no install
required. The instructions below are for running it locally.

In-browser playground for the a2a-testbed. Four coordinated tools:

- **Multi-agent scenario** — a node-graph canvas (powered by
  [`@xyflow/react`](https://reactflow.dev/)) that animates message
  flow. Pick any built-in scenario from the dropdown, or paste your
  own CLI-format YAML. Click any node or edge to inspect AgentCards
  and message payloads.
- **Live LLM agent validator** — drive a real, deployed LLM-backed
  A2A agent from the browser. The bundled math-agent scenario
  POSTs A2A JSON-RPC to a live worker (Llama 3.3 via Groq, JSON
  mode) and evaluates each step's `expect` block against the
  actual HTTP response — the same checks the CLI runs. See
  [Live LLM agent validation](#live-llm-agent-validation) below.
- **A2A 1.0 conformance sweep** — when a scenario declares an
  agent with `runtime: external`, the playground exposes a
  user-paced sweep of the same 58 spec-derived transport
  contracts the CLI's `a2a-testbed conformance` command runs.
  Click **Run conformance** to fire the next batch; the panel
  shows pass / soft-pass / fail per row with the spec section
  cited. Source under [`src/conformance/`](src/conformance/).
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
- No analytics is loaded by default. The playground ships an
  opt-in analytics loader at
  [`src/CloudflareAnalytics.tsx`](src/CloudflareAnalytics.tsx) — a
  no-op when the build-time env var is unset, otherwise it injects
  a single `<script defer>`. Swap the script `src` for whichever
  privacy-respecting tracker your deployment uses
  ([Plausible](https://plausible.io), [Fathom](https://usefathom.com),
  [GoatCounter](https://www.goatcounter.com), etc.). See
  [`.env.example`](.env.example) for the env var pattern; `.env.*`
  files are git-ignored.

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
    ├── CustomScenarioPanel.tsx  # paste-your-own YAML loader
    ├── CloudflareAnalytics.tsx  # opt-in analytics loader (vendor-swappable)
    ├── scenario.ts           # bundled three-party scenario data
    ├── scenarioLoader.ts     # YAML → ActiveScenario adapter
    ├── builtins/             # registered built-in scenarios + their AgentCards
    ├── conformance/          # 58-contract A2A 1.0 transport sweep (TS port of CLI)
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

## License

Apache 2.0. See the [repository LICENSE](../LICENSE). Hosted at
[a2a-testbed.com](https://a2a-testbed.com).
