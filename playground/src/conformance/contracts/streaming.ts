// Streaming SSE + Subscribe-to-task + Push notification contracts.
// Browser-side mirror of the Python streaming_*.py / subscribe_*.py
// / push_*.py modules. Every probe goes through AgentProbe (the A2A
// version the card advertises); SSE frames are unwrapped from their
// JSON-RPC envelope and 0.3 events normalized to 1.0 StreamResponses.

import {
  pushDeleteParams,
  pushGetParams,
  pushListParams,
  pushSetParams,
  webhookTaskId,
} from '../dialect';
import type { Contract } from '../types';
import {
  AgentProbe,
  errorCode,
  LONG_TASK_TEXT,
  METHOD_NOT_FOUND_CODE,
  UNSUPPORTED_OPERATION_CODE,
} from './_probe';
import {
  freshToken,
  getPushReceiverBase,
  pushSkipDetail,
  readReceivedHooks,
  type SseEvent,
  SseFormatError,
  streamingSkipDetail,
} from './_streaming_helpers';
import {
  looksLikeTask,
  TASK_NOT_FOUND_CODE,
  type TaskShape,
  TERMINAL_TASK_STATES,
  VALID_TASK_STATES,
} from './_task_helpers';

const RPC_PATH = '/a2a/v1/';
const TS_VALID = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

function maybeAssert(cond: unknown, message: string): asserts cond {
  if (!cond) throw new Error(message);
}

/** Probe + streaming capability gate shared by the SSE contracts. */
async function streamingProbe(agentUrl: string): Promise<AgentProbe | string> {
  const probe = await AgentProbe.create(agentUrl);
  return streamingSkipDetail(probe.card) ?? probe;
}

async function streamSend(probe: AgentProbe, text: string): Promise<SseEvent[]> {
  return probe.stream('stream', probe.sendParams(text));
}

// ---------------------------------------------------------------------------
// Streaming SSE (§3.1.2, §4.1.6, §4.1.7, §9.4.2)
// ---------------------------------------------------------------------------

export const streamingResponseContentType: Contract = {
  id: 'transport.streaming_response_content_type',
  specSection: '§3.1.2',
  description: 'SendStreamingMessage returns Content-Type text/event-stream.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const res = await fetch(agentUrl.replace(/\/$/, '') + RPC_PATH, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...probe.headers() },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 'stream-ctype',
        method: probe.method('stream'),
        params: probe.sendParams('count: 1 ctype'),
      }),
    });
    res.body?.cancel();
    const ctype = res.headers.get('content-type') ?? '';
    maybeAssert(
      ctype.toLowerCase().includes('text/event-stream'),
      `${probe.method('stream')} MUST return text/event-stream; got ${ctype}`,
    );
  },
};

export const streamingJsonrpcFraming: Contract = {
  id: 'transport.streaming_jsonrpc_framing',
  specSection: '§9.4.2',
  description: 'Each SSE frame is a JSON-RPC response echoing the request id.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const requestId = 'sse-framing-probe';
    const frames = await probe.streamFrames(
      'stream',
      probe.sendParams('count: 2 framing'),
      requestId,
    );
    maybeAssert(frames.length > 0, `${probe.method('stream')} emitted no SSE events`);
    const offenders: string[] = [];
    frames.forEach((frame, i) => {
      if (frame.jsonrpc !== '2.0') {
        offenders.push(
          `frame[${i}] is not a JSON-RPC 2.0 response (keys ${Object.keys(frame).sort()})`,
        );
        return;
      }
      if (frame.id !== requestId) {
        offenders.push(`frame[${i}].id=${JSON.stringify(frame.id)} does not echo the request id`);
      }
      if ('result' in frame === 'error' in frame) {
        offenders.push(`frame[${i}] must carry exactly one of result / error`);
      }
    });
    maybeAssert(offenders.length === 0, offenders.slice(0, 5).join('; '));
  },
};

export const streamingFirstEventIsTask: Contract = {
  id: 'transport.streaming_first_event_is_task',
  specSection: '§3.1.2',
  description: 'First SSE event carries the Task (or the sole Message).',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const events = await streamSend(probe, 'count: 1 first-event');
    maybeAssert(events.length > 0, `${probe.method('stream')} emitted no events`);
    const first = events[0] ?? {};
    if (first.message && typeof first.message === 'object') {
      // Message-only stream (§3.1.2 pattern 1): exactly one Message.
      maybeAssert(
        events.length === 1,
        `message-only stream MUST contain exactly one Message and then close; got ${events.length} events`,
      );
      return 'message-only stream (agent answered with a Message, not a Task)';
    }
    maybeAssert(
      looksLikeTask(first.task),
      'first SSE event MUST carry the Task (`{"task": {...}}`) or, for a message-only stream, the Message',
    );
  },
};

