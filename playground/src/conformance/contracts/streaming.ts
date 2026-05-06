// Streaming SSE + Subscribe-to-task + Push notification contracts.
// Browser-side mirror of the Python streaming_*.py /  subscribe_*.py
// /  push_*.py modules.

import type { Contract } from '../types';
import { TASK_NOT_FOUND_CODE, TERMINAL_TASK_STATES, VALID_TASK_STATES, looksLikeTask, probeForTask } from './_task_helpers';
import {
  PUSH_RECEIVER_BASE,
  SseFormatError,
  callMethod,
  fetchCardJson,
  freshToken,
  pushSkipDetail,
  readReceivedHooks,
  streamSseEvents,
  streamingSkipDetail,
} from './_streaming_helpers';

const RPC_PATH = '/a2a/v1/';
const TS_VALID = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

function maybeAssert(cond: unknown, message: string): asserts cond {
  if (!cond) throw new Error(message);
}

// ---------------------------------------------------------------------------
// Streaming SSE (§3.1.2, §4.1.6, §4.1.7)
// ---------------------------------------------------------------------------

async function probeStreamMessage(text: string) {
  return {
    message: {
      messageId: 'sse-probe-' + Math.random().toString(36).slice(2, 10),
      role: 'user',
      parts: [{ kind: 'text', text }],
    },
  };
}

export const streamingResponseContentType: Contract = {
  id: 'transport.streaming_response_content_type',
  specSection: '§3.1.2',
  description:
    'message/stream returns Content-Type text/event-stream.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const url = agentUrl.replace(/\/$/, '') + RPC_PATH;
    const req = {
      jsonrpc: '2.0',
      id: 'stream-ctype',
      method: 'message/stream',
      params: await probeStreamMessage('count: 1 ctype'),
    };
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(req),
    });
    res.body?.cancel();
    const ctype = res.headers.get('content-type') ?? '';
    maybeAssert(
      ctype.toLowerCase().includes('text/event-stream'),
      `message/stream MUST return text/event-stream; got ${ctype}`,
    );
  },
};

export const streamingFirstEventIsTask: Contract = {
  id: 'transport.streaming_first_event_is_task',
  specSection: '§3.1.2',
  description:
    'First SSE event of message/stream carries the Task envelope.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const events = await streamSseEvents(
      agentUrl,
      'message/stream',
      await probeStreamMessage('count: 1 first-event'),
    );
    maybeAssert(events.length > 0, 'message/stream emitted no events');
    const first = events[0] ?? {};
    const task = (first as { task?: unknown }).task;
    maybeAssert(
      looksLikeTask(task),
      'first SSE event MUST carry a `task` envelope',
    );
  },
};

const RECOGNIZED_KEYS = new Set(['task', 'statusUpdate', 'artifactUpdate']);

export const streamingEventKinds: Contract = {
  id: 'transport.streaming_event_kinds',
  specSection: '§3.1.2',
  description: 'SSE events carry task / statusUpdate / artifactUpdate.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const events = await streamSseEvents(
      agentUrl,
      'message/stream',
      await probeStreamMessage('count: 2 kinds'),
    );
    const offenders: string[] = [];
    events.forEach((ev, i) => {
      const keys = new Set(Object.keys(ev));
      const intersect = [...keys].filter((k) => RECOGNIZED_KEYS.has(k));
      if (intersect.length === 0) {
        offenders.push(`event[${i}] keys=${[...keys]}`);
      }
    });
    maybeAssert(
      offenders.length === 0,
      `events with no recognized kind: ${offenders.join('; ')}`,
    );
  },
};

