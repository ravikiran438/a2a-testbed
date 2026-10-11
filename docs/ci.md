# Running a2a-testbed in CI

Two checks, one tool:

| Check | Needs | Catches |
|---|---|---|
| `lint-card <file>` | the AgentCard JSON only | malformed cards: missing fields, duplicate skill ids, non-HTTPS URLs, bad version strings… (15 card contracts) |
| `conformance <url>` | a running agent | everything above plus the wire: version negotiation, JSON-RPC envelopes, error codes, tasks, streaming, subscribe, push (62 contracts) |

Both cite the A2A spec section for every row and share contract ids, so a
finding reads the same whether it came from the lint job or the live sweep.
The stories these features were built for are in
[consumer.md](consumer.md).

## GitHub Actions

### Sweep a preview deployment

```yaml
name: a2a-conformance
on: pull_request

permissions:
  contents: read
  security-events: write   # SARIF upload to code scanning (optional)

jobs:
  conformance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: deploy
        run: ./deploy-preview.sh   # however you deploy; output the URL
      - uses: ravikiran438/a2a-testbed@v0
        with:
          url: ${{ steps.deploy.outputs.preview_url }}
          card: agent-card.json    # optional: also lint the card file
```

### Start the agent inside the job

```yaml
      - run: |
          uv run uvicorn my_agent:app --port 8000 &
          for i in $(seq 1 60); do
            curl -fsS http://127.0.0.1:8000/.well-known/agent-card.json >/dev/null && break
            sleep 1
          done
      - uses: ravikiran438/a2a-testbed@v0
        with:
          url: http://127.0.0.1:8000
```

For a loopback agent the push-delivery contract uses a webhook receiver the
tool starts on `127.0.0.1` automatically, so the job needs no external
service. `wrangler dev` or `npm start` work the same way.

An agent in a Docker container (`docker run -p 8000:8000`, or a job
`services:` container) is reached on `127.0.0.1` too, but from inside the
container `127.0.0.1` is the container itself, so it cannot deliver to the
local receiver. Set `push-receiver: hosted` (or your own receiver URL) for
it; otherwise `transport.push_fires_on_completion` fails with "no webhook
fired".

### Lint the card on every PR

```yaml
      - uses: ravikiran438/a2a-testbed@v0
        with:
          card: agent-card.json
```

### Inputs

| Input | Default | Meaning |
|---|---|---|
| `url` | | Running agent to sweep (base URL, not the card path). |
| `card` | | AgentCard file to lint. Set `url`, `card`, or both. |
| `baseline` | `.a2a-conformance.yaml` | Accepted failures; used when the file exists. `none` ignores it. |
| `strict` | `false` | Soft-pass deviations (right behavior, wrong error code) fail too. |
| `protocol-version` | card's | Probe as `1.0` or `0.3`. |
| `push-receiver` | `auto` | `auto`, `local`, `hosted`, `off`, or a receiver URL. |
| `timeout` | `45` | Seconds per contract before it counts as an error. |
| `retries` | `1` | Re-runs for a contract whose agent did not answer. |
| `fail-on-errors` | `true` | Fail on exit 3 (agent did not answer some checks). `false` tolerates a flaky preview. |
| `sarif-location` | `card`, else `agent-card.json` | Repository file the code-scanning findings attach to. |
| `sarif-category` | per check | Code-scanning category prefix; give each agent its own when one workflow checks several (a matrix), or their alerts replace each other. |
| `upload-sarif` | `true` | Upload to code scanning. Needs `security-events: write`; a failed upload never fails the step. |
| `package` | this action's checkout | Where to install from, e.g. `a2a-testbed==0.2.0`. |
| `python-version` | `3.12` | Python for the tool. |

Outputs: `exit-code` and `report-dir` (holding `results.json`,
`results.sarif`, `results.xml`, `summary.md`, and `lint.*` for a card
lint). Every run also writes the Markdown summary to the job page.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Conformant: every contract passed, was skipped as not applicable, or is accepted by the baseline. |
| `1` | A contract failed: the agent answered and the answer breaks a rule. With `--strict`, deviations count. |
| `3` | No failures, but the agent did not answer some checks even after a retry (timeouts, dropped connections). Not a conformance verdict. |
| `2` | Usage error (bad flag, malformed baseline) or the agent could not be reached at all. |

A row's result is one of `pass`, `warn` (passed with a deviation), `skip`
(rule does not apply, e.g. capability not advertised), `fail`, `error`
(no answer), or `accepted` (failing, but listed in the baseline).

## Baseline: accepted failures

Adopt the gate before everything is green. Generate a starter file from
one sweep, then give every entry a reason:

```bash
a2a-testbed conformance https://agent.example --write-baseline .a2a-conformance.yaml
```

```yaml
version: 1
accepted:
  - contract: transport.push_fires_on_completion
    reason: Push delivery ships with the queue migration.
    owner: "@platform-team"     # optional
    expires: 2026-12-31         # optional; enforced again after this date
```

- The file is rejected while any `reason` is empty.
- Accepted rows still appear in every report, marked accepted, with the
  reason. In SARIF they are suppressed findings, not missing ones.
- An entry whose contract now passes is reported as stale so it gets
  deleted. An expired entry stops applying.
- `lint-card` and `conformance` read `.a2a-conformance.yaml` from the
  working directory by default; `--baseline PATH` or `--baseline none`
  override it.

## Any other CI

The CLI is the whole tool; the Action only wraps it.

```bash
uvx a2a-testbed lint-card agent-card.json -o card.xml
uvx a2a-testbed conformance "$AGENT_URL" -o results.xml -o results.json
```

| Flag | Purpose |
|---|---|
| `--format table\|json\|junit\|sarif\|markdown` | What goes to stdout (default `table`). |
| `-o PATH` (repeatable) | Write a report; format from the extension: `.json`, `.xml` (JUnit), `.sarif`, `.md`. |
| `--baseline PATH` / `--write-baseline PATH` | Use / generate a baseline. |
| `--only CONTRACT_ID` (repeatable) | Run a subset of the live sweep. |
| `--timeout`, `--retries` | Per-contract time limit and retries for unanswered checks. |
| `--push-receiver` | As the Action input above. |
| `--sarif-location`, `--sarif-category` | Repository file findings attach to; code-scanning category. |
| `--no-step-summary` | Do not append to `$GITHUB_STEP_SUMMARY`. |

GitLab example:

```yaml
a2a-conformance:
  image: ghcr.io/astral-sh/uv:python3.12-bookworm-slim
  script:
    - uvx a2a-testbed conformance "$PREVIEW_URL" -o results.xml
  artifacts:
    when: always
    reports:
      junit: results.xml
```

## Push receivers

`transport.push_fires_on_completion` registers a webhook with the agent and
waits for the delivery, so it needs a receiver the agent can reach:

- `auto` (default): `local` for an agent on `localhost`/`127.0.0.1`,
  `hosted` otherwise. An `A2A_TESTBED_PUSH_RECEIVER` environment variable
  takes precedence.
- `local`: an in-process receiver on `127.0.0.1`. Not reachable from an
  agent inside a Docker container; use `hosted` or a URL for those.
- `hosted`: the public receiver at `push.a2a-testbed.com`, for remote
  agents.
- a URL: your own receiver serving `POST /webhook/<token>` and
  `GET /received/<token>` (the sources of the hosted one are in
  `examples/hosted-agents/cloudflare-push-receiver/`).
- `off`: skip push delivery.

If the receiver cannot be reached, the contract is skipped with the reason
rather than failed: a broken test rig is not evidence against the agent.
