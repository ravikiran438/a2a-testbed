/**
 * A2A 1.0 reference task runner.
 *
 * Implements every Task / GetTask / ListTasks / CancelTask /
 * SubscribeToTask / PushNotificationConfig method the A2A spec
 * defines, against an in-memory work simulator. Tasks "do work"
 * by emitting N status updates spaced 50ms apart; the input text
 * may carry a leading integer to choose N (default 5, capped at
 * MAX_WORK_UNITS).
 *
 * Storage: a single global Durable Object (`TaskRunnerDO`) owns
 * every task + push config. Routing all requests to one DO keeps
 * the access pattern serialized and avoids KV's daily write cap —
 * DO storage has no per-day cap; only per-instance request rate
 * limits (effectively unbounded for a demo at this scale).
 */

interface Env {
  TASK_RUNNER: DurableObjectNamespace;
  TASK_RATE_LIMITER: {
    limit: (opts: { key: string }) => Promise<{ success: boolean }>;
  };
  MAX_WORK_UNITS: string;
}

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
}

interface JsonRpcRequest {
  jsonrpc?: string;
  id?: string | number | null;
  method?: string;
  params?: unknown;
}

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
    "access-control-allow-headers": "content-type",
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
      "A2A 1.0 reference agent exercising the full task lifecycle: " +
      "Tasks via message/send, SSE streaming via message/stream, " +
      "tasks/get/list/cancel, tasks/resubscribe, and " +
      "tasks/pushNotificationConfig/{set,get,list,delete}. " +
      "Echoes input back over N work units (default 5; client may " +
      "send 'count: N' to override).",
    version: "1.0.0",
    supportedInterfaces: [
      { url: selfUrl, protocolBinding: "JSONRPC", protocolVersion: "1.0" },
    ],
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
// JSON-RPC helpers (used by the DO; CORS headers are added by the
// outer worker after the DO returns).
// --------------------------------------------------------------------------

function rpcResult(
  id: string | number | null | undefined,
  result: unknown,
): Response {
  return Response.json({ jsonrpc: "2.0", id: id ?? null, result });
}