const RECOGNIZED_KEYS = new Set(['task', 'message', 'statusUpdate', 'artifactUpdate']);

export const streamingEventKinds: Contract = {
  id: 'transport.streaming_event_kinds',
  specSection: '§3.1.2',
  description:
    'SSE events carry one StreamResponse member: task / message / statusUpdate / artifactUpdate.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const events = await streamSend(probe, 'count: 2 kinds');
    maybeAssert(events.length > 0, `${probe.method('stream')} emitted no SSE events`);
    const offenders: string[] = [];
    events.forEach((ev, i) => {
      if (!ev || typeof ev !== 'object') {
        offenders.push(`event[${i}] is not an object`);
        return;
      }
      if ('error' in ev) {
        offenders.push(`event[${i}] is a JSON-RPC error: ${JSON.stringify(ev.error)}`);
        return;
      }
      const keys = Object.keys(ev);
      if (keys.filter((k) => RECOGNIZED_KEYS.has(k)).length !== 1) {
        offenders.push(`event[${i}] keys=${keys}`);
      }
    });
    maybeAssert(offenders.length === 0, `events without exactly one kind: ${offenders.join('; ')}`);
  },
};

export const streamingStatusUpdateShape: Contract = {
  id: 'transport.streaming_status_update_shape',
  specSection: '§4.1.6',
  description: 'TaskStatusUpdateEvent carries taskId + status{state, timestamp}.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const events = await streamSend(probe, 'count: 1 status-shape');
    events.forEach((ev, i) => {
      if (!('statusUpdate' in ev)) return;
      const su = ev.statusUpdate as Record<string, unknown>;
      maybeAssert(
        typeof su === 'object' && su !== null,
        `event[${i}].statusUpdate MUST be an object`,
      );
      maybeAssert(
        typeof su.taskId === 'string' && su.taskId,
        `event[${i}].statusUpdate.taskId is REQUIRED`,
      );
      const status = su.status as Record<string, unknown>;
      maybeAssert(
        typeof status === 'object' && status !== null,
        `event[${i}].statusUpdate.status MUST be an object`,
      );
      const state = status.state;
      maybeAssert(
        typeof state === 'string' && VALID_TASK_STATES.has(state),
        `event[${i}].status.state ${JSON.stringify(state)} not in TaskState`,
      );
      const ts = status.timestamp;
      maybeAssert(
        typeof ts === 'string' && TS_VALID.test(ts),
        `event[${i}].status.timestamp MUST be ISO 8601 UTC; got ${JSON.stringify(ts)}`,
      );
    });
  },
};

export const streamingArtifactUpdateShape: Contract = {
  id: 'transport.streaming_artifact_update_shape',
  specSection: '§4.1.7',
  description: 'TaskArtifactUpdateEvent carries taskId + Artifact.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const events = await streamSend(probe, 'count: 2 artifacts');
    let seen = 0;
    events.forEach((ev, i) => {
      if (!('artifactUpdate' in ev)) return;
      seen += 1;
      const au = ev.artifactUpdate as Record<string, unknown>;
      maybeAssert(
        typeof au === 'object' && au !== null,
        `event[${i}].artifactUpdate MUST be an object`,
      );
      maybeAssert(
        typeof au.taskId === 'string' && au.taskId,
        `event[${i}].artifactUpdate.taskId is REQUIRED`,
      );
      const artifact = au.artifact as Record<string, unknown>;
      maybeAssert(
        typeof artifact === 'object' && artifact !== null,
        `event[${i}].artifactUpdate.artifact MUST be an object`,
      );
      maybeAssert(
        typeof artifact.artifactId === 'string' && artifact.artifactId,
        `event[${i}].artifact.artifactId is REQUIRED`,
      );
      const parts = artifact.parts as unknown[];
      maybeAssert(
        Array.isArray(parts) && parts.length > 0,
        `event[${i}].artifact.parts MUST be non-empty array`,
      );
    });
    if (seen === 0) {
      return 'agent streamed no artifactUpdate events for count=2 — skipped';
    }
  },
};

