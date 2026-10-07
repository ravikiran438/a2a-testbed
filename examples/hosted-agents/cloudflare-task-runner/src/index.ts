/**
 * A2A reference task runner (A2A 1.0, with A2A 0.3 compatibility).
 *
 * Implements every A2A 1.0 JSON-RPC method (SendMessage,
 * SendStreamingMessage, GetTask, ListTasks, CancelTask,
 * SubscribeToTask, {Create,Get,List,Delete}TaskPushNotificationConfig,
 * GetExtendedAgentCard) with the 1.0 ProtoJSON payload shapes, so the
 * official a2a-sdk 1.x clients interoperate unmodified.
 *
 * The same endpoint also serves A2A 0.3 clients (`message/send`,
 * `tasks/get`, ...) with 0.3 payloads (`kind` discriminators,
 * lower-case task states, bare Task results), the same arrangement as
 * the a2a-sdk server's `enable_v0_3_compat`. The AgentCard advertises
 * both: a 1.0 JSONRPC interface first (preferred) and a 0.3 one on the
 * same URL (A2A 1.0 §3.6.2: "Agents CAN expose multiple interfaces for
 * the same transport with different versions under the same or
 * different URLs").
 *
 * Version negotiation follows A2A 1.0 §3.6.2: a 1.0 method must carry
 * `A2A-Version: 1.x` (an absent header means 0.3), and any request
 * for a version this agent does not serve gets VersionNotSupportedError.
 *
 * Tasks run against an in-memory work simulator. Tasks "do work"
 * by emitting N artifact updates spaced 50ms apart; the input text
 * may carry a leading integer to choose N (default 5, capped at
 * MAX_WORK_UNITS).
 *
 * Storage: a single global Durable Object (`TaskRunnerDO`) owns
 * every task + push config. Routing all requests to one DO keeps
 * the access pattern serialized and avoids KV's daily write cap —
 * DO storage has no per-day cap; only per-instance request rate
 * limits (effectively unbounded for a demo at this scale). The stored
 * shape is version-neutral and rendered per request, so tasks created
 * by either protocol version are visible to both.
 */

interface Env {
  TASK_RUNNER: DurableObjectNamespace;
  TASK_RATE_LIMITER: {
    limit: (opts: { key: string }) => Promise<{ success: boolean }>;
  };
  MAX_WORK_UNITS: string;
}

// --------------------------------------------------------------------------
// Stored (version-neutral) shapes. Kept identical to what earlier
// releases persisted so existing Durable Object data stays readable.
// --------------------------------------------------------------------------

interface MessagePart {
  kind: "text";
  text: string;
}

interface Message {
  messageId: string;
  role: "user" | "agent" | "ROLE_USER" | "ROLE_AGENT";
  parts: MessagePart[];
  contextId?: string;
  taskId?: string;
}

interface ArtifactObj {
  artifactId: string;
  parts: MessagePart[];
  name?: string;
}

interface TaskStatus {
  state: TaskState;
  timestamp: string;
  message?: Message;
}

type TaskState =
  | "TASK_STATE_SUBMITTED"
  | "TASK_STATE_WORKING"
  | "TASK_STATE_INPUT_REQUIRED"
  | "TASK_STATE_COMPLETED"
  | "TASK_STATE_CANCELED"
  | "TASK_STATE_FAILED"
  | "TASK_STATE_REJECTED"
  | "TASK_STATE_AUTH_REQUIRED";

const TERMINAL_STATES: ReadonlySet<TaskState> = new Set([
  "TASK_STATE_COMPLETED",
  "TASK_STATE_CANCELED",
  "TASK_STATE_FAILED",
  "TASK_STATE_REJECTED",
]);

interface Task {
  id: string;
  contextId: string;
  status: TaskStatus;
  history: Message[];
  artifacts: ArtifactObj[];
}

interface PushNotificationConfig {
  id: string;
  url: string;
  token?: string;
  authentication?: {
    schemes: string[];
    credentials?: string;
  };
  /** Protocol version the config was registered with; decides the
   *  webhook payload shape. Absent on configs stored before 1.0. */
  dialect?: Dialect;
}

interface JsonRpcRequest {
  jsonrpc?: string;
  id?: string | number | null;
  method?: string;
  params?: unknown;
}

type Dialect = "1.0" | "0.3";

// --------------------------------------------------------------------------
// CORS allowlist (matches cloudflare-math worker exactly).
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

function corsHeaders(origin: string | null): Record<string, string> {
  const allowed = originAllowed(origin);
  const headers: Record<string, string> = {
    "access-control-allow-methods": "GET, POST, OPTIONS",
    // A2A-Version / A2A-Extensions are the 1.0 service parameters
    // clients send as HTTP headers; browsers preflight on them.
    "access-control-allow-headers": "content-type, a2a-version, a2a-extensions",
    "access-control-max-age": "86400",
    vary: "Origin",
  };
  if (allowed) headers["access-control-allow-origin"] = allowed;
  return headers;
}

// --------------------------------------------------------------------------
// AgentCard
// --------------------------------------------------------------------------

