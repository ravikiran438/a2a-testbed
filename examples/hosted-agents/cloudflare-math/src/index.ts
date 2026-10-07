/**
 * A2A 1.0 compliant math agent (with A2A 0.3 compatibility).
 *
 *   Endpoints
 *     GET  /                              -> AgentCard JSON (also serves
 *                                            /.well-known/agent-card.json)
 *     GET  /.well-known/agent-card.json   -> AgentCard JSON
 *     POST /                              -> JSON-RPC 2.0:
 *                                              "SendMessage" (A2A 1.0,
 *                                              header A2A-Version: 1.0)
 *                                              "message/send" (A2A 0.3)
 *
 * Every other A2A method answers with the error the spec mandates for
 * an agent that advertises no streaming / push / extended card and
 * keeps no task store (§3.3.4): UnsupportedOperation, PushNotification-
 * NotSupported, or TaskNotFound.
 *
 * The agent answers arithmetic + word-math problems by calling Groq's
 * Llama 3.3 in JSON mode. Forcing JSON output keeps the response shape
 * deterministic so downstream test runners can match exact fields:
 *
 *     { "answer": <number>, "explanation": <string> }
 *
 * That mapping is the entire agent contract. Anything off-topic is
 * answered with `{ "answer": null, "explanation": "<why>" }`.
 */

interface Env {
  GROQ_API_KEY: string;
  GROQ_MODEL: string; // pinned in wrangler.toml [vars]
  /** Cloudflare RateLimit binding declared in wrangler.toml.
   *  Per-IP throttle for LLM calls. */
  MATH_RATE_LIMITER: {
    limit: (opts: { key: string }) => Promise<{ success: boolean }>;
  };
}

// --------------------------------------------------------------------------
// CORS origin allowlist. Only origins listed here get a CORS
// allow-origin header reflected back. Edit this list when forking
// the worker for a different deployment. Server-side callers ignore
// CORS, so the per-IP rate limiter is the cap on that path.
// --------------------------------------------------------------------------

const ALLOWED_ORIGINS: ReadonlyArray<string | RegExp> = [
  "https://a2a-testbed.com",
  "https://www.a2a-testbed.com",
  /^http:\/\/localhost:\d+$/,
  /^http:\/\/127\.0\.0\.1:\d+$/,
];

function originAllowed(origin: string | null): string | null {
  if (!origin) return null;
  for (const entry of ALLOWED_ORIGINS) {
    if (typeof entry === "string") {
      if (entry === origin) return origin;
    } else if (entry.test(origin)) {
      return origin;
    }
  }
  return null;
}

// --------------------------------------------------------------------------
// AgentCard: returned at the well-known endpoint and at GET /.
// Self-URL is computed at request time so the same code works locally
// (`wrangler dev`) and after deploy without editing this file.
// --------------------------------------------------------------------------

function buildAgentCard(selfUrl: string) {
  // A2A 1.0 schema: top-level `url` was removed in favor of
  // `supportedInterfaces[*].url`. Each interface declares its own
  // protocolBinding + endpoint URL; clients pick from the list.
  return {
    name: "Math Agent",
    description:
      "Answers arithmetic and short word-math problems via Llama 3.3 " +
      "(Groq) in JSON mode. Returns a deterministic JSON envelope so " +
      "clients can extract the numeric answer programmatically.",
    version: "1.0.0",
    supportedInterfaces: [
      // protocolVersion is per-interface (§8.3.1, spec line 2143);
      // declares which A2A protocol revision this binding speaks. The
      // same URL also serves 0.3 clients (§3.6.2 allows several
      // versions per transport and URL); 1.0 is listed first (preferred).
      { url: selfUrl, protocolBinding: "JSONRPC", protocolVersion: "1.0" },
      { url: selfUrl, protocolBinding: "JSONRPC", protocolVersion: "0.3" },
    ],
    // A2A 0.3 top-level fields, so 0.3 clients can read the same card
    // (the merge the a2a-sdk's card route performs for dual-version
    // agents). 1.0 clients ignore unrecognized fields.
    url: selfUrl,
    protocolVersion: "0.3",
    preferredTransport: "JSONRPC",
    capabilities: {
      streaming: false,
      pushNotifications: false,
      extensions: [],
    },
    defaultInputModes: ["text"],
    defaultOutputModes: ["text"],
    skills: [
      {
        id: "answer_math",
        name: "Answer a math question",
        description:
          "Accepts an arithmetic expression or a short word problem; " +
          "returns a JSON object with `answer` (number or null) and " +
          "`explanation` (one-sentence rationale).",
        tags: ["math", "json"],
        inputModes: ["text"],
        outputModes: ["text"],
      },
    ],
  };
}