function rpcError(
  id: string | number | null | undefined,
  code: number,
  message: string,
): Response {
  return Response.json({
    jsonrpc: "2.0",
    id: id ?? null,
    error: { code, message },
  });
}

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

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

  private async listTasks(max = 50): Promise<Task[]> {
    const map = await this.state.storage.list<Task>({
      prefix: "task:",
      limit: max,
    });
    const out: Task[] = [];
    for (const v of map.values()) out.push(v);
    out.sort((a, b) => b.status.timestamp.localeCompare(a.status.timestamp));
    return out;
  }

  private async getPushConfigs(
    taskId: string,
  ): Promise<PushNotificationConfig[]> {
    return (
      (await this.state.storage.get<PushNotificationConfig[]>(
        this.pushKey(taskId),
      )) ?? []
    );
  }

  private async putPushConfigs(
    taskId: string,
    configs: PushNotificationConfig[],
  ): Promise<void> {
    if (configs.length === 0) {
      await this.state.storage.delete(this.pushKey(taskId));
    } else {
      await this.state.storage.put(this.pushKey(taskId), configs);
    }
  }

  private async firePushNotifications(task: Task): Promise<void> {
    const configs = await this.getPushConfigs(task.id);
    for (const cfg of configs) {
      const init: RequestInit = {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(task),
      };
      if (cfg.token) {
        (init.headers as Record<string, string>)["authorization"] =
          `Bearer ${cfg.token}`;
      }
      try {
        await fetch(cfg.url, init);
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

  private async processTaskWork(
    task: Task,
    text: string,
    count: number,
  ): Promise<void> {
    for (let i = 1; i <= count; i++) {
      await delay(50);
      const live = await this.getTask(task.id);
      if (live?.status.state === "TASK_STATE_CANCELED") return;
      task.artifacts.push(this.makeArtifact(i, count, text));
    }
    task.status = { state: "TASK_STATE_COMPLETED", timestamp: nowIso() };
    task.history.push({
      messageId: crypto.randomUUID(),
      role: "agent",
      parts: [{ kind: "text", text: `done: ${count} unit(s)` }],
      contextId: task.contextId,
      taskId: task.id,
    });
    await this.putTask(task);
    await this.firePushNotifications(task);
  }

  // --- method handlers ---

  private async handleMessageSend(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as {
      message?: unknown;
      configuration?: { blocking?: unknown };
    };
    const text = extractText(params.message);
    if (!text) {
      return rpcError(
        body.id,
        -32602,
        "invalid params: no text part found in message.parts",
      );
    }
    const max = parseInt(this.env.MAX_WORK_UNITS, 10) || 20;
    const count = parseCount(text, max);
    const requestedContextId = (params.message as { contextId?: unknown })
      ?.contextId;
    const contextId =
      typeof requestedContextId === "string" && requestedContextId
        ? requestedContextId
        : undefined;

    const task = this.makeTask(text, contextId);
    task.status = { state: "TASK_STATE_WORKING", timestamp: nowIso() };
    await this.putTask(task);

    const blocking = (params.configuration?.blocking ?? true) !== false;
    if (!blocking) {
      // ctx.waitUntil wired through state.waitUntil — keeps the DO
      // alive long enough to finish the work after returning the
      // SUBMITTED task to the caller.
      this.state.waitUntil(this.processTaskWork(task, text, count));
      return rpcResult(body.id, task);
    }

    await this.processTaskWork(task, text, count);
    const final = (await this.getTask(task.id)) ?? task;
    return rpcResult(body.id, final);
  }

  private async handleMessageStream(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as { message?: unknown };
    const text = extractText(params.message);
    if (!text) {
      return rpcError(
        body.id,
        -32602,
        "invalid params: no text part found in message.parts",
      );
    }
    const max = parseInt(this.env.MAX_WORK_UNITS, 10) || 20;
    const count = parseCount(text, max);
    const requestedContextId = (params.message as { contextId?: unknown })
      ?.contextId;
    const contextId =
      typeof requestedContextId === "string" && requestedContextId
        ? requestedContextId
        : undefined;

    const task = this.makeTask(text, contextId);
    task.status = { state: "TASK_STATE_WORKING", timestamp: nowIso() };
    await this.putTask(task);

    const encoder = new TextEncoder();
    const self = this;
    const stream = new ReadableStream({
      async start(controller) {
        controller.enqueue(encoder.encode(sseEvent({ task })));
        for (let i = 1; i <= count; i++) {
          await delay(50);
          const live = await self.getTask(task.id);
          if (live?.status.state === "TASK_STATE_CANCELED") {
            controller.enqueue(
              encoder.encode(
                sseEvent({
                  statusUpdate: { taskId: task.id, status: live.status },
                }),
              ),
            );
            controller.close();
            return;
          }
          const artifact = self.makeArtifact(i, count, text);
          task.artifacts.push(artifact);
          await self.putTask(task);
          controller.enqueue(
            encoder.encode(
              sseEvent({ artifactUpdate: { taskId: task.id, artifact } }),
            ),
          );
        }
        task.status = { state: "TASK_STATE_COMPLETED", timestamp: nowIso() };
        task.history.push({
          messageId: crypto.randomUUID(),
          role: "agent",
          parts: [{ kind: "text", text: `done: ${count} unit(s)` }],
          contextId: task.contextId,
          taskId: task.id,
        });
        await self.putTask(task);
        controller.enqueue(
          encoder.encode(
            sseEvent({
              statusUpdate: { taskId: task.id, status: task.status },
            }),
          ),
        );
        controller.close();
        await self.firePushNotifications(task);
      },
    });
    return new Response(stream, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
      },
    });
  }

  private async handleTasksGet(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as { id?: unknown };
    if (typeof params.id !== "string" || !params.id) {
      return rpcError(body.id, -32602, "params.id is required");
    }
    const task = await this.getTask(params.id);
    if (!task) return rpcError(body.id, -32001, "task not found");
    return rpcResult(body.id, task);
  }

  private async handleTasksList(body: JsonRpcRequest): Promise<Response> {
    const tasks = await this.listTasks();
    return rpcResult(body.id, { tasks });
  }

  private async handleTasksCancel(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as { id?: unknown };
    if (typeof params.id !== "string" || !params.id) {
      return rpcError(body.id, -32602, "params.id is required");
    }
    const task = await this.getTask(params.id);
    if (!task) return rpcError(body.id, -32001, "task not found");
    if (TERMINAL_STATES.has(task.status.state)) {
      return rpcResult(body.id, task);
    }
    task.status = { state: "TASK_STATE_CANCELED", timestamp: nowIso() };
    await this.putTask(task);
    return rpcResult(body.id, task);
  }

  private async handleTasksResubscribe(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as { id?: unknown };
    if (typeof params.id !== "string" || !params.id) {
      return rpcError(body.id, -32602, "params.id is required");
    }
    const task = await this.getTask(params.id);
    if (!task) return rpcError(body.id, -32001, "task not found");
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(sseEvent({ task })));
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
      },
    });
  }

  private async handlePushSet(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as {
      taskId?: unknown;
      pushNotificationConfig?: unknown;
    };
    if (typeof params.taskId !== "string" || !params.taskId) {
      return rpcError(body.id, -32602, "params.taskId is required");
    }
    const task = await this.getTask(params.taskId);
    if (!task) return rpcError(body.id, -32001, "task not found");
    const cfg = params.pushNotificationConfig as Record<string, unknown> | null;
    if (!cfg || typeof cfg !== "object") {
      return rpcError(
        body.id,
        -32602,
        "params.pushNotificationConfig is required",
      );
    }
    if (typeof cfg.url !== "string" || !cfg.url) {
      return rpcError(
        body.id,
        -32602,
        "params.pushNotificationConfig.url is required",
      );
    }
    const stored: PushNotificationConfig = {
      id: typeof cfg.id === "string" && cfg.id ? cfg.id : crypto.randomUUID(),
      url: cfg.url,
      ...(typeof cfg.token === "string" ? { token: cfg.token } : {}),
      ...(cfg.authentication && typeof cfg.authentication === "object"
        ? {
            authentication:
              cfg.authentication as PushNotificationConfig["authentication"],
          }
        : {}),
    };
    const existing = await this.getPushConfigs(params.taskId);
    const without = existing.filter((c) => c.id !== stored.id);
    without.push(stored);
    await this.putPushConfigs(params.taskId, without);
    return rpcResult(body.id, {
      taskId: params.taskId,
      pushNotificationConfig: stored,
    });
  }

  private async handlePushGet(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as {
      taskId?: unknown;
      pushNotificationConfigId?: unknown;
    };
    if (typeof params.taskId !== "string" || !params.taskId) {
      return rpcError(body.id, -32602, "params.taskId is required");
    }
    const configs = await this.getPushConfigs(params.taskId);
    if (typeof params.pushNotificationConfigId === "string") {
      const cfg = configs.find(
        (c) => c.id === params.pushNotificationConfigId,
      );
      if (!cfg) {
        return rpcError(
          body.id,
          -32001,
          "push notification config not found",
        );
      }
      return rpcResult(body.id, {
        taskId: params.taskId,
        pushNotificationConfig: cfg,
      });
    }
    if (configs.length === 0) {
      return rpcError(body.id, -32001, "no push notification config for task");
    }
    return rpcResult(body.id, {
      taskId: params.taskId,
      pushNotificationConfig: configs[0],
    });
  }

  private async handlePushList(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as { taskId?: unknown };
    if (typeof params.taskId !== "string" || !params.taskId) {
      return rpcError(body.id, -32602, "params.taskId is required");
    }
    const configs = await this.getPushConfigs(params.taskId);
    return rpcResult(body.id, {
      taskId: params.taskId,
      pushNotificationConfigs: configs,
    });
  }

  private async handlePushDelete(body: JsonRpcRequest): Promise<Response> {
    const params = (body.params ?? {}) as {
      taskId?: unknown;
      pushNotificationConfigId?: unknown;
    };
    if (typeof params.taskId !== "string" || !params.taskId) {
      return rpcError(body.id, -32602, "params.taskId is required");
    }
    const configs = await this.getPushConfigs(params.taskId);
    if (typeof params.pushNotificationConfigId === "string") {
      const remaining = configs.filter(
        (c) => c.id !== params.pushNotificationConfigId,
      );
      if (remaining.length === configs.length) {
        return rpcError(
          body.id,
          -32001,
          "push notification config not found",
        );
      }
      await this.putPushConfigs(params.taskId, remaining);
    } else {
      await this.putPushConfigs(params.taskId, []);
    }
    return rpcResult(body.id, {});
  }

  // --- DO entry point ---

  async fetch(req: Request): Promise<Response> {
    let body: JsonRpcRequest;
    try {
      body = (await req.json()) as JsonRpcRequest;
    } catch {
      return rpcError(null, -32700, "parse error: body is not JSON");
    }
    if (body.jsonrpc !== "2.0") {
      return rpcError(
        body.id,
        -32600,
        "invalid request: jsonrpc must be '2.0'",
      );
    }
    try {
      switch (body.method) {
        case "message/send":
          return await this.handleMessageSend(body);
        case "message/stream":
          return await this.handleMessageStream(body);
        case "tasks/get":
          return await this.handleTasksGet(body);
        case "tasks/list":
          return await this.handleTasksList(body);
        case "tasks/cancel":
          return await this.handleTasksCancel(body);
        case "tasks/resubscribe":
          return await this.handleTasksResubscribe(body);
        case "tasks/pushNotificationConfig/set":
          return await this.handlePushSet(body);
        case "tasks/pushNotificationConfig/get":
          return await this.handlePushGet(body);
        case "tasks/pushNotificationConfig/list":
          return await this.handlePushList(body);
        case "tasks/pushNotificationConfig/delete":
          return await this.handlePushDelete(body);
        default:
          return rpcError(
            body.id,
            -32601,
            `method not implemented: ${String(body.method)}`,
          );
      }
    } catch (err) {
      return rpcError(body.id, -32000, (err as Error).message);
    }
  }
}