function buildAgentCard(selfUrl: string) {
  return {
    name: "Task Runner",
    description:
      "A2A reference agent exercising the full task lifecycle: " +
      "SendMessage, SSE streaming via SendStreamingMessage, " +
      "GetTask / ListTasks / CancelTask, SubscribeToTask, and " +
      "{Create,Get,List,Delete}TaskPushNotificationConfig. " +
      "Serves A2A 1.0 and, on the same URL, A2A 0.3. Echoes input " +
      "back over N work units (default 5; client may send " +
      "'count: N' to override).",
    version: "1.1.0",
    supportedInterfaces: [
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
      streaming: true,
      pushNotifications: true,
      extensions: [],
    },
    defaultInputModes: ["text"],
    defaultOutputModes: ["text"],
    skills: [
      {
        id: "echo_over_time",
        name: "Echo over time",
        description:
          "Accept any text input and emit N artifact updates spaced " +
          "50ms apart, then complete the task. Useful for exercising " +
          "the full Task / SSE / push-notification surface.",
        tags: ["task", "streaming", "demo"],
        inputModes: ["text"],
        outputModes: ["text"],
      },
    ],
  };
}

// --------------------------------------------------------------------------
// Methods per protocol version.
// --------------------------------------------------------------------------

type Op =
  | "send"
  | "stream"
  | "get"
  | "list"
  | "cancel"
  | "subscribe"
  | "push_set"
  | "push_get"
  | "push_list"
  | "push_delete"
  | "extended_card";

const METHODS: Record<Dialect, Record<Op, string>> = {
  "1.0": {
    send: "SendMessage",
    stream: "SendStreamingMessage",
    get: "GetTask",
    list: "ListTasks",
    cancel: "CancelTask",
    subscribe: "SubscribeToTask",
    push_set: "CreateTaskPushNotificationConfig",
    push_get: "GetTaskPushNotificationConfig",
    push_list: "ListTaskPushNotificationConfigs",
    push_delete: "DeleteTaskPushNotificationConfig",
    extended_card: "GetExtendedAgentCard",
  },
  "0.3": {
    send: "message/send",
    stream: "message/stream",
    get: "tasks/get",
    // Not part of A2A 0.3; earlier releases of this agent served it.
    list: "tasks/list",
    cancel: "tasks/cancel",
    subscribe: "tasks/resubscribe",
    push_set: "tasks/pushNotificationConfig/set",
    push_get: "tasks/pushNotificationConfig/get",
    push_list: "tasks/pushNotificationConfig/list",
    push_delete: "tasks/pushNotificationConfig/delete",
    extended_card: "agent/getAuthenticatedExtendedCard",
  },
};

const METHOD_LOOKUP = new Map<string, { dialect: Dialect; op: Op }>();
for (const dialect of ["1.0", "0.3"] as const) {
  for (const [op, name] of Object.entries(METHODS[dialect])) {
    METHOD_LOOKUP.set(name, { dialect, op: op as Op });
  }
}

/** Requested protocol version from the A2A-Version header
 *  (§3.6.2: absent = 0.3); `null` when it names a version this agent
 *  does not serve. */
function requestedDialect(header: string | null): Dialect | null {
  if (!header || !header.trim()) return "0.3";
  const versions = header.split(",").map((v) => v.trim());
  if (versions.some((v) => /^1(\.\d+)*$/.test(v))) return "1.0";
  if (versions.some((v) => /^0\.3(\.\d+)*$/.test(v))) return "0.3";
  return null;
}

// --------------------------------------------------------------------------
// JSON-RPC helpers (used by the DO; CORS headers are added by the
// outer worker after the DO returns).
// --------------------------------------------------------------------------

type RpcId = string | number | null | undefined;

function rpcResult(id: RpcId, result: unknown): Response {
  return Response.json({ jsonrpc: "2.0", id: id ?? null, result });
}

/** A2A error codes (§5.4) with their google.rpc.ErrorInfo reasons. */
const A2A_ERRORS = {
  TASK_NOT_FOUND: -32001,
  TASK_NOT_CANCELABLE: -32002,
  PUSH_NOTIFICATION_NOT_SUPPORTED: -32003,
  UNSUPPORTED_OPERATION: -32004,
  CONTENT_TYPE_NOT_SUPPORTED: -32005,
  EXTENDED_AGENT_CARD_NOT_CONFIGURED: -32007,
  VERSION_NOT_SUPPORTED: -32009,
  INVALID_PARAMS: -32602,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INTERNAL_ERROR: -32603,
  JSON_PARSE_ERROR: -32700,
} as const;
type A2AErrorReason = keyof typeof A2A_ERRORS;

/** JSON-RPC error body. 1.0 attaches a google.rpc.ErrorInfo in
 *  `error.data` (§9.5); 0.3 errors carry code + message only. */
function errorBody(
  id: RpcId,
  reason: A2AErrorReason,
  message: string,
  dialect: Dialect = "1.0",
) {
  const error: Record<string, unknown> = { code: A2A_ERRORS[reason], message };
  if (dialect === "1.0") {
    error.data = [
      {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        reason,
        domain: "a2a-protocol.org",
        metadata: {},
      },
    ];
  }
  return { jsonrpc: "2.0", id: id ?? null, error };
}

function rpcError(
  id: RpcId,
  reason: A2AErrorReason,
  message: string,
  dialect: Dialect = "1.0",
): Response {
  return Response.json(errorBody(id, reason, message, dialect));
}

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

/** Text of every text part, accepting both 0.3 (`{kind, text}`) and
 *  1.0 (`{text}`) Parts. */
function extractText(message: unknown): string {
  if (!message || typeof message !== "object") return "";
  const parts = (message as { parts?: unknown }).parts;
  if (!Array.isArray(parts)) return "";
  return parts
    .filter(
      (p) =>
        p &&
        typeof p === "object" &&
        ((p as { kind?: unknown }).kind === "text" ||
          (p as { kind?: unknown }).kind === undefined) &&
        typeof (p as { text?: unknown }).text === "string",
    )
    .map((p) => (p as { text: string }).text)
    .join(" ")
    .trim();
}

