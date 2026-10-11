# Consumer stories: a2a-testbed in CI

Written before the code. Each story is a person with five minutes and a
specific outcome; if a story stops being true, the feature is broken
even when the tests are green.

## 1. "My card said 1.0, my server spoke 0.3"

**Who:** Priya maintains an A2A agent on Cloudflare Workers. A user just
filed an issue: the card advertises `protocolVersion: 1.0` but
`SendMessage` returns `MethodNotFoundError`.

**Five minutes:** she adds one step to the workflow that already deploys
a preview:

```yaml
- uses: ravikiran438/a2a-testbed@v0
  with:
    url: ${{ steps.deploy.outputs.preview_url }}
```

**What she sees:** the PR check goes red. The job summary has one row
marked ✗, `transport.advertised_version_served`, citing A2A 1.0 §3.6.2
and saying the agent answered `message/send` but not `SendMessage`. The
same finding appears inline under the repository's code-scanning tab.
She fixes the router, pushes, and the check goes green.

**Exit:** the drift that reached a user last time is caught on the PR
that introduces it.

## 2. "We are not 100% green, and that is fine for now"

**Who:** Marcus's team runs an agent that deliberately omits push
notifications on one interface and still returns `-32601` instead of
`-32003` for one capability check. They want the gate for everything
else today.

**Five minutes:** he runs the sweep once locally with
`--write-baseline .a2a-conformance.yaml`, edits the generated file to
give each accepted failure a reason and an owner, and commits it.

**What he sees:** CI passes with the two known failures listed as
"accepted (baseline)" with their reasons. When someone fixes one, the
summary flags the baseline entry as stale so it gets deleted. When a
*new* contract fails, CI goes red as usual.

**Exit:** a team adopts the gate without first fixing everything, and the
exceptions stay visible and justified instead of silently ignored.

## 3. "Check the card before anything is running"

**Who:** Aisha edits `agent-card.json` in a PR. No server runs in that
job.

**Five minutes:** she adds `uvx a2a-testbed lint-card agent-card.json`
to the lint job.

**What she sees:** a duplicate skill id and an `http://` interface URL
are flagged in under a second, with the same contract ids and spec
sections the live sweep uses.

**Exit:** the card mistakes that a live sweep would catch are caught at
lint time, with identical wording.

## 4. "The network blipped; that is not a conformance bug"

**Who:** Priya again, a week later. The preview deployment was cold and
one request timed out.

**What she sees:** the sweep retried that contract once and it passed.
Had it timed out twice, the row would read **error** ("agent did not
respond within 45s"), not **fail**, and the run would exit `3` instead
of `1`, so her workflow can choose to tolerate unreachable-agent errors
while still failing on wrong answers.

**Exit:** a flaky network never reads as "your agent violates the spec".

## 5. "My agent runs inside the CI job"

**Who:** Leo starts his agent with `uvicorn` in the job and sweeps
`http://127.0.0.1:8000`.

**What he sees:** push-notification contracts run against a webhook
receiver the CLI starts on localhost automatically. Nothing reaches the
hosted receiver, and nothing needs internet access beyond installing the
tool. Against a remote agent with no reachable receiver, the push
delivery contract *skips* with a reason instead of failing.

**Exit:** a self-contained CI job gets full coverage with no external
service in the loop.
