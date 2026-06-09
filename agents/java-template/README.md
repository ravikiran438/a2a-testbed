# Java reference agent

A minimal A2A 1.0 agent for the a2a-testbed **Java subprocess runtime**,
mirroring `agents/nodejs-template/` and `agents/go-template/`. It exists so
the cross-SDK polyglot story includes Java: a scenario can mix a Python
principal, a Go service, a Node.js guardian, and a Java agent in one run.

JDK stdlib only (`com.sun.net.httpserver` + regex, no JSON library), so it
builds into a single dependency-free jar.

## Build

Either way produces `target/agent.jar`:

```bash
# Maven (recommended)
mvn -q package

# or no-Maven, no-network
./build.sh
```

Requires a JDK 17+ (`javac` + `jar` on PATH).

## Use in a scenario

Point a `runtime: java` agent's `source:` at the built jar:

```yaml
agents:
  - id: helper
    card: ../agent-cards/helper.json
    runtime: java
    source: ../../agents/java-template/target/agent.jar
    role: service_provider
```

The testbed's `JavaRuntime` adapter spawns it as:

```
java -jar <source> --agent-card <card> --scripts <scripts> --port <port>
```

The agent binds `127.0.0.1`, prints `A2A_TESTBED_READY: http://127.0.0.1:<port>`
when listening, serves the AgentCard at
`/.well-known/agent-card.json`, and answers JSON-RPC `message/send`:
it extracts the message text, matches it (case-insensitive substring)
against the `--scripts` map, and replies with
`[<agent name>] <scripted response>`. Unknown methods return JSON-RPC
`-32601`.

## Contract (parity with the other templates)

| Surface | Behaviour |
|---|---|
| CLI | `--agent-card`, `--scripts`, `--port` (0 = ephemeral), `--host` |
| Ready line | `A2A_TESTBED_READY: http://<host>:<port>` on stdout |
| `GET …/.well-known/agent-card.json` | 200, the AgentCard JSON verbatim |
| `POST` `message/send` | `result.parts[0].text = "[<name>] <response>"` |
| `POST` other method | JSON-RPC error `-32601` |

Source: `src/main/java/com/a2atestbed/template/Main.java` (~150 LOC).