function parseCount(text: string, max: number): number {
  const m = /(?:count\s*:\s*)?(\d+)/i.exec(text);
  if (!m) return 5;
  const n = parseInt(m[1] ?? "0", 10);
  if (Number.isNaN(n) || n < 1) return 5;
  return Math.min(n, max);
}

function nowIso(): string {
  return new Date().toISOString();
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function sseEvent(data: unknown): string {
  return `data: ${JSON.stringify(data)}\n\n`;
}

const SSE_HEADERS = {
  "content-type": "text/event-stream",
  "cache-control": "no-cache",
} as const;

/** Optional int32 field from a ProtoJSON object (ints may arrive as
 *  strings). Returns undefined when absent or malformed. */
function optInt(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isInteger(v)) return v;
  if (typeof v === "string" && /^-?\d+$/.test(v)) return parseInt(v, 10);
  return undefined;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v ? v : undefined;
}

/** Max tasks ListTasks scans (newest first) before filtering. */
const LIST_SCAN_LIMIT = 500;
/** Upper bound on a SubscribeToTask stream's lifetime. */
const SUBSCRIBE_MAX_MS = 30_000;

// --------------------------------------------------------------------------
// Rendering: A2A 1.0 (ProtoJSON of a2a.proto). The official SDKs parse
// strictly (unknown fields are rejected), so the 1.0 renderers emit
// exactly these fields and nothing else.
// --------------------------------------------------------------------------

function isAgent(role: Message["role"]): boolean {
  return role === "agent" || role === "ROLE_AGENT";
}

function v1Parts(parts: MessagePart[]) {
  return parts.map((p) => ({ text: p.text }));
}

function v1Message(m: Message) {
  return {
    messageId: m.messageId,
    ...(m.contextId ? { contextId: m.contextId } : {}),
    ...(m.taskId ? { taskId: m.taskId } : {}),
    role: isAgent(m.role) ? "ROLE_AGENT" : "ROLE_USER",
    parts: v1Parts(m.parts),
  };
}

function v1Artifact(a: ArtifactObj) {
  return {
    artifactId: a.artifactId,
    ...(a.name ? { name: a.name } : {}),
    parts: v1Parts(a.parts),
  };
}

function v1Status(s: TaskStatus) {
  return {
    state: s.state,
    ...(s.message ? { message: v1Message(s.message) } : {}),
    timestamp: s.timestamp,
  };
}

interface RenderOpts {
  historyLength?: number;
  includeArtifacts?: boolean;
}

/** `historyLength` per spec: unset = no limit, 0 = omit, N = last N. */
function trimHistory(history: Message[], historyLength?: number): Message[] {
  if (typeof historyLength !== "number") return history;
  return historyLength <= 0 ? [] : history.slice(-historyLength);
}

function v1Task(t: Task, opts: RenderOpts = {}) {
  const history = trimHistory(t.history, opts.historyLength);
  const includeArtifacts = opts.includeArtifacts ?? true;
  return {
    id: t.id,
    contextId: t.contextId,
    status: v1Status(t.status),
    ...(includeArtifacts && t.artifacts.length
      ? { artifacts: t.artifacts.map(v1Artifact) }
      : {}),
    ...(history.length ? { history: history.map(v1Message) } : {}),
  };
}

function v1PushConfig(taskId: string, c: PushNotificationConfig) {
  const scheme = c.authentication?.schemes?.[0];
  return {
    id: c.id,
    taskId,
    url: c.url,
    ...(c.token ? { token: c.token } : {}),
    ...(scheme
      ? {
          authentication: {
            scheme,
            ...(c.authentication?.credentials
              ? { credentials: c.authentication.credentials }
              : {}),
          },
        }
      : {}),
  };
}

// --------------------------------------------------------------------------
// Rendering: A2A 0.3 (kind discriminators, lower-case states).
// --------------------------------------------------------------------------

const V03_STATE: Record<TaskState, string> = {
  TASK_STATE_SUBMITTED: "submitted",
  TASK_STATE_WORKING: "working",
  TASK_STATE_INPUT_REQUIRED: "input-required",
  TASK_STATE_COMPLETED: "completed",
  TASK_STATE_CANCELED: "canceled",
  TASK_STATE_FAILED: "failed",
  TASK_STATE_REJECTED: "rejected",
  TASK_STATE_AUTH_REQUIRED: "auth-required",
};

function v03Parts(parts: MessagePart[]) {
  return parts.map((p) => ({ kind: "text", text: p.text }));
}

function v03Message(m: Message) {
  return {
    kind: "message",
    messageId: m.messageId,
    ...(m.contextId ? { contextId: m.contextId } : {}),
    ...(m.taskId ? { taskId: m.taskId } : {}),
    role: isAgent(m.role) ? "agent" : "user",
    parts: v03Parts(m.parts),
  };
}

function v03Artifact(a: ArtifactObj) {
  return {
    artifactId: a.artifactId,
    ...(a.name ? { name: a.name } : {}),
    parts: v03Parts(a.parts),
  };
}

function v03Status(s: TaskStatus) {
  return {
    state: V03_STATE[s.state] ?? "unknown",
    ...(s.message ? { message: v03Message(s.message) } : {}),
    timestamp: s.timestamp,
  };
}

