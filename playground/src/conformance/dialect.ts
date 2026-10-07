// A2A protocol dialects: 1.0 (current) and 0.3 (legacy).
// Browser-side mirror of `src/a2a_testbed/transport/dialect.py` —
// keep the two in step (tests/test_browser_parity.py checks the
// method tables).
//
// A2A 1.0 renamed every JSON-RPC method (`message/send` →
// `SendMessage`), switched payloads to the ProtoJSON rendering of
// a2a.proto (oneof Parts without `kind`, `ROLE_*` roles, `TASK_STATE_*`
// states, `{"task": ...}` send results, JSON-RPC-wrapped StreamResponse
// SSE frames) and introduced the `A2A-Version` header. The validator
// talks to each agent in the dialect its AgentCard advertises and
// normalizes 0.3 payloads into the 1.0 shape so every contract checks
// one canonical form; 1.0 payloads are never rewritten, so genuine 1.0
// violations still surface.

export type Dialect = '1.0' | '0.3';

export const CURRENT: Dialect = '1.0';
export const VERSION_HEADER = 'A2A-Version';

export type Op =
  | 'send'
  | 'stream'
  | 'get'
  | 'list'
  | 'cancel'
  | 'subscribe'
  | 'push_set'
  | 'push_get'
  | 'push_list'
  | 'push_delete'
  | 'extended_card';

export const METHODS: Record<Dialect, Record<Op, string>> = {
  '1.0': {
    send: 'SendMessage',
    stream: 'SendStreamingMessage',
    get: 'GetTask',
    list: 'ListTasks',
    cancel: 'CancelTask',
    subscribe: 'SubscribeToTask',
    push_set: 'CreateTaskPushNotificationConfig',
    push_get: 'GetTaskPushNotificationConfig',
    push_list: 'ListTaskPushNotificationConfigs',
    push_delete: 'DeleteTaskPushNotificationConfig',
    extended_card: 'GetExtendedAgentCard',
  },
  '0.3': {
    send: 'message/send',
    stream: 'message/stream',
    get: 'tasks/get',
    // Not in the 0.3 spec; a common pre-1.0 extension.
    list: 'tasks/list',
    cancel: 'tasks/cancel',
    subscribe: 'tasks/resubscribe',
    push_set: 'tasks/pushNotificationConfig/set',
    push_get: 'tasks/pushNotificationConfig/get',
    push_list: 'tasks/pushNotificationConfig/list',
    push_delete: 'tasks/pushNotificationConfig/delete',
    extended_card: 'agent/getAuthenticatedExtendedCard',
  },
};

export function method(dialect: Dialect, op: Op): string {
  return METHODS[dialect][op];
}

/** Headers a client sends with every request (1.0 MUST send
 *  A2A-Version; an absent header means 0.3, §3.6.2). */
export function requestHeaders(dialect: Dialect): Record<string, string> {
  return dialect === '1.0' ? { [VERSION_HEADER]: '1.0' } : {};
}

type Json = Record<string, unknown>;