export const streamingStatusUpdateShape: Contract = {
  id: 'transport.streaming_status_update_shape',
  specSection: '§4.1.6',
  description:
    'TaskStatusUpdateEvent carries taskId + status{state, timestamp}.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const events = await streamSseEvents(
      agentUrl,
      'message/stream',
      await probeStreamMessage('count: 1 status-shape'),
    );
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
  description:
    'TaskArtifactUpdateEvent carries taskId + Artifact.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const events = await streamSseEvents(
      agentUrl,
      'message/stream',
      await probeStreamMessage('count: 2 artifacts'),
    );
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
  description:
    'All SSE events in one stream reference the same taskId.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const events = await streamSseEvents(
      agentUrl,
      'message/stream',
      await probeStreamMessage('count: 2 id-consistency'),
    );
    maybeAssert(events.length > 0, 'no events streamed');
    const first = events[0] ?? {};
    const taskId = (((first as { task?: { id?: unknown } }).task ?? {}).id ?? null) as string | null;
    maybeAssert(
      typeof taskId === 'string' && taskId,
      'first event must carry task.id',
    );
    const offenders: string[] = [];
    events.slice(1).forEach((ev, i) => {
      const payload =
        (ev.statusUpdate as Record<string, unknown>) ??
        (ev.artifactUpdate as Record<string, unknown>) ??
        null;
      if (!payload) return;
      const seen = payload.taskId;
      if (seen !== taskId) {
        offenders.push(
          `event[${i + 1}].taskId=${JSON.stringify(seen)} ≠ initial ${JSON.stringify(taskId)}`,
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
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const events = await streamSseEvents(
      agentUrl,
      'message/stream',
      await probeStreamMessage('count: 1 terminal'),
    );
    maybeAssert(events.length > 0, 'no events streamed');
    let lastStatusIndex = -1;
    let lastState: string | null = null;
    events.forEach((ev, i) => {
      if (!('statusUpdate' in ev)) return;
      const su = ev.statusUpdate as { status?: { state?: unknown } };
      lastState =
        typeof su.status?.state === 'string' ? su.status.state : null;
      lastStatusIndex = i;
    });
    maybeAssert(
      lastStatusIndex >= 0,
      'stream emitted no terminal statusUpdate',
    );
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

export const subscribeReturnsStream: Contract = {
  id: 'transport.subscribe_returns_stream',
  specSection: '§3.1.6',
  description:
    'tasks/resubscribe returns Content-Type text/event-stream.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task';
    const url = agentUrl.replace(/\/$/, '') + RPC_PATH;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 'resub-ctype',
        method: 'tasks/resubscribe',
        params: { id: seed.id },
      }),
    });
    res.body?.cancel();
    const ctype = res.headers.get('content-type') ?? '';
    if (ctype.toLowerCase().includes('text/event-stream')) return;
    if (ctype.toLowerCase().includes('application/json')) {
      return `tasks/resubscribe returned application/json, not text/event-stream; spec mandates SSE`;
    }
    throw new Error(
      `tasks/resubscribe returned unexpected content-type ${ctype}`,
    );
  },
};

export const subscribeReplaysState: Contract = {
  id: 'transport.subscribe_replays_state',
  specSection: '§3.1.6',
  description:
    'tasks/resubscribe first event reflects the subscribed task state.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task';
    let events;
    try {
      events = await streamSseEvents(
        agentUrl,
        'tasks/resubscribe',
        { id: seed.id },
      );
    } catch (err) {
      if (err instanceof SseFormatError) {
        return 'skipped — tasks/resubscribe did not return SSE';
      }
      throw err;
    }
    maybeAssert(events.length > 0, 'no events from tasks/resubscribe');
    const first = events[0] ?? {};
    const taskEnv = first.task as Record<string, unknown> | undefined;
    if (looksLikeTask(taskEnv)) {
      maybeAssert(
        (taskEnv as { id: string }).id === seed.id,
        `first event task.id ≠ subscribed id`,
      );
      return;
    }
    const su = first.statusUpdate as Record<string, unknown> | undefined;
    if (su) {
      maybeAssert(
        su.taskId === seed.id,
        'first statusUpdate.taskId ≠ subscribed id',
      );
      return;
    }
    throw new Error(
      `first tasks/resubscribe event carries neither task nor statusUpdate`,
    );
  },
};