function v03Task(t: Task, opts: RenderOpts = {}) {
  const history = trimHistory(t.history, opts.historyLength);
  return {
    kind: "task",
    id: t.id,
    contextId: t.contextId,
    status: v03Status(t.status),
    ...(t.artifacts.length ? { artifacts: t.artifacts.map(v03Artifact) } : {}),
    ...(history.length ? { history: history.map(v03Message) } : {}),
  };
}

function v03PushConfig(taskId: string, c: PushNotificationConfig) {
  return {
    taskId,
    pushNotificationConfig: {
      id: c.id,
      url: c.url,
      ...(c.token ? { token: c.token } : {}),
      ...(c.authentication ? { authentication: c.authentication } : {}),
    },
  };
}

function renderTask(dialect: Dialect, t: Task, opts: RenderOpts = {}) {
  return dialect === "1.0" ? v1Task(t, opts) : v03Task(t, opts);
}

// --------------------------------------------------------------------------
// Streaming events.
// --------------------------------------------------------------------------

/** One streamed event, in the 1.0 StreamResponse oneof shape. */
type StreamEvent =
  | { task: Task }
  | { artifactUpdate: { taskId: string; artifact: ArtifactObj } }
  | { statusUpdate: { taskId: string; status: TaskStatus } };

/** The JSON-RPC `result` of one SSE frame in `dialect`. */
function renderStreamEvent(dialect: Dialect, e: StreamEvent, contextId: string) {
  if ("task" in e) {
    return dialect === "1.0" ? { task: v1Task(e.task) } : v03Task(e.task);
  }
  if ("artifactUpdate" in e) {
    const { taskId, artifact } = e.artifactUpdate;
    return dialect === "1.0"
      ? { artifactUpdate: { taskId, contextId, artifact: v1Artifact(artifact) } }
      : {
          kind: "artifact-update",
          taskId,
          contextId,
          artifact: v03Artifact(artifact),
        };
  }
  const { taskId, status } = e.statusUpdate;
  return dialect === "1.0"
    ? { statusUpdate: { taskId, contextId, status: v1Status(status) } }
    : {
        kind: "status-update",
        taskId,
        contextId,
        status: v03Status(status),
        final: TERMINAL_STATES.has(status.state),
      };
}

// --------------------------------------------------------------------------
// Push-config parsing.
// --------------------------------------------------------------------------

/** 1.0 TaskPushNotificationConfig (flat) -> stored config. */
function fromV1PushConfig(raw: Record<string, unknown>): PushNotificationConfig | string {
  const url = str(raw.url);
  if (!url) return "url is required";
  const auth = raw.authentication as { scheme?: unknown; credentials?: unknown } | undefined;
  const scheme = auth ? str(auth.scheme) : undefined;
  return {
    id: str(raw.id) ?? crypto.randomUUID(),
    url,
    ...(str(raw.token) ? { token: raw.token as string } : {}),
    ...(scheme
      ? {
          authentication: {
            schemes: [scheme],
            ...(typeof auth?.credentials === "string" ? { credentials: auth.credentials } : {}),
          },
        }
      : {}),
    dialect: "1.0",
  };
}

/** 0.3 PushNotificationConfig (nested) -> stored config. */
function fromV03PushConfig(raw: Record<string, unknown>): PushNotificationConfig | string {
  const url = str(raw.url);
  if (!url) return "pushNotificationConfig.url is required";
  const auth = raw.authentication as PushNotificationConfig["authentication"] | undefined;
  return {
    id: str(raw.id) ?? crypto.randomUUID(),
    url,
    ...(str(raw.token) ? { token: raw.token as string } : {}),
    ...(auth && typeof auth === "object" && Array.isArray(auth.schemes)
      ? { authentication: auth }
      : {}),
    dialect: "0.3",
  };
}

// --------------------------------------------------------------------------
// Durable Object: the single source of truth for tasks + push configs.
//
// One global instance handles every request. State lives in the DO's
// transactional storage (key prefixes: `task:<id>` and `push:<taskId>`).
// No daily write caps; serializes concurrent updates per task.
// --------------------------------------------------------------------------

export class TaskRunnerDO implements DurableObject {
  private readonly state: DurableObjectState;
  private readonly env: Env;

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  // --- storage helpers ---

  private taskKey(id: string): string {
    return `task:${id}`;
  }

  private pushKey(taskId: string): string {
    return `push:${taskId}`;
  }

  private async getTask(id: string): Promise<Task | null> {
    return (await this.state.storage.get<Task>(this.taskKey(id))) ?? null;
  }

  private async putTask(task: Task): Promise<void> {
    await this.state.storage.put(this.taskKey(task.id), task);
  }

  /** Up to `max` stored tasks, newest first by status timestamp. */
  private async listTasks(max: number): Promise<Task[]> {
    const map = await this.state.storage.list<Task>({
      prefix: "task:",
      limit: max,
    });
    const out: Task[] = [];
    for (const v of map.values()) out.push(v);
    out.sort((a, b) => b.status.timestamp.localeCompare(a.status.timestamp));
    return out;
  }

  private async getPushConfigs(taskId: string): Promise<PushNotificationConfig[]> {
    return (await this.state.storage.get<PushNotificationConfig[]>(this.pushKey(taskId))) ?? [];
  }

  private async putPushConfigs(taskId: string, configs: PushNotificationConfig[]): Promise<void> {
    if (configs.length === 0) {
      await this.state.storage.delete(this.pushKey(taskId));
    } else {
      await this.state.storage.put(this.pushKey(taskId), configs);
    }
  }

  private async addPushConfig(taskId: string, cfg: PushNotificationConfig): Promise<void> {
    const existing = await this.getPushConfigs(taskId);
    await this.putPushConfigs(taskId, [...existing.filter((c) => c.id !== cfg.id), cfg]);
  }