function isObj(v: unknown): v is Json {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function major(version: unknown): number | null {
  const m = /^\s*(\d+)/.exec(typeof version === 'string' ? version : '');
  return m ? Number(m[1]) : null;
}

// ---------------------------------------------------------------------------
// Dialect detection from an AgentCard
// ---------------------------------------------------------------------------

/** True when a card uses the 0.3 layout. Without interfaces, only a
 *  0.x top-level protocolVersion (or none, next to a url) counts: a card
 *  claiming 1.0 in the old layout is a malformed 1.0 card. */
export function cardIsV03(card: unknown): boolean {
  if (!isObj(card)) return false;
  const ifaces = card.supportedInterfaces;
  if (Array.isArray(ifaces) && ifaces.length > 0) return false;
  if (card.protocolVersion !== undefined && card.protocolVersion !== null) {
    return typeof card.protocolVersion === 'string' && major(card.protocolVersion) === 0;
  }
  return 'url' in card;
}

/** Dialect for an agent: 1.0 unless the card positively says 0.3. */
export function detectDialect(card: unknown): Dialect {
  if (cardIsV03(card)) return '0.3';
  if (!isObj(card) || !Array.isArray(card.supportedInterfaces)) return CURRENT;
  const versions = card.supportedInterfaces
    .filter(
      (i): i is Json =>
        isObj(i) && String(i.protocolBinding ?? 'JSONRPC').toUpperCase() === 'JSONRPC',
    )
    .map((i) => i.protocolVersion);
  if (versions.length === 0) return CURRENT;
  if (versions.some((v) => !v || major(v) !== 0)) return '1.0';
  return '0.3';
}

/** A card in the 1.0 layout. 1.0 cards pass through untouched; 0.3
 *  cards get the same structural mapping the a2a-sdk compat layer
 *  applies (url / preferredTransport / protocolVersion →
 *  supportedInterfaces[0], additionalInterfaces → further entries,
 *  supportsAuthenticatedExtendedCard → capabilities.extendedAgentCard). */
export function cardToV10(card: unknown): Json {
  if (!isObj(card)) return {};
  if (!cardIsV03(card)) return card;
  const {
    url,
    preferredTransport,
    protocolVersion,
    additionalInterfaces,
    supportsAuthenticatedExtendedCard,
    ...rest
  } = card;
  const interfaces: Json[] = [
    {
      url,
      protocolBinding: preferredTransport ?? 'JSONRPC',
      protocolVersion: protocolVersion ?? '0.3',
    },
  ];
  if (Array.isArray(additionalInterfaces)) {
    for (const extra of additionalInterfaces) {
      if (isObj(extra)) {
        interfaces.push({
          url: extra.url,
          protocolBinding: extra.transport,
          protocolVersion: '0.3',
        });
      }
    }
  }
  const out: Json = { ...rest, supportedInterfaces: interfaces };
  if (supportsAuthenticatedExtendedCard !== undefined) {
    out.capabilities = {
      ...(isObj(rest.capabilities) ? rest.capabilities : {}),
      extendedAgentCard: supportsAuthenticatedExtendedCard,
    };
  }
  return out;
}

// ---------------------------------------------------------------------------
// Request builders
// ---------------------------------------------------------------------------

export interface MessageOpts {
  role?: 'user' | 'agent';
  messageId?: string;
  contextId?: string;
  taskId?: string;
}

export function textMessage(dialect: Dialect, text: string, opts: MessageOpts = {}): Json {
  const agent = opts.role === 'agent';
  const msg: Json = { messageId: opts.messageId ?? crypto.randomUUID() };
  if (dialect === '1.0') {
    msg.role = agent ? 'ROLE_AGENT' : 'ROLE_USER';
    msg.parts = [{ text }];
  } else {
    msg.kind = 'message';
    msg.role = agent ? 'agent' : 'user';
    msg.parts = [{ kind: 'text', text }];
  }
  if (opts.contextId !== undefined) msg.contextId = opts.contextId;
  if (opts.taskId !== undefined) msg.taskId = opts.taskId;
  return msg;
}

/** SendMessage params; `blocking: false` → 1.0 returnImmediately / 0.3 blocking=false. */
export function sendParams(dialect: Dialect, message: Json, blocking?: boolean): Json {
  const params: Json = { message };
  if (blocking !== undefined) {
    params.configuration = dialect === '1.0' ? { returnImmediately: !blocking } : { blocking };
  }
  return params;
}

export function pushSetParams(
  dialect: Dialect,
  taskId: string,
  url: string,
  opts: { token?: string; configId?: string } = {},
): Json {
  if (dialect === '1.0') {
    return {
      taskId,
      url,
      ...(opts.configId ? { id: opts.configId } : {}),
      ...(opts.token ? { token: opts.token } : {}),
    };
  }
  return {
    taskId,
    pushNotificationConfig: {
      url,
      ...(opts.configId ? { id: opts.configId } : {}),
      ...(opts.token ? { token: opts.token } : {}),
    },
  };
}

export function pushGetParams(dialect: Dialect, taskId: string, configId: string): Json {
  return dialect === '1.0'
    ? { taskId, id: configId }
    : { id: taskId, pushNotificationConfigId: configId };
}

export function pushListParams(dialect: Dialect, taskId: string): Json {
  return dialect === '1.0' ? { taskId } : { id: taskId };
}

export const pushDeleteParams = pushGetParams;

// ---------------------------------------------------------------------------
// 0.3 → 1.0 normalization (lenient: only rewrites values it recognizes)
// ---------------------------------------------------------------------------

const STATE_V03: Record<string, string> = {
  submitted: 'TASK_STATE_SUBMITTED',
  working: 'TASK_STATE_WORKING',
  'input-required': 'TASK_STATE_INPUT_REQUIRED',
  completed: 'TASK_STATE_COMPLETED',
  canceled: 'TASK_STATE_CANCELED',
  failed: 'TASK_STATE_FAILED',
  rejected: 'TASK_STATE_REJECTED',
  'auth-required': 'TASK_STATE_AUTH_REQUIRED',
  unknown: 'TASK_STATE_UNSPECIFIED',
};
const ROLE_V03: Record<string, string> = { user: 'ROLE_USER', agent: 'ROLE_AGENT' };

function without(obj: Json, ...keys: string[]): Json {
  const out: Json = {};
  for (const [k, v] of Object.entries(obj)) if (!keys.includes(k)) out[k] = v;
  return out;
}

export function normalizePart(part: unknown): unknown {
  if (!isObj(part) || !('kind' in part)) return part;
  let out: Json;
  if (part.kind === 'text') out = { text: part.text };
  else if (part.kind === 'data') out = { data: part.data };
  else if (part.kind === 'file') {
    const f = isObj(part.file) ? part.file : {};
    out = {};
    if ('uri' in f) out.url = f.uri;
    if ('bytes' in f) out.raw = f.bytes;
    if (f.mimeType) out.mediaType = f.mimeType;
    if (f.name) out.filename = f.name;
  } else out = without(part, 'kind');
  if ('metadata' in part) out.metadata = part.metadata;
  return out;
}

export function normalizeMessage(msg: unknown): unknown {
  if (!isObj(msg)) return msg;
  const out = without(msg, 'kind');
  if (typeof out.role === 'string') out.role = ROLE_V03[out.role] ?? out.role;
  if (Array.isArray(out.parts)) out.parts = out.parts.map(normalizePart);
  return out;
}

function normalizeArtifact(art: unknown): unknown {
  if (!isObj(art)) return art;
  const out = { ...art };
  if (Array.isArray(out.parts)) out.parts = out.parts.map(normalizePart);
  return out;
}

function normalizeStatus(status: unknown): unknown {
  if (!isObj(status)) return status;
  const out = { ...status };
  if (typeof out.state === 'string') out.state = STATE_V03[out.state] ?? out.state;
  if (isObj(out.message)) out.message = normalizeMessage(out.message);
  return out;
}

export function normalizeTask(task: unknown): unknown {
  if (!isObj(task)) return task;
  const out = without(task, 'kind');
  if ('status' in out) out.status = normalizeStatus(out.status);
  if (Array.isArray(out.history)) out.history = out.history.map(normalizeMessage);
  if (Array.isArray(out.artifacts)) out.artifacts = out.artifacts.map(normalizeArtifact);
  return out;
}

/** SendMessage result in the 1.0 `{task}` / `{message}` shape. */
export function normalizeSendResult(dialect: Dialect, result: unknown): unknown {
  if (dialect === '1.0' || !isObj(result)) return result;
  if ('task' in result || 'message' in result) return result;
  const kind = result.kind;
  if (
    kind === 'message' ||
    (kind === undefined && 'messageId' in result && !('status' in result))
  ) {
    return { message: normalizeMessage(result) };
  }
  return { task: normalizeTask(result) };
}

/** One SSE `result` as a 1.0 StreamResponse. */
export function normalizeStreamResult(dialect: Dialect, result: unknown): unknown {
  if (dialect === '1.0' || !isObj(result)) return result;
  if (['task', 'message', 'statusUpdate', 'artifactUpdate'].some((k) => k in result)) {
    const out = { ...result };
    if ('task' in out) out.task = normalizeTask(out.task);
    if ('message' in out) out.message = normalizeMessage(out.message);
    if (isObj(out.statusUpdate)) {
      const su = without(out.statusUpdate, 'kind', 'final');
      su.status = normalizeStatus(su.status);
      out.statusUpdate = su;
    }
    if (isObj(out.artifactUpdate)) {
      const au = without(out.artifactUpdate, 'kind');
      au.artifact = normalizeArtifact(au.artifact);
      out.artifactUpdate = au;
    }
    return out;
  }
  if (result.kind === 'status-update') {
    const su = without(result, 'kind', 'final');
    su.status = normalizeStatus(su.status);
    return { statusUpdate: su };
  }
  if (result.kind === 'artifact-update') {
    const au = without(result, 'kind');
    au.artifact = normalizeArtifact(au.artifact);
    return { artifactUpdate: au };
  }
  if (result.kind === 'message') return { message: normalizeMessage(result) };
  return { task: normalizeTask(result) };
}

/** A parsed SSE `data:` payload as a 1.0 StreamResponse (error frames →
 *  `{error}`; bare frames tolerated — streaming_jsonrpc_framing flags them). */
export function unwrapStreamFrame(dialect: Dialect, frame: unknown): unknown {
  if (!isObj(frame)) return frame;
  if ('jsonrpc' in frame || ('id' in frame && ('result' in frame || 'error' in frame))) {
    if (frame.error != null) return { error: frame.error };
    return normalizeStreamResult(dialect, frame.result);
  }
  return normalizeStreamResult(dialect, frame);
}

/** Push-config result as a flat 1.0 TaskPushNotificationConfig. */
export function normalizePushConfig(dialect: Dialect, cfg: unknown): Json | null {
  if (!isObj(cfg)) return null;
  if (dialect === '1.0' || !isObj(cfg.pushNotificationConfig)) return cfg;
  const inner = cfg.pushNotificationConfig;
  const out: Json = { taskId: cfg.taskId };
  for (const key of ['id', 'url', 'token']) if (key in inner) out[key] = inner[key];
  if (isObj(inner.authentication)) {
    const schemes = Array.isArray(inner.authentication.schemes) ? inner.authentication.schemes : [];
    out.authentication = {
      ...(schemes.length ? { scheme: schemes[0] } : {}),
      ...(inner.authentication.credentials
        ? { credentials: inner.authentication.credentials }
        : {}),
    };
  }
  return out;
}

/** Push-config list result as an array of flat configs (null if unrecognized). */
export function normalizePushConfigList(dialect: Dialect, result: unknown): Json[] | null {
  if (dialect === '1.0') {
    if (!isObj(result)) return null;
    const configs = result.configs ?? []; // ProtoJSON omits empty repeated fields
    return Array.isArray(configs) ? (configs as Json[]) : null;
  }
  if (Array.isArray(result)) {
    return result.map((c) => normalizePushConfig(dialect, c)).filter((c): c is Json => c !== null);
  }
  if (isObj(result)) {
    if (Array.isArray(result.pushNotificationConfigs))
      return result.pushNotificationConfigs as Json[];
    if (Array.isArray(result.configs)) return result.configs as Json[];
  }
  return null;
}

/** Task id a push-notification body refers to (1.0 StreamResponse or 0.3 bare Task). */
export function webhookTaskId(dialect: Dialect, payload: unknown): string | null {
  const ev = normalizeStreamResult(dialect, payload);
  if (!isObj(ev)) return null;
  if (isObj(ev.task)) return typeof ev.task.id === 'string' ? ev.task.id : null;
  for (const key of ['statusUpdate', 'artifactUpdate', 'message']) {
    const v = ev[key];
    if (isObj(v)) return typeof v.taskId === 'string' ? v.taskId : null;
  }
  return null;
}