export const streamingTaskIdConsistency: Contract = {
  id: 'transport.streaming_task_id_consistency',
  specSection: '§3.1.2',
  description: 'All SSE events in one stream reference the same taskId.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const events = await streamSend(probe, 'count: 2 id-consistency');
    maybeAssert(events.length > 0, 'no events streamed');
    const first = events[0] ?? {};
    if ('message' in first) return 'skipped — message-only stream; no task id to keep consistent';
    const taskId = ((first as { task?: { id?: unknown } }).task?.id ?? null) as string | null;
    maybeAssert(typeof taskId === 'string' && taskId, 'first event must carry task.id');
    const offenders: string[] = [];
    events.slice(1).forEach((ev, i) => {
      const payload =
        (ev.statusUpdate as Record<string, unknown>) ??
        (ev.artifactUpdate as Record<string, unknown>) ??
        null;
      if (!payload) return;
      if (payload.taskId !== taskId) {
        offenders.push(
          `event[${i + 1}].taskId=${JSON.stringify(payload.taskId)} ≠ initial ${JSON.stringify(taskId)}`,
        );
      }
    });
    maybeAssert(offenders.length === 0, offenders.join('; '));
  },
};

export const streamingTerminalStateCloses: Contract = {
  id: 'transport.streaming_terminal_state_closes',
  specSection: '§3.1.2',
  description: 'SSE stream closes after a terminal-state statusUpdate.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const events = await streamSend(probe, 'count: 1 terminal');
    maybeAssert(events.length > 0, 'no events streamed');
    if ('message' in (events[0] ?? {})) {
      return 'skipped — message-only stream; no task lifecycle to close';
    }
    let lastStatusIndex = -1;
    let lastState: string | null = null;
    events.forEach((ev, i) => {
      if (!('statusUpdate' in ev)) return;
      const su = ev.statusUpdate as { status?: { state?: unknown } };
      lastState = typeof su.status?.state === 'string' ? su.status.state : null;
      lastStatusIndex = i;
    });
    maybeAssert(lastStatusIndex >= 0, 'stream emitted no terminal statusUpdate');
    maybeAssert(
      lastState !== null && TERMINAL_TASK_STATES.has(lastState),
      `last statusUpdate state ${JSON.stringify(lastState)} not terminal`,
    );
    maybeAssert(
      lastStatusIndex === events.length - 1,
      `${events.length - lastStatusIndex - 1} stray events after terminal status`,
    );
  },
};

// ---------------------------------------------------------------------------
// Subscribe-to-task (§3.1.6)
// ---------------------------------------------------------------------------

/** SubscribeToTask only applies to running tasks (terminal → -32004),
 *  so seed one that returns immediately and keeps working. */
async function runningTask(probe: AgentProbe): Promise<TaskShape | string> {
  const seed = await probe.sendForTask({ text: LONG_TASK_TEXT, blocking: false });
  if (!seed) return 'skipped — agent did not return a Task to subscribe to';
  if (TERMINAL_TASK_STATES.has(seed.status.state)) {
    return 'skipped — task was already terminal when the send returned; nothing to subscribe to';
  }
  return seed;
}

export const subscribeReturnsStream: Contract = {
  id: 'transport.subscribe_returns_stream',
  specSection: '§3.1.6',
  description: 'SubscribeToTask returns Content-Type text/event-stream.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const seed = await runningTask(probe);
    if (typeof seed === 'string') return seed;
    const res = await fetch(agentUrl.replace(/\/$/, '') + RPC_PATH, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...probe.headers() },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 'resub-ctype',
        method: probe.method('subscribe'),
        params: { id: seed.id },
      }),
    });
    const ctype = (res.headers.get('content-type') ?? '').toLowerCase();
    if (ctype.includes('text/event-stream')) {
      res.body?.cancel();
      return;
    }
    const raw = await res.text().catch(() => '');
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      /* not JSON */
    }
    if (errorCode(parsed) === UNSUPPORTED_OPERATION_CODE) {
      return 'skipped — task finished before the subscription was opened';
    }
    if (ctype.includes('application/json')) {
      return `${probe.method('subscribe')} returned application/json, not text/event-stream; spec mandates SSE`;
    }
    throw new Error(`${probe.method('subscribe')} returned unexpected content-type ${ctype}`);
  },
};