  /**
   * Webhook delivery. A config registered over 1.0 receives a
   * StreamResponse (`{"task": ...}`, A2A 1.0 §4.3.3) with the token in
   * `X-A2A-Notification-Token` and `Authorization: <scheme>
   * <credentials>` when authentication is configured — the same
   * headers the a2a-sdk sender uses. Configs registered over 0.3 (or
   * stored before 1.0) keep receiving the bare Task as before.
   */
  private async firePushNotifications(task: Task): Promise<void> {
    const configs = await this.getPushConfigs(task.id);
    for (const cfg of configs) {
      const headers: Record<string, string> = {};
      let body: unknown;
      if (cfg.dialect === "1.0") {
        headers["content-type"] = "application/a2a+json";
        body = { task: v1Task(task) };
        if (cfg.token) headers["x-a2a-notification-token"] = cfg.token;
        const scheme = cfg.authentication?.schemes?.[0];
        if (scheme && cfg.authentication?.credentials) {
          headers.authorization = `${scheme} ${cfg.authentication.credentials}`;
        }
      } else {
        headers["content-type"] = "application/json";
        body = cfg.dialect === "0.3" ? v03Task(task) : task;
        if (cfg.token) headers.authorization = `Bearer ${cfg.token}`;
      }
      try {
        await fetch(cfg.url, { method: "POST", headers, body: JSON.stringify(body) });
      } catch {
        /* swallow — push delivery is best-effort */
      }
    }
  }

  // --- task construction + work simulation ---

  private makeTask(text: string, contextId?: string): Task {
    const id = crypto.randomUUID();
    const userMessage: Message = {
      messageId: crypto.randomUUID(),
      role: "user",
      parts: [{ kind: "text", text }],
      ...(contextId ? { contextId } : {}),
      taskId: id,
    };
    return {
      id,
      contextId: contextId ?? crypto.randomUUID(),
      status: { state: "TASK_STATE_SUBMITTED", timestamp: nowIso() },
      history: [userMessage],
      artifacts: [],
    };
  }

  private makeArtifact(index: number, total: number, text: string): ArtifactObj {
    return {
      artifactId: crypto.randomUUID(),
      name: `echo-${index}`,
      parts: [{ kind: "text", text: `unit ${index}/${total}: ${text}` }],
    };
  }

  private complete(task: Task, count: number): void {
    task.status = { state: "TASK_STATE_COMPLETED", timestamp: nowIso() };
    task.history.push({
      messageId: crypto.randomUUID(),
      role: "agent",
      parts: [{ kind: "text", text: `done: ${count} unit(s)` }],
      contextId: task.contextId,
      taskId: task.id,
    });
  }

  /**
   * Run the task's work units. `onEvent` receives each update as it
   * happens (streaming callers); every unit is persisted so GetTask /
   * SubscribeToTask observe progress mid-flight.
   */
  private async processTaskWork(
    task: Task,
    text: string,
    count: number,
    onEvent?: (e: StreamEvent) => void,
  ): Promise<void> {
    for (let i = 1; i <= count; i++) {
      await delay(50);
      const live = await this.getTask(task.id);
      if (live?.status.state === "TASK_STATE_CANCELED") {
        onEvent?.({ statusUpdate: { taskId: task.id, status: live.status } });
        return;
      }
      const artifact = this.makeArtifact(i, count, text);
      task.artifacts.push(artifact);
      await this.putTask(task);
      onEvent?.({ artifactUpdate: { taskId: task.id, artifact } });
    }
    this.complete(task, count);
    await this.putTask(task);
    onEvent?.({ statusUpdate: { taskId: task.id, status: task.status } });
    await this.firePushNotifications(task);
  }