// --------------------------------------------------------------------------
// Worker entry point: thin router. CORS + per-IP rate limit happen
// here; everything else forwards to the DO. Splits responsibilities
// cleanly (network policy in the worker, business logic in the DO).
// --------------------------------------------------------------------------

const SINGLETON_NAME = "task-runner-singleton";

function withCors(
  resp: Response,
  origin: string | null,
): Response {
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

    if (
      req.method === "GET" &&
      (url.pathname === "/" ||
        url.pathname === "/.well-known/agent-card.json")
    ) {
      return Response.json(buildAgentCard(selfUrl), {
        headers: corsHeaders(origin),
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
      const errResp = rpcError(
        null,
        -32029,
        "rate limit exceeded — try again in a minute",
      );
      return withCors(
        new Response(errResp.body, {
          status: 429,
          headers: { ...errResp.headers, "retry-after": "60" },
        }),
        origin,
      );
    }

    const id = env.TASK_RUNNER.idFromName(SINGLETON_NAME);
    const stub = env.TASK_RUNNER.get(id);
    // Forward the body to the DO; the DO does its own JSON-RPC
    // dispatch + storage. We reconstruct the request because the
    // original body has already been consumed if anything along the
    // way read it (currently nothing does, but explicit > implicit).
    const bodyText = await req.text();
    const doResp = await stub.fetch("https://do.local/", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: bodyText,
    });
    return withCors(doResp, origin);
  },
} satisfies ExportedHandler<Env>;