// --------------------------------------------------------------------------
// JSON-RPC + A2A response builders.
// --------------------------------------------------------------------------

interface JsonRpcRequest {
  jsonrpc?: string;
  id?: string | number | null;
  method?: string;
  params?: unknown;
}

type Dialect = "1.0" | "0.3";

// google.rpc.ErrorInfo reasons for the codes this agent returns (§5.4).
const ERROR_REASONS: Record<number, string> = {
  [-32001]: "TASK_NOT_FOUND",
  [-32003]: "PUSH_NOTIFICATION_NOT_SUPPORTED",
  [-32004]: "UNSUPPORTED_OPERATION",
  [-32009]: "VERSION_NOT_SUPPORTED",
  [-32600]: "INVALID_REQUEST",
  [-32601]: "METHOD_NOT_FOUND",
  [-32602]: "INVALID_PARAMS",
  [-32603]: "INTERNAL_ERROR",
  [-32700]: "JSON_PARSE_ERROR",
};

/** JSON-RPC error. In 1.0, `error.data` carries a google.rpc.ErrorInfo
 *  (§9.5); 0.3 errors carry code + message only. */
function jsonRpcError(
  id: string | number | null | undefined,
  code: number,
  message: string,
  origin: string | null,
  dialect: Dialect = "1.0",
): Response {
  const error: Record<string, unknown> = { code, message };
  if (dialect === "1.0" && ERROR_REASONS[code]) {
    error.data = [
      {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        reason: ERROR_REASONS[code],
        domain: "a2a-protocol.org",
        metadata: {},
      },
    ];
  }
  return Response.json(
    { jsonrpc: "2.0", id: id ?? null, error },
    { headers: corsHeaders(origin) },
  );
}

// A2A method names per protocol version, mapped to the operation.
const METHODS: Record<string, { dialect: Dialect; op: string }> = {
  SendMessage: { dialect: "1.0", op: "send" },
  SendStreamingMessage: { dialect: "1.0", op: "stream" },
  GetTask: { dialect: "1.0", op: "get" },
  ListTasks: { dialect: "1.0", op: "list" },
  CancelTask: { dialect: "1.0", op: "cancel" },
  SubscribeToTask: { dialect: "1.0", op: "subscribe" },
  CreateTaskPushNotificationConfig: { dialect: "1.0", op: "push" },
  GetTaskPushNotificationConfig: { dialect: "1.0", op: "push" },
  ListTaskPushNotificationConfigs: { dialect: "1.0", op: "push" },
  DeleteTaskPushNotificationConfig: { dialect: "1.0", op: "push" },
  GetExtendedAgentCard: { dialect: "1.0", op: "extended_card" },
  "message/send": { dialect: "0.3", op: "send" },
  "message/stream": { dialect: "0.3", op: "stream" },
  "tasks/get": { dialect: "0.3", op: "get" },
  "tasks/cancel": { dialect: "0.3", op: "cancel" },
  "tasks/resubscribe": { dialect: "0.3", op: "subscribe" },
  "tasks/pushNotificationConfig/set": { dialect: "0.3", op: "push" },
  "tasks/pushNotificationConfig/get": { dialect: "0.3", op: "push" },
  "tasks/pushNotificationConfig/list": { dialect: "0.3", op: "push" },
  "tasks/pushNotificationConfig/delete": { dialect: "0.3", op: "push" },
  "agent/getAuthenticatedExtendedCard": { dialect: "0.3", op: "extended_card" },
};

/** Requested version from A2A-Version (§3.6.2: absent = 0.3); null
 *  when it names a version this agent does not serve. */
function requestedDialect(header: string | null): Dialect | null {
  if (!header || !header.trim()) return "0.3";
  const versions = header.split(",").map((v) => v.trim());
  if (versions.some((v) => /^1(\.\d+)*$/.test(v))) return "1.0";
  if (versions.some((v) => /^0\.3(\.\d+)*$/.test(v))) return "0.3";
  return null;
}

/** The answer as a Message, in the caller's protocol version. The
 *  agent is stateless (nothing to poll, cancel or subscribe to), so it
 *  replies with a Message rather than a Task (A2A 1.0 §3.1.1 allows
 *  either; a Task would promise a GetTask the agent cannot honor). */
function answerMessage(dialect: Dialect, text: string, contextId: string) {
  const messageId = crypto.randomUUID();
  if (dialect === "1.0") {
    return {
      message: { messageId, contextId, role: "ROLE_AGENT", parts: [{ text }] },
    };
  }
  return {
    kind: "message",
    messageId,
    contextId,
    role: "agent",
    parts: [{ kind: "text", text }],
  };
}