  private sseStream(
    body: JsonRpcRequest,
    dialect: Dialect,
    contextId: string,
    run: (emit: (e: StreamEvent) => void) => Promise<void>,
  ): Response {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        // A2A 1.0 §9.4.2 (and 0.3): every SSE frame is a full JSON-RPC
        // response echoing the request id.
        // If the client disconnects, enqueue throws; keep running the
        // task (it must still reach a terminal state and fire webhooks)
        // and just stop writing to the stream.
        let open = true;
        const emit = (e: StreamEvent) => {
          if (!open) return;
          try {
            controller.enqueue(
              encoder.encode(
                sseEvent({
                  jsonrpc: "2.0",
                  id: body.id ?? null,
                  result: renderStreamEvent(dialect, e, contextId),
                }),
              ),
            );
          } catch {
            open = false;
          }
        };
        try {
          await run(emit);
        } finally {
          if (open) {
            try {
              controller.close();
            } catch {
              /* already closed by the client */
            }
          }
        }
      },
    });
    return new Response(stream, { status: 200, headers: SSE_HEADERS });
  }

  // --- method handlers (shared by both protocol versions) ---

  private async handleSend(
    body: JsonRpcRequest,
    dialect: Dialect,
    streaming: boolean,
  ): Promise<Response> {
    const params = (body.params ?? {}) as {
      message?: unknown;
      configuration?: Record<string, unknown>;
    };
    if (!params.message || typeof params.message !== "object") {
      return rpcError(body.id, "INVALID_PARAMS", "params.message is required", dialect);
    }
    const text = extractText(params.message);
    if (!text) {
      return rpcError(body.id, "INVALID_PARAMS", "no text part found in message.parts", dialect);
    }
    const cfg = params.configuration ?? {};
    // Inline push config: 1.0 configuration.taskPushNotificationConfig,
    // 0.3 configuration.pushNotificationConfig.
    let inlinePush: PushNotificationConfig | undefined;
    const rawPush = dialect === "1.0" ? cfg.taskPushNotificationConfig : cfg.pushNotificationConfig;
    if (rawPush && typeof rawPush === "object") {
      const parsed =
        dialect === "1.0"
          ? fromV1PushConfig(rawPush as Record<string, unknown>)
          : fromV03PushConfig(rawPush as Record<string, unknown>);
      if (typeof parsed === "string") {
        return rpcError(body.id, "INVALID_PARAMS", `push config: ${parsed}`, dialect);
      }
      inlinePush = parsed;
    }
    const max = parseInt(this.env.MAX_WORK_UNITS, 10) || 20;
    const count = parseCount(text, max);
    const contextId = str((params.message as { contextId?: unknown }).contextId);
    const historyLength = optInt(cfg.historyLength);

    const task = this.makeTask(text, contextId);
    task.status = { state: "TASK_STATE_WORKING", timestamp: nowIso() };
    await this.putTask(task);
    if (inlinePush) await this.addPushConfig(task.id, inlinePush);

    if (streaming) {
      return this.sseStream(body, dialect, task.contextId, async (emit) => {
        emit({ task: structuredClone(task) });
        await this.processTaskWork(task, text, count, emit);
      });
    }

    // Non-blocking: 1.0 returnImmediately=true, 0.3 blocking=false.
    const returnImmediately =
      dialect === "1.0" ? cfg.returnImmediately === true : cfg.blocking === false;
    if (returnImmediately) {
      // state.waitUntil keeps the DO alive to finish the work after
      // returning the WORKING task to the caller.
      this.state.waitUntil(this.processTaskWork(task, text, count));
      const rendered = renderTask(dialect, task, { historyLength });
      return rpcResult(body.id, dialect === "1.0" ? { task: rendered } : rendered);
    }
    await this.processTaskWork(task, text, count);
    const final = (await this.getTask(task.id)) ?? task;
    const rendered = renderTask(dialect, final, { historyLength });
    return rpcResult(body.id, dialect === "1.0" ? { task: rendered } : rendered);
  }

  private async handleGet(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const params = (body.params ?? {}) as { id?: unknown; historyLength?: unknown };
    const id = str(params.id);
    if (!id) return rpcError(body.id, "INVALID_PARAMS", "params.id is required", dialect);
    const task = await this.getTask(id);
    if (!task) return rpcError(body.id, "TASK_NOT_FOUND", `task ${id} not found`, dialect);
    return rpcResult(
      body.id,
      renderTask(dialect, task, { historyLength: optInt(params.historyLength) }),
    );
  }

  private async handleList(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const params = (body.params ?? {}) as Record<string, unknown>;
    const pageSize = optInt(params.pageSize) ?? 50;
    if (pageSize < 1 || pageSize > 100) {
      return rpcError(body.id, "INVALID_PARAMS", "pageSize must be between 1 and 100", dialect);
    }
    let offset = 0;
    if (str(params.pageToken)) {
      const n = optInt(params.pageToken);
      if (n === undefined || n < 0) {
        return rpcError(body.id, "INVALID_PARAMS", "invalid pageToken", dialect);
      }
      offset = n;
    }
    let tasks = await this.listTasks(LIST_SCAN_LIMIT);
    const contextId = str(params.contextId);
    if (contextId) tasks = tasks.filter((t) => t.contextId === contextId);
    const status = str(params.status);
    if (status && status !== "TASK_STATE_UNSPECIFIED") {
      tasks = tasks.filter((t) => t.status.state === status);
    }
    const page = tasks.slice(offset, offset + pageSize);
    const historyLength = optInt(params.historyLength);
    if (dialect === "0.3") {
      // Pre-1.0 extension shape served by earlier releases.
      return rpcResult(body.id, { tasks: page.map((t) => v03Task(t, { historyLength })) });
    }
    const includeArtifacts = params.includeArtifacts === true;
    return rpcResult(body.id, {
      tasks: page.map((t) => v1Task(t, { historyLength, includeArtifacts })),
      nextPageToken: offset + pageSize < tasks.length ? String(offset + pageSize) : "",
      pageSize,
      totalSize: tasks.length,
    });
  }

  private async handleCancel(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const params = (body.params ?? {}) as { id?: unknown };
    const id = str(params.id);
    if (!id) return rpcError(body.id, "INVALID_PARAMS", "params.id is required", dialect);
    const task = await this.getTask(id);
    if (!task) return rpcError(body.id, "TASK_NOT_FOUND", `task ${id} not found`, dialect);
    if (TERMINAL_STATES.has(task.status.state)) {
      return rpcError(
        body.id,
        "TASK_NOT_CANCELABLE",
        `task ${task.id} is in terminal state ${task.status.state}`,
        dialect,
      );
    }
    task.status = { state: "TASK_STATE_CANCELED", timestamp: nowIso() };
    await this.putTask(task);
    // Canceled is terminal: notify registered webhooks, as on completion.
    this.state.waitUntil(this.firePushNotifications(task));
    return rpcResult(body.id, renderTask(dialect, task));
  }

  /** Streams the current Task, then every subsequent artifact /
   *  status change until the task reaches a terminal state. */
  private async handleSubscribe(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const params = (body.params ?? {}) as { id?: unknown };
    const id = str(params.id);
    if (!id) return rpcError(body.id, "INVALID_PARAMS", "params.id is required", dialect);
    const initial = await this.getTask(id);
    if (!initial) return rpcError(body.id, "TASK_NOT_FOUND", `task ${id} not found`, dialect);
    if (TERMINAL_STATES.has(initial.status.state)) {
      // 1.0 §3.1.6: terminal tasks cannot be subscribed to. 0.3 clients
      // historically got a one-event snapshot; keep that for them.
      if (dialect === "1.0") {
        return rpcError(
          body.id,
          "UNSUPPORTED_OPERATION",
          `task ${initial.id} is in terminal state ${initial.status.state}`,
          dialect,
        );
      }
      return this.sseStream(body, dialect, initial.contextId, async (emit) => {
        emit({ task: initial });
      });
    }
    return this.sseStream(body, dialect, initial.contextId, async (emit) => {
      emit({ task: initial });
      let seen = initial.artifacts.length;
      const deadline = Date.now() + SUBSCRIBE_MAX_MS;
      while (Date.now() < deadline) {
        await delay(50);
        const live = await this.getTask(initial.id);
        if (!live) break;
        for (const artifact of live.artifacts.slice(seen)) {
          emit({ artifactUpdate: { taskId: live.id, artifact } });
        }
        seen = live.artifacts.length;
        if (TERMINAL_STATES.has(live.status.state)) {
          emit({ statusUpdate: { taskId: live.id, status: live.status } });
          break;
        }
      }
    });
  }

  private async handlePushSet(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const params = (body.params ?? {}) as Record<string, unknown>;
    const taskId = str(params.taskId);
    if (!taskId) return rpcError(body.id, "INVALID_PARAMS", "params.taskId is required", dialect);
    if (!(await this.getTask(taskId))) {
      return rpcError(body.id, "TASK_NOT_FOUND", `task ${taskId} not found`, dialect);
    }
    let parsed: PushNotificationConfig | string;
    if (dialect === "1.0") {
      parsed = fromV1PushConfig(params);
    } else {
      const inner = params.pushNotificationConfig;
      parsed =
        inner && typeof inner === "object"
          ? fromV03PushConfig(inner as Record<string, unknown>)
          : "params.pushNotificationConfig is required";
    }
    if (typeof parsed === "string") return rpcError(body.id, "INVALID_PARAMS", parsed, dialect);
    await this.addPushConfig(taskId, parsed);
    return rpcResult(
      body.id,
      dialect === "1.0" ? v1PushConfig(taskId, parsed) : v03PushConfig(taskId, parsed),
    );
  }

  /** Push get/list/delete address the task as `taskId` in 1.0 and as
   *  `id` in 0.3 (earlier releases of this agent also took `taskId`). */
  private pushTarget(params: Record<string, unknown>, dialect: Dialect) {
    return dialect === "1.0"
      ? { taskId: str(params.taskId), configId: str(params.id) }
      : {
          taskId: str(params.id) ?? str(params.taskId),
          configId: str(params.pushNotificationConfigId),
        };
  }

  private async handlePushGet(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const { taskId, configId } = this.pushTarget(
      (body.params ?? {}) as Record<string, unknown>,
      dialect,
    );
    if (!taskId) return rpcError(body.id, "INVALID_PARAMS", "task id is required", dialect);
    if (!(await this.getTask(taskId))) {
      return rpcError(body.id, "TASK_NOT_FOUND", `task ${taskId} not found`, dialect);
    }
    const configs = await this.getPushConfigs(taskId);
    // 1.0 requires the config id; 0.3 made it optional (first config).
    if (!configId && dialect === "1.0") {
      return rpcError(body.id, "INVALID_PARAMS", "params.id is required", dialect);
    }
    const cfg = configId ? configs.find((c) => c.id === configId) : configs[0];
    if (!cfg) {
      return rpcError(body.id, "TASK_NOT_FOUND", "push notification config not found", dialect);
    }
    return rpcResult(
      body.id,
      dialect === "1.0" ? v1PushConfig(taskId, cfg) : v03PushConfig(taskId, cfg),
    );
  }

  private async handlePushList(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const { taskId } = this.pushTarget((body.params ?? {}) as Record<string, unknown>, dialect);
    if (!taskId) return rpcError(body.id, "INVALID_PARAMS", "task id is required", dialect);
    if (!(await this.getTask(taskId))) {
      return rpcError(body.id, "TASK_NOT_FOUND", `task ${taskId} not found`, dialect);
    }
    const configs = await this.getPushConfigs(taskId);
    if (dialect === "0.3") {
      return rpcResult(
        body.id,
        configs.map((c) => v03PushConfig(taskId, c)),
      );
    }
    return rpcResult(body.id, {
      configs: configs.map((c) => v1PushConfig(taskId, c)),
      nextPageToken: "",
    });
  }

  private async handlePushDelete(body: JsonRpcRequest, dialect: Dialect): Promise<Response> {
    const { taskId, configId } = this.pushTarget(
      (body.params ?? {}) as Record<string, unknown>,
      dialect,
    );
    if (!taskId) return rpcError(body.id, "INVALID_PARAMS", "task id is required", dialect);
    if (!configId) return rpcError(body.id, "INVALID_PARAMS", "config id is required", dialect);
    const configs = await this.getPushConfigs(taskId);
    const remaining = configs.filter((c) => c.id !== configId);
    if (remaining.length === configs.length) {
      return rpcError(
        body.id,
        "TASK_NOT_FOUND",
        `push notification config ${configId} not found`,
        dialect,
      );
    }
    await this.putPushConfigs(taskId, remaining);
    return rpcResult(body.id, null);
  }

  private async dispatch(body: JsonRpcRequest, dialect: Dialect, op: Op): Promise<Response> {
    switch (op) {
      case "send":
        return this.handleSend(body, dialect, false);
      case "stream":
        return this.handleSend(body, dialect, true);
      case "get":
        return this.handleGet(body, dialect);
      case "list":
        return this.handleList(body, dialect);
      case "cancel":
        return this.handleCancel(body, dialect);
      case "subscribe":
        return this.handleSubscribe(body, dialect);
      case "push_set":
        return this.handlePushSet(body, dialect);
      case "push_get":
        return this.handlePushGet(body, dialect);
      case "push_list":
        return this.handlePushList(body, dialect);
      case "push_delete":
        return this.handlePushDelete(body, dialect);
      case "extended_card":
        // capabilities.extendedAgentCard is not declared (§3.3.4).
        return rpcError(
          body.id,
          "UNSUPPORTED_OPERATION",
          "this agent does not support an extended agent card",
          dialect,
        );
    }
  }

  // --- DO entry point ---

  async fetch(req: Request): Promise<Response> {
    let body: JsonRpcRequest;
    try {
      body = (await req.json()) as JsonRpcRequest;
    } catch {
      return rpcError(null, "JSON_PARSE_ERROR", "parse error: body is not JSON");
    }
    if (!body || typeof body !== "object" || body.jsonrpc !== "2.0") {
      return rpcError(body?.id, "INVALID_REQUEST", "invalid request: jsonrpc must be '2.0'");
    }
    const found = typeof body.method === "string" ? METHOD_LOOKUP.get(body.method) : undefined;
    if (!found) {
      return rpcError(body.id, "METHOD_NOT_FOUND", `method not found: ${String(body.method)}`);
    }
    const header = req.headers.get("a2a-version");
    const requested = requestedDialect(header);
    if (requested === null) {
      return rpcError(
        body.id,
        "VERSION_NOT_SUPPORTED",
        `A2A-Version ${header} is not supported; this agent serves 1.0 and 0.3`,
        found.dialect,
      );
    }
    // A 1.0 method under 0.3 semantics (no header, §3.6.2) does not exist.
    if (found.dialect === "1.0" && requested !== "1.0") {
      return rpcError(
        body.id,
        "VERSION_NOT_SUPPORTED",
        `${body.method} is an A2A 1.0 method; send the header A2A-Version: 1.0 ` +
          "(an absent header means 0.3, A2A 1.0 §3.6.2)",
      );
    }
    try {
      return await this.dispatch(body, found.dialect, found.op);
    } catch (err) {
      return rpcError(body.id, "INTERNAL_ERROR", (err as Error).message, found.dialect);
    }
  }
}

