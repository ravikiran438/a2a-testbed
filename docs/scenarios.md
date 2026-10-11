# Scenario expectations

Each send step can carry an `expect:` block. The step passes only when
every expectation in it holds.

```yaml
expect:
  response_status: "2xx"          # '2xx', '4xx', '5xx' or an exact status
  response_contains: "approved"   # substring of the response body
  extensions:                     # extension semantics, checked on MCP servers
    "<extension URI>": {tool: ..., args: {...}, verdict: ok}
```

Unknown keys (in `expect:`, in a step, or at the top of the scenario)
are rejected when the scenario loads, so a misspelt or mis-indented
expectation cannot pass silently.

## Extension checks

HTTP expectations prove a message was delivered. `expect.extensions` asks
an extension's own MCP server whether the interaction obeyed that
extension's rules. The testbed has no built-in knowledge of any
extension: the URI is looked up in the configured MCP delegates, the
server is started over stdio, and the named tool is called.

```yaml
mcp_delegates: ../mcp-delegates.yaml        # file (relative to the scenario) or inline list

flow:
  - from: carol
    to: alice
    action: deliver
    message: "deliver: follow-up call at 19:00"
    expect:
      response_status: "2xx"
      extensions:
        "https://ravikiran438.github.io/sauvidya-pace/v1":
          tool: validate_time_window
          args:
            contract: {...}
            current_time_hhmm: "19:00"
          verdict: violation
```

Each check has:

| Field | Meaning |
|---|---|
| `tool` | Tool on the extension's MCP server. |
| `args` | Tool arguments, passed as given. |
| `verdict` | What the step must get back (default `ok`). |

Verdicts:

| Verdict | The tool answered |
|---|---|
| `ok` | `{"ok": true, ...}` |
| `violation` | `{"ok": false, ...}`: it ran the check and the rule was broken |
| `rejected` | an error result (`isError`): typically invalid arguments, or a protocol that signals a failed check by raising |

`violation` and `rejected` are deliberately different: a call with
malformed arguments must not count as the violation the scenario expects.

A URI can carry a list of checks; every one must hold. An empty list or
an empty `extensions:` block is a load error.

The step **fails closed**. Each of these fails it, with the URI and tool
in the detail:

- the verdict differs from the expected one;
- no delegate is configured for the URI;
- the server command is not found, the server exits or does not answer
  within 60 seconds;
- the server does not offer the tool;
- the answer is not a JSON object whose `ok` is `true` or `false`.

Extension checks run only on `send` steps (anywhere else is a load error)
and only after the HTTP expectations of the step have held.

### Where delegates come from

- The scenario's `mcp_delegates:`: a delegates file path (relative to the
  scenario file) or an inline list of entries.
- `a2a-testbed run --mcp-delegates FILE`: entries in this file override
  the scenario's for the same URI, so a CI job can point a scenario at a
  locally installed or pinned server.

Delegate entries (see `examples/mcp-delegates.yaml`):

```yaml
delegates:
  - uri: https://example.org/my-extension/v1   # extension URI
    command: [my-extension-mcp]                 # argv (list, or a shell-style string);
                                                #   "{python}" = the testbed's interpreter;
                                                #   relative paths resolve against this file
    card_validator_tool: validate_service_ref   # optional, for `validate --via-mcp`
    card_arg_name: ref                          # optional, default "ref"
    env: {LOG_LEVEL: warning}                   # optional
```

The same file serves `a2a-testbed validate CARD --via-mcp --mcp-delegates
FILE`, which calls each delegate's `card_validator_tool` with the card
extension's `params`.

### Migrating from 0.2

Up to 0.2.0a1, steps could carry `acap:`, `phala:`, `nerve:` or `pace:`
blocks. They were recorded in the step detail and **never checked**: the
step passed whatever they said. They are now a load error. Rewrite each
one as a tool call on that protocol's MCP server under `extensions:`,
keyed by the protocol's extension URI, or delete it if no tool backs it.

`examples/scenarios/extension_checks.yaml` is a complete example against
the PACE server.