export const subscribeNotFound: Contract = {
  id: 'transport.subscribe_not_found',
  specSection: '§3.1.6',
  description:
    'tasks/resubscribe on unknown id returns TaskNotFoundError.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = streamingSkipDetail(card);
    if (skip) return skip;
    const env = await callMethod(agentUrl, 'tasks/resubscribe', {
      id: crypto.randomUUID(),
    });
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement tasks/resubscribe (-32601)';
    }
    if ('result' in env && !error) {
      throw new Error('tasks/resubscribe returned a result for bogus id');
    }
    const code = error?.code;
    if (code === TASK_NOT_FOUND_CODE) return;
    return `agent rejected unknown id (good) but with code ${code}; spec mandates ${TASK_NOT_FOUND_CODE}`;
  },
};

export const subscribeCapabilityRequired: Contract = {
  id: 'transport.subscribe_capability_required',
  specSection: '§3.1.6',
  description:
    'tasks/resubscribe returns -32004 when streaming=false.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const caps = card.capabilities as Record<string, unknown> | undefined;
    if (caps?.streaming === true) {
      return 'skipped — agent advertises streaming=true (positive case)';
    }
    const env = await callMethod(agentUrl, 'tasks/resubscribe', {
      id: crypto.randomUUID(),
    });
    if ('result' in env && !env.error) {
      throw new Error(
        'agent advertises streaming=false but tasks/resubscribe returned a result',
      );
    }
    const error = (env.error ?? {}) as Record<string, unknown>;
    if (error.code === -32004) return;
    return `capability honored — agent refused but with code ${error.code}; spec mandates -32004`;
  },
};

// ---------------------------------------------------------------------------
// Push notifications (§3.1.7–§3.1.10, §3.5)
// ---------------------------------------------------------------------------

async function setPushConfig(
  agentUrl: string,
  taskId: string,
  url: string,
): Promise<{ id: string | null; skipped: string | null }> {
  const env = await callMethod(
    agentUrl,
    'tasks/pushNotificationConfig/set',
    { taskId, pushNotificationConfig: { url } },
  );
  const error = env.error as Record<string, unknown> | undefined;
  if (error?.code === -32601) {
    return {
      id: null,
      skipped: 'skipped — agent does not implement pushNotificationConfig/set',
    };
  }
  const cfg = (((env.result as Record<string, unknown>) ?? {})
    .pushNotificationConfig ?? null) as Record<string, unknown> | null;
  return { id: typeof cfg?.id === 'string' ? cfg.id : null, skipped: null };
}

export const pushSetPersists: Contract = {
  id: 'transport.push_set_persists',
  specSection: '§3.1.7',
  description:
    'pushNotificationConfig/set returns the stored config with id.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = pushSkipDetail(card);
    if (skip) return skip;
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task';
    const url = 'https://example.invalid/wh/' + crypto.randomUUID();
    const env = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/set',
      { taskId: seed.id, pushNotificationConfig: { url } },
    );
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement pushNotificationConfig/set';
    }
    const result = env.result as Record<string, unknown> | undefined;
    maybeAssert(
      typeof result === 'object' && result !== null,
      'set MUST return result object',
    );
    const cfg = (result as { pushNotificationConfig?: unknown })
      .pushNotificationConfig as Record<string, unknown> | undefined;
    maybeAssert(
      typeof cfg === 'object' && cfg !== null,
      'result.pushNotificationConfig MUST be present',
    );
    maybeAssert(
      cfg.url === url,
      `set returned url ${JSON.stringify(cfg.url)}; expected ${JSON.stringify(url)}`,
    );
    maybeAssert(
      typeof cfg.id === 'string' && cfg.id,
      'config id MUST be assigned',
    );
  },
};