export const subscribeReplaysState: Contract = {
  id: 'transport.subscribe_replays_state',
  specSection: '§3.1.6',
  description: "SubscribeToTask first event reflects the subscribed task's state.",
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const seed = await runningTask(probe);
    if (typeof seed === 'string') return seed;
    let events: SseEvent[];
    try {
      events = await probe.stream('subscribe', { id: seed.id });
    } catch (err) {
      if (err instanceof SseFormatError) {
        return err.errorCode === UNSUPPORTED_OPERATION_CODE
          ? 'skipped — task finished before the subscription was opened'
          : `skipped — ${probe.method('subscribe')} did not return SSE`;
      }
      throw err;
    }
    maybeAssert(events.length > 0, `no events from ${probe.method('subscribe')}`);
    const first = events[0] ?? {};
    if (looksLikeTask(first.task)) {
      maybeAssert(first.task.id === seed.id, 'first event task.id ≠ subscribed id');
      return;
    }
    // 1.0 §3.1.6: "The operation MUST return a Task object as the first
    // event"; 0.3 agents could lead with a status update.
    const su = first.statusUpdate as Record<string, unknown> | undefined;
    if (su && probe.isLegacy) {
      maybeAssert(su.taskId === seed.id, 'first statusUpdate.taskId ≠ subscribed id');
      return;
    }
    throw new Error(`first ${probe.method('subscribe')} event MUST carry the Task (§3.1.6)`);
  },
};

export const subscribeNotFound: Contract = {
  id: 'transport.subscribe_not_found',
  specSection: '§3.1.6',
  description: 'SubscribeToTask on unknown id returns TaskNotFoundError.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await streamingProbe(agentUrl);
    if (typeof probe === 'string') return probe;
    const env = await probe.call('subscribe', { id: crypto.randomUUID() });
    const error = env.error as Record<string, unknown> | undefined;
    if (errorCode(env) === METHOD_NOT_FOUND_CODE) {
      return `skipped — agent does not implement ${probe.method('subscribe')} (-32601)`;
    }
    maybeAssert(
      Object.keys(env).length > 0,
      `${probe.method('subscribe')} for a bogus id did not return a JSON-RPC error envelope`,
    );
    if ('result' in env && !error) {
      throw new Error(`${probe.method('subscribe')} returned a result for bogus id`);
    }
    const code = error?.code;
    if (code === TASK_NOT_FOUND_CODE) return;
    return `agent rejected unknown id (good) but with code ${code}; spec mandates ${TASK_NOT_FOUND_CODE}`;
  },
};

export const subscribeCapabilityRequired: Contract = {
  id: 'transport.subscribe_capability_required',
  specSection: '§3.1.6',
  description: 'SubscribeToTask returns -32004 when streaming=false.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await AgentProbe.create(agentUrl);
    if (probe.capability('streaming') === true) {
      return 'skipped — agent advertises streaming=true (positive case)';
    }
    const env = await probe.call('subscribe', { id: crypto.randomUUID() });
    if ('result' in env && !env.error) {
      throw new Error(
        `agent advertises streaming=false but ${probe.method('subscribe')} returned a result`,
      );
    }
    const code = errorCode(env);
    if (code === UNSUPPORTED_OPERATION_CODE) return;
    return `capability honored — agent refused but with code ${code}; spec mandates -32004`;
  },
};

// ---------------------------------------------------------------------------
// Push notifications (§3.1.7–§3.1.10, §3.5)
// ---------------------------------------------------------------------------

/** Probe + push capability gate + a Task to attach configs to. */
async function pushSeed(
  agentUrl: string,
): Promise<{ probe: AgentProbe; seed: TaskShape } | string> {
  const probe = await AgentProbe.create(agentUrl);
  const skip = pushSkipDetail(probe.card);
  if (skip) return skip;
  const seed = await probe.sendForTask();
  if (!seed) return 'skipped — agent did not return a Task';
  return { probe, seed };
}

function notImplemented(
  probe: AgentProbe,
  env: Record<string, unknown>,
  op: 'push_set' | 'push_get' | 'push_list' | 'push_delete',
): string | null {
  return errorCode(env) === METHOD_NOT_FOUND_CODE
    ? `skipped — agent does not implement ${probe.method(op)} (-32601)`
    : null;
}

async function setPushConfig(
  probe: AgentProbe,
  taskId: string,
  url: string,
): Promise<{ id: string | null; skipped: string | null; cfg: Record<string, unknown> | null }> {
  const env = await probe.call('push_set', pushSetParams(probe.dialect, taskId, url));
  const skipped = notImplemented(probe, env, 'push_set');
  if (skipped) return { id: null, skipped, cfg: null };
  const cfg = probe.pushConfigOf(env.result);
  return { id: typeof cfg?.id === 'string' ? cfg.id : null, skipped: null, cfg };
}