function jsonRpcResult(
  id: string | number | null | undefined,
  result: unknown,
  origin: string | null,
): Response {
  return Response.json(
    {
      jsonrpc: "2.0",
      id: id ?? null,
      result,
    },
    { headers: corsHeaders(origin) },
  );
}

/**
 * Build CORS headers for the response. If the request's Origin is
 * on the allowlist we reflect it back; otherwise we omit the
 * allow-origin header entirely so browsers block the response.
 */
function corsHeaders(origin: string | null): Record<string, string> {
  const allowed = originAllowed(origin);
  const headers: Record<string, string> = {
    "access-control-allow-methods": "GET, POST, OPTIONS",
    // A2A-Version / A2A-Extensions are the 1.0 service parameters
    // clients send as HTTP headers; browsers preflight on them.
    "access-control-allow-headers": "content-type, a2a-version, a2a-extensions",
    "access-control-max-age": "86400",
    // Tell shared caches / CDNs that responses vary by Origin so the
    // allowlist decision isn't cached against the wrong requester.
    vary: "Origin",
  };
  if (allowed) {
    headers["access-control-allow-origin"] = allowed;
  }
  return headers;
}

// --------------------------------------------------------------------------
// A2A message extraction: pull plain text out of the request's
// `params.message.parts[*]`. Tolerant of small shape variations.
// --------------------------------------------------------------------------

interface A2APart { kind?: string; text?: string }
interface A2AMessage { parts?: A2APart[] }

function extractUserText(params: unknown): string {
  if (!params || typeof params !== "object") return "";
  const message = (params as { message?: A2AMessage }).message;
  if (!message || !Array.isArray(message.parts)) return "";
  return message.parts
    .filter((p) => (!p.kind || p.kind === "text") && typeof p.text === "string")
    .map((p) => p.text!)
    .join(" ")
    .trim();
}

// --------------------------------------------------------------------------
// Groq call. Uses OpenAI-compatible chat completions endpoint with
// JSON mode (`response_format: { type: "json_object" }`). The system
// prompt pins the schema so the model can't drift into prose.
// --------------------------------------------------------------------------

const SYSTEM_PROMPT = `\
You are a math agent. The user will send an arithmetic expression or a \
short word-math problem. Reply ONLY with a JSON object of the form:

  {"answer": <number-or-null>, "explanation": "<one short sentence>"}

Rules:
- "answer" MUST be a JSON number when the problem is mathematical.
- "answer" MUST be JSON null when the input is not a math question.
- "explanation" MUST be one sentence, plain ASCII, no markdown.
- Reply with the JSON object and nothing else. No code fences.`;

interface GroqAnswer {
  answer: number | null;
  explanation: string;
}