export const pushGetReturnsConfig: Contract = {
  id: 'transport.push_get_returns_config',
  specSection: '§3.1.8',
  description:
    'pushNotificationConfig/get retrieves the stored config.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = pushSkipDetail(card);
    if (skip) return skip;
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task';
    const url = 'https://example.invalid/wh/' + crypto.randomUUID();
    const set = await setPushConfig(agentUrl, seed.id, url);
    if (set.skipped) return set.skipped;
    if (!set.id) throw new Error('set did not return a config id');
    const env = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/get',
      { taskId: seed.id, pushNotificationConfigId: set.id },
    );
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement pushNotificationConfig/get';
    }
    const cfg = (((env.result as Record<string, unknown>) ?? {})
      .pushNotificationConfig ?? null) as Record<string, unknown> | null;
    maybeAssert(
      typeof cfg === 'object' && cfg !== null,
      'get MUST return pushNotificationConfig',
    );
    maybeAssert(cfg.id === set.id, `get id ${JSON.stringify(cfg.id)} ≠ stored ${JSON.stringify(set.id)}`);
    maybeAssert(cfg.url === url, `get url ${JSON.stringify(cfg.url)} ≠ stored ${JSON.stringify(url)}`);
  },
};

export const pushListReturnsAll: Contract = {
  id: 'transport.push_list_returns_all',
  specSection: '§3.1.9',
  description:
    'pushNotificationConfig/list returns every stored config.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = pushSkipDetail(card);
    if (skip) return skip;
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task';
    const ids: string[] = [];
    for (let i = 0; i < 2; i++) {
      const set = await setPushConfig(
        agentUrl,
        seed.id,
        `https://example.invalid/wh/${crypto.randomUUID()}-${i}`,
      );
      if (set.skipped) return set.skipped;
      if (!set.id) throw new Error('set did not return id');
      ids.push(set.id);
    }
    const env = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/list',
      { taskId: seed.id },
    );
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement pushNotificationConfig/list';
    }
    const result = env.result as Record<string, unknown>;
    const configs =
      (result?.pushNotificationConfigs as unknown[] | undefined) ??
      (result?.configs as unknown[] | undefined) ??
      [];
    const listed = new Set(
      configs
        .map((c) => (c as { id?: unknown })?.id)
        .filter((id): id is string => typeof id === 'string'),
    );
    for (const id of ids) {
      maybeAssert(
        listed.has(id),
        `list omitted previously-set config ${id}`,
      );
    }
  },
};

export const pushDeleteRemoves: Contract = {
  id: 'transport.push_delete_removes',
  specSection: '§3.1.10',
  description:
    'pushNotificationConfig/delete removes the config from list.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = pushSkipDetail(card);
    if (skip) return skip;
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task';
    const set = await setPushConfig(
      agentUrl,
      seed.id,
      'https://example.invalid/wh/' + crypto.randomUUID(),
    );
    if (set.skipped) return set.skipped;
    if (!set.id) throw new Error('set did not return id');
    const del = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/delete',
      { taskId: seed.id, pushNotificationConfigId: set.id },
    );
    const error = del.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement pushNotificationConfig/delete';
    }
    const list = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/list',
      { taskId: seed.id },
    );
    const listError = list.error as Record<string, unknown> | undefined;
    if (listError?.code === -32601) return;
    const result = list.result as Record<string, unknown>;
    const configs =
      (result?.pushNotificationConfigs as unknown[] | undefined) ??
      (result?.configs as unknown[] | undefined) ??
      [];
    const listed = new Set(
      configs.map((c) => (c as { id?: unknown })?.id).filter((id): id is string => typeof id === 'string'),
    );
    maybeAssert(
      !listed.has(set.id),
      `deleted config ${set.id} still in list response`,
    );
  },
};