function listedIds(configs: Array<Record<string, unknown>> | null): Set<string> {
  return new Set(
    (configs ?? []).map((c) => c?.id).filter((id): id is string => typeof id === 'string'),
  );
}

export const pushSetPersists: Contract = {
  id: 'transport.push_set_persists',
  specSection: '§3.1.7',
  description: 'CreateTaskPushNotificationConfig returns the stored config with id.',
  category: 'transport',
  async verify(agentUrl) {
    const ctx = await pushSeed(agentUrl);
    if (typeof ctx === 'string') return ctx;
    const url = `https://example.invalid/wh/${crypto.randomUUID()}`;
    const set = await setPushConfig(ctx.probe, ctx.seed.id, url);
    if (set.skipped) return set.skipped;
    maybeAssert(set.cfg, `${ctx.probe.method('push_set')} MUST return a result object`);
    maybeAssert(
      set.cfg.url === url,
      `set returned url ${JSON.stringify(set.cfg.url)}; expected ${JSON.stringify(url)}`,
    );
    maybeAssert(set.id, 'config id MUST be assigned');
  },
};

export const pushGetReturnsConfig: Contract = {
  id: 'transport.push_get_returns_config',
  specSection: '§3.1.8',
  description: 'GetTaskPushNotificationConfig retrieves the stored config.',
  category: 'transport',
  async verify(agentUrl) {
    const ctx = await pushSeed(agentUrl);
    if (typeof ctx === 'string') return ctx;
    const { probe, seed } = ctx;
    const url = `https://example.invalid/wh/${crypto.randomUUID()}`;
    const set = await setPushConfig(probe, seed.id, url);
    if (set.skipped) return set.skipped;
    if (!set.id) throw new Error('set did not return a config id');
    const env = await probe.call('push_get', pushGetParams(probe.dialect, seed.id, set.id));
    const skipped = notImplemented(probe, env, 'push_get');
    if (skipped) return skipped;
    const cfg = probe.pushConfigOf(env.result);
    maybeAssert(cfg, 'get MUST return the push notification config');
    maybeAssert(
      cfg.id === set.id,
      `get id ${JSON.stringify(cfg.id)} ≠ stored ${JSON.stringify(set.id)}`,
    );
    maybeAssert(
      cfg.url === url,
      `get url ${JSON.stringify(cfg.url)} ≠ stored ${JSON.stringify(url)}`,
    );
  },
};

export const pushListReturnsAll: Contract = {
  id: 'transport.push_list_returns_all',
  specSection: '§3.1.9',
  description: 'ListTaskPushNotificationConfigs returns every stored config.',
  category: 'transport',
  async verify(agentUrl) {
    const ctx = await pushSeed(agentUrl);
    if (typeof ctx === 'string') return ctx;
    const { probe, seed } = ctx;
    const ids: string[] = [];
    for (let i = 0; i < 2; i++) {
      const set = await setPushConfig(
        probe,
        seed.id,
        `https://example.invalid/wh/${crypto.randomUUID()}-${i}`,
      );
      if (set.skipped) return set.skipped;
      if (!set.id) throw new Error('set did not return id');
      ids.push(set.id);
    }
    const env = await probe.call('push_list', pushListParams(probe.dialect, seed.id));
    const skipped = notImplemented(probe, env, 'push_list');
    if (skipped) return skipped;
    const configs = probe.pushConfigListOf(env.result);
    maybeAssert(
      configs,
      `${probe.method('push_list')} MUST return the configs array (1.0: result.configs; 0.3: a bare array)`,
    );
    const listed = listedIds(configs);
    for (const id of ids) {
      maybeAssert(listed.has(id), `list omitted previously-set config ${id}`);
    }
  },
};

