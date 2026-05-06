# Java agent template (placeholder)

A reference Java agent for the subprocess runtime is on the roadmap
but not yet included. The runtime adapter at
`src/a2a_testbed/runtimes/java.py` spawns `java -jar agent.jar`
against this directory. When a contributor adds the jar (e.g. via
`./gradlew build`), the `runtime: java` scenario kind will work
without orchestrator changes.

## Contract a Java agent must satisfy

The agent process must:

1. Accept these CLI flags:
   - `--agent-card <path>` — AgentCard JSON file
   - `--scripts <path>` — JSON object: `{"action": "response", ...}`
   - `--port <int>` — bind port (`0` = random)

2. Bind an HTTP server on `127.0.0.1:<port>`.

3. Print exactly one line on stdout when listening:
   ```
   A2A_TESTBED_READY: http://127.0.0.1:<actual-port>
   ```

4. Serve the AgentCard at `/.well-known/agent-card.json`.

5. Accept JSON-RPC at the root path. Implement `message/send`:
   - extract the user's text from `params.message.parts[*].text`
   - match against the scripts map (substring, case-insensitive)
   - return a JSON-RPC `result` containing a message with the matched
     response (or a default fallback)

See `agents/python-template/main.py`, `agents/nodejs-template/index.js`,
or `agents/go-template/main.go` for ~100 LOC reference implementations.

## Recommended path

A clean Java implementation would use the official `a2a-java` SDK (see
the project's awesome list). For the testbed's purposes, even a stdlib
`com.sun.net.httpserver.HttpServer` would work — the goal is exercising
the polyglot subprocess adapter, not full A2A compliance from this
template.