// --------------------------------------------------------------------------
// Worker entry point: thin router. CORS + per-IP rate limit happen
// here; everything else forwards to the DO. Splits responsibilities
// cleanly (network policy in the worker, business logic in the DO).
// --------------------------------------------------------------------------

const SINGLETON_NAME = "task-runner-singleton";

function withCors(resp: Response, origin: string | null): Response {
  const merged = new Headers(resp.headers);
  for (const [k, v] of Object.entries(corsHeaders(origin))) {
    merged.set(k, v);
  }
  return new Response(resp.body, {
    status: resp.status,
    statusText: resp.statusText,
    headers: merged,
  });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const selfUrl = `${url.protocol}//${url.host}`;
    const origin = req.headers.get("origin");

    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // AgentCard discovery. Same JSON for every caller, so we let
    // Cloudflare's edge cache it (s-maxage=300) and the browser
    // hold it briefly (max-age=60). Conformance correctness is
    // verified against the live JSON-RPC handlers, not this
    // static descriptor.
    if (
      req.method === "GET" &&
      (url.pathname === "/" || url.pathname === "/.well-known/agent-card.json")
    ) {
      return Response.json(buildAgentCard(selfUrl), {
        headers: {
          ...corsHeaders(origin),
          "cache-control": "public, max-age=60, s-maxage=300",
        },
      });
    }

    const isJsonRpcPath =
      url.pathname === "/" ||
      url.pathname === "" ||
      url.pathname === "/a2a/v1" ||
      url.pathname === "/a2a/v1/";
    if (req.method !== "POST" || !isJsonRpcPath) {
      return new Response("Not Found", {
        status: 404,
        headers: corsHeaders(origin),
      });
    }

    const ip = req.headers.get("cf-connecting-ip") ?? "unknown";
    const { success } = await env.TASK_RATE_LIMITER.limit({ key: ip });
    if (!success) {
      return withCors(
        Response.json(
          {
            jsonrpc: "2.0",
            id: null,
            error: { code: -32029, message: "rate limit exceeded — try again in a minute" },
          },
          { status: 429, headers: { "retry-after": "60" } },
        ),
        origin,
      );
    }

    const id = env.TASK_RUNNER.idFromName(SINGLETON_NAME);
    const stub = env.TASK_RUNNER.get(id);
    // Forward the body (and the version header the DO negotiates on).
    const bodyText = await req.text();
    const doHeaders: Record<string, string> = {
      "content-type": "application/json",
    };
    const a2aVersion = req.headers.get("a2a-version");
    if (a2aVersion) doHeaders["a2a-version"] = a2aVersion;
    const doResp = await stub.fetch("https://do.local/", {
      method: "POST",
      headers: doHeaders,
      body: bodyText,
    });
    return withCors(doResp, origin);
  },
} satisfies ExportedHandler<Env>;