async function callGroq(env: Env, userText: string): Promise<GroqAnswer> {
  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GROQ_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: env.GROQ_MODEL,
      response_format: { type: "json_object" },
      temperature: 0,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: userText },
      ],
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Groq ${res.status}: ${text.slice(0, 200)}`);
  }

  const body = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const content = body.choices?.[0]?.message?.content ?? "{}";

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch (err) {
    throw new Error(
      `Groq returned non-JSON despite json_object mode: ${(err as Error).message}`,
    );
  }

  // Coerce into the shape we promised on the AgentCard.
  const obj = parsed as Partial<GroqAnswer>;
  return {
    answer:
      typeof obj.answer === "number"
        ? obj.answer
        : obj.answer === null
        ? null
        : null,
    explanation:
      typeof obj.explanation === "string"
        ? obj.explanation
        : "(no explanation)",
  };
}

// --------------------------------------------------------------------------
// HTTP entry point.
// --------------------------------------------------------------------------

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const selfUrl = `${url.protocol}//${url.host}`;
    const origin = req.headers.get("origin");

    // CORS preflight
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // AgentCard discovery. Same JSON for every caller, so we let
    // Cloudflare's edge cache it (s-maxage=300) and the browser
    // hold it briefly (max-age=60). The card barely changes between
    // deploys; conformance correctness is verified against the live
    // JSON-RPC handlers, not this static descriptor.
    if (
      req.method === "GET" &&
      (url.pathname === "/" ||
        url.pathname === "/.well-known/agent-card.json")
    ) {
      return Response.json(buildAgentCard(selfUrl), {
        headers: {
          ...corsHeaders(origin),
          "cache-control": "public, max-age=60, s-maxage=300",
        },
      });
    }

    // JSON-RPC. Accept both the bare root and the A2A 1.0 conventional
    // path (`/a2a/v1/`, with or without trailing slash). The testbed's
    // default transport posts to `<agent_url>/a2a/v1/`; ad-hoc curl
    // testers hitting the root URL work too.
    const isJsonRpcPath =
      url.pathname === "/" ||
      url.pathname === "" ||
      url.pathname === "/a2a/v1" ||
      url.pathname === "/a2a/v1/";
    if (req.method === "POST" && isJsonRpcPath) {
      // Per-IP rate limit. Cloudflare populates `cf-connecting-ip`
      // on every inbound request; we fall back to a constant when
      // it's missing so misconfigured deploys don't accidentally
      // bypass the limiter. Uses the binding declared in
      // wrangler.toml (`MATH_RATE_LIMITER`) — no DO setup required.
      const clientIp = req.headers.get("cf-connecting-ip") ?? "unknown";
      const { success } = await env.MATH_RATE_LIMITER.limit({
        key: clientIp,
      });
      if (!success) {
        return new Response(
          JSON.stringify({
            jsonrpc: "2.0",
            id: null,
            error: {
              code: -32029,
              message:
                "rate limit exceeded — this demo agent caps requests per IP. Try again in a minute.",
            },
          }),
          {
            status: 429,
            headers: {
              ...corsHeaders(origin),
              "content-type": "application/json",
              "retry-after": "60",
            },
          },
        );
      }

      let body: JsonRpcRequest;
      try {
        body = (await req.json()) as JsonRpcRequest;
      } catch {
        return jsonRpcError(null, -32700, "parse error: body is not JSON", origin);
      }

      const id = body.id ?? null;

      if (body.jsonrpc !== "2.0") {
        return jsonRpcError(id, -32600, "invalid request: jsonrpc must be '2.0'", origin);
      }

      const found = typeof body.method === "string" ? METHODS[body.method] : undefined;
      if (!found) {
        return jsonRpcError(id, -32601, `method not found: ${String(body.method)}`, origin);
      }
      const { dialect, op } = found;
      const versionHeader = req.headers.get("a2a-version");
      const requested = requestedDialect(versionHeader);
      if (requested === null) {
        return jsonRpcError(
          id,
          -32009,
          `A2A-Version ${versionHeader} is not supported; this agent serves 1.0 and 0.3`,
          origin,
          dialect,
        );
      }
      if (dialect === "1.0" && requested !== "1.0") {
        return jsonRpcError(
          id,
          -32009,
          `${body.method} is an A2A 1.0 method; send the header A2A-Version: 1.0 ` +
            "(an absent header means 0.3, A2A 1.0 §3.6.2)",
          origin,
        );
      }
      // Capability errors the spec mandates for what the card does not
      // advertise (§3.3.4), and TaskNotFound for task lookups (answers
      // are not stored).
      if (op === "stream" || op === "subscribe" || op === "extended_card") {
        return jsonRpcError(id, -32004, `${body.method} is not supported by this agent`, origin, dialect);
      }
      if (op === "push") {
        return jsonRpcError(id, -32003, "push notifications are not supported by this agent", origin, dialect);
      }
      if (op === "list") {
        return jsonRpcResult(id, { tasks: [], nextPageToken: "", pageSize: 0, totalSize: 0 }, origin);
      }
      if (op === "get" || op === "cancel") {
        return jsonRpcError(id, -32001, "task not found (this agent creates no tasks)", origin, dialect);
      }

      const userText = extractUserText(body.params);
      if (!userText) {
        return jsonRpcError(
          id,
          -32602,
          "invalid params: no text part found in message.parts",
          origin,
          dialect,
        );
      }

      try {
        const answer = await callGroq(env, userText);
        // Canonical spacing (`: ` after keys) so substring matchers
        // in scenario files can rely on a fixed wire format regardless
        // of how the LLM happens to emit whitespace.
        const canonicalText = `{"answer": ${
          answer.answer === null ? "null" : String(answer.answer)
        }, "explanation": ${JSON.stringify(answer.explanation)}}`;
        // Preserve the client's contextId if supplied; otherwise mint
        // one so multi-turn clients can chain follow-ups under a stable
        // grouping (§3.4.2).
        const params = body.params as
          | { message?: { contextId?: string } }
          | undefined;
        const responseContextId =
          params?.message?.contextId ?? crypto.randomUUID();
        return jsonRpcResult(id, answerMessage(dialect, canonicalText, responseContextId), origin);
      } catch (err) {
        return jsonRpcError(id, -32603, (err as Error).message, origin, dialect);
      }
    }

    return new Response("Not Found", {
      status: 404,
      headers: corsHeaders(origin),
    });
  },
} satisfies ExportedHandler<Env>;