export const pushDeleteRemoves: Contract = {
  id: 'transport.push_delete_removes',
  specSection: '§3.1.10',
  description: 'DeleteTaskPushNotificationConfig removes the config from list.',
  category: 'transport',
  async verify(agentUrl) {
    const ctx = await pushSeed(agentUrl);
    if (typeof ctx === 'string') return ctx;
    const { probe, seed } = ctx;
    const set = await setPushConfig(
      probe,
      seed.id,
      `https://example.invalid/wh/${crypto.randomUUID()}`,
    );
    if (set.skipped) return set.skipped;
    if (!set.id) throw new Error('set did not return id');
    const del = await probe.call('push_delete', pushDeleteParams(probe.dialect, seed.id, set.id));
    const skipped = notImplemented(probe, del, 'push_delete');
    if (skipped) return skipped;
    maybeAssert(!del.error, `${probe.method('push_delete')} failed: ${JSON.stringify(del.error)}`);
    const list = await probe.call('push_list', pushListParams(probe.dialect, seed.id));
    if (errorCode(list) === METHOD_NOT_FOUND_CODE) return;
    maybeAssert(
      !listedIds(probe.pushConfigListOf(list.result)).has(set.id),
      `deleted config ${set.id} still in list response`,
    );
  },
};

async function expectPushTaskNotFound(
  agentUrl: string,
  op: 'push_set' | 'push_get',
): Promise<undefined | string> {
  const probe = await AgentProbe.create(agentUrl);
  const skip = pushSkipDetail(probe.card);
  if (skip) return skip;
  const bogus = crypto.randomUUID();
  const params =
    op === 'push_set'
      ? pushSetParams(probe.dialect, bogus, 'https://example.invalid/wh')
      : pushGetParams(probe.dialect, bogus, crypto.randomUUID());
  const env = await probe.call(op, params);
  const skipped = notImplemented(probe, env, op);
  if (skipped) return skipped;
  const error = env.error as Record<string, unknown> | undefined;
  if ('result' in env && !error) {
    throw new Error(`${probe.method(op)} returned a result for bogus taskId`);
  }
  if (error?.code === TASK_NOT_FOUND_CODE) return;
  return `agent rejected unknown taskId (good) but with code ${error?.code}; spec mandates ${TASK_NOT_FOUND_CODE}`;
}

export const pushSetTaskNotFound: Contract = {
  id: 'transport.push_set_task_not_found',
  specSection: '§3.1.7',
  description: 'CreateTaskPushNotificationConfig on unknown taskId returns TaskNotFoundError.',
  category: 'transport',
  verify: (agentUrl) => expectPushTaskNotFound(agentUrl, 'push_set'),
};

export const pushGetTaskNotFound: Contract = {
  id: 'transport.push_get_task_not_found',
  specSection: '§3.1.8',
  description: 'GetTaskPushNotificationConfig on unknown taskId returns TaskNotFoundError.',
  category: 'transport',
  verify: (agentUrl) => expectPushTaskNotFound(agentUrl, 'push_get'),
};

export const pushFiresOnCompletion: Contract = {
  id: 'transport.push_fires_on_completion',
  specSection: '§3.5',
  description: 'Agent POSTs a task update to a registered push URL on completion.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await AgentProbe.create(agentUrl);
    const skip = pushSkipDetail(probe.card);
    if (skip) return skip;
    const token = freshToken();
    const webhook = `${getPushReceiverBase()}/webhook/${token}`;
    // Non-blocking send so the agent returns before the task completes
    // and we have time to register the push config.
    const fresh = await probe.sendForTask({ text: 'count: 8 push', blocking: false });
    if (!fresh) return 'skipped — agent did not return a Task for a non-blocking send';
    if (TERMINAL_TASK_STATES.has(fresh.status.state)) {
      return 'skipped — agent ignored the non-blocking request (task already terminal)';
    }
    const set = await setPushConfig(probe, fresh.id, webhook);
    if (set.skipped) return set.skipped;
    // Poll the receiver up to 5s.
    const deadline = Date.now() + 5000;
    let hooks: Array<Record<string, unknown>> = [];
    while (Date.now() < deadline) {
      hooks = await readReceivedHooks(token);
      if (hooks.length > 0) break;
      await new Promise((r) => setTimeout(r, 250));
    }
    maybeAssert(
      hooks.length > 0,
      `no webhook fired within 5s; agent advertises pushNotifications=true`,
    );
    const first = hooks[0] ?? {};
    const body = typeof first.body === 'string' ? first.body : '';
    let payload: unknown = null;
    try {
      payload = JSON.parse(body);
    } catch {
      payload = null;
    }
    // 1.0 posts a StreamResponse (§4.3.3); 0.3 posted the bare Task.
    if (webhookTaskId(probe.dialect, payload) !== fresh.id) {
      return `webhook delivered but payload didn't carry the task id`;
    }
  },
};