export const pushSetTaskNotFound: Contract = {
  id: 'transport.push_set_task_not_found',
  specSection: '§3.1.7',
  description:
    'pushNotificationConfig/set on unknown taskId returns TaskNotFoundError.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = pushSkipDetail(card);
    if (skip) return skip;
    const env = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/set',
      {
        taskId: crypto.randomUUID(),
        pushNotificationConfig: { url: 'https://example.invalid/wh' },
      },
    );
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement pushNotificationConfig/set';
    }
    if ('result' in env && !error) {
      throw new Error('set returned a result for bogus taskId');
    }
    if (error?.code === TASK_NOT_FOUND_CODE) return;
    return `agent rejected unknown taskId (good) but with code ${error?.code}; spec mandates ${TASK_NOT_FOUND_CODE}`;
  },
};

export const pushGetTaskNotFound: Contract = {
  id: 'transport.push_get_task_not_found',
  specSection: '§3.1.8',
  description:
    'pushNotificationConfig/get on unknown taskId returns TaskNotFoundError.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = pushSkipDetail(card);
    if (skip) return skip;
    const env = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/get',
      {
        taskId: crypto.randomUUID(),
        pushNotificationConfigId: crypto.randomUUID(),
      },
    );
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement pushNotificationConfig/get';
    }
    if ('result' in env && !error) {
      throw new Error('get returned a result for bogus taskId');
    }
    if (error?.code === TASK_NOT_FOUND_CODE) return;
    return `agent rejected unknown taskId (good) but with code ${error?.code}; spec mandates ${TASK_NOT_FOUND_CODE}`;
  },
};

export const pushFiresOnCompletion: Contract = {
  id: 'transport.push_fires_on_completion',
  specSection: '§3.5',
  description:
    'Agent POSTs the Task to a registered push URL on completion.',
  category: 'transport',
  async verify(agentUrl) {
    const card = await fetchCardJson(agentUrl);
    const skip = pushSkipDetail(card);
    if (skip) return skip;
    const token = freshToken();
    const webhook = `${PUSH_RECEIVER_BASE}/webhook/${token}`;
    // blocking=false so the agent returns before the task completes
    // and we have time to register the push config.
    const task = await probeForTask(agentUrl, { text: 'count: 8' });
    if (!task) return 'skipped — agent did not return a Task';
    if (TERMINAL_TASK_STATES.has(task.status.state)) {
      return 'skipped — agent ignored blocking semantics; task already terminal';
    }
    // Use raw JSON-RPC call for blocking=false since probeForTask
    // doesn't take that option in the TS port.
    const url = agentUrl.replace(/\/$/, '') + RPC_PATH;
    const sendRes = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 'pfc-send',
        method: 'message/send',
        params: {
          message: {
            messageId: 'pfc-' + crypto.randomUUID(),
            role: 'user',
            parts: [{ kind: 'text', text: 'count: 8 push' }],
          },
          configuration: { blocking: false },
        },
      }),
    });
    const sendBody = (await sendRes.json()) as Record<string, unknown>;
    const fresh = sendBody.result as
      | { id?: string; status?: { state?: string } }
      | undefined;
    if (!fresh?.id) return 'skipped — message/send did not return Task';
    if (fresh.status && TERMINAL_TASK_STATES.has(fresh.status.state ?? '')) {
      return 'skipped — agent ignored blocking=false (task already terminal)';
    }
    const set = await callMethod(
      agentUrl,
      'tasks/pushNotificationConfig/set',
      { taskId: fresh.id, pushNotificationConfig: { url: webhook } },
    );
    const setError = set.error as Record<string, unknown> | undefined;
    if (setError?.code === -32601) {
      return 'skipped — agent does not implement pushNotificationConfig/set';
    }
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
    let payload: { id?: unknown } | null = null;
    try {
      payload = JSON.parse(body) as { id?: unknown };
    } catch {
      payload = null;
    }
    if (payload?.id !== fresh.id) {
      return `webhook delivered but payload didn't carry the task id`;
    }
  },
};
