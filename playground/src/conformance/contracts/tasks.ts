// Task lifecycle, tasks/get, tasks/cancel, tasks/list, and multi-turn
// contextId contracts. Browser-side mirror of the
// `task_*.py` / `tasks_*.py` / `task_context_id_echoed.py` modules.

import { assert, jsonRpcCall } from '../transport';
import type { Contract } from '../types';
import {
  looksLikeTask,
  probeForTask,
  TASK_NOT_FOUND_CODE,
  TERMINAL_TASK_STATES,
  VALID_TASK_STATES,
} from './_task_helpers';

const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const TS_VALID = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const RECOGNIZED_ROLES = new Set(['user', 'agent', 'ROLE_USER', 'ROLE_AGENT']);

// ---------------------------------------------------------------------------
// Task lifecycle (§3.4 + §4.1.1 + §4.1.3 + §4.1.4 + §4.1.5)
// ---------------------------------------------------------------------------

export const taskIdUuidFormat: Contract = {
  id: 'transport.task_id_uuid_format',
  specSection: '§3.4',
  description: 'Task.id is a server-generated UUID.',
  category: 'transport',
  async verify(agentUrl) {
    const task = await probeForTask(agentUrl);
    if (!task) return 'skipped — agent did not return a Task envelope';
    assert(typeof task.id === 'string' && task.id, 'Task.id MUST be a non-empty string');
    assert(UUID_RE.test(task.id), `Task.id ${JSON.stringify(task.id)} is not a valid UUID`);
  },
};

export const taskStatusStateEnum: Contract = {
  id: 'transport.task_status_state_enum',
  specSection: '§4.1.3',
  description: 'Task.status.state is a recognized TaskState enum value.',
  category: 'transport',
  async verify(agentUrl) {
    const task = await probeForTask(agentUrl);
    if (!task) return 'skipped — agent did not return a Task envelope';
    const state = task.status.state;
    assert(typeof state === 'string' && state, 'Task.status.state MUST be a non-empty string');
    assert(
      VALID_TASK_STATES.has(state),
      `Task.status.state ${JSON.stringify(state)} is not a recognized ` +
        'TaskState; ProtoJSON requires SCREAMING_SNAKE_CASE form',
    );
  },
};

export const taskStatusTimestampPresent: Contract = {
  id: 'transport.task_status_timestamp_present',
  specSection: '§3.4',
  description: 'Task.status.timestamp is present and ISO 8601 UTC.',
  category: 'transport',
  async verify(agentUrl) {
    const task = await probeForTask(agentUrl);
    if (!task) return 'skipped — agent did not return a Task envelope';
    const ts = task.status.timestamp;
    assert(
      typeof ts === 'string' && ts,
      'Task.status.timestamp is REQUIRED — ListTasks ordering depends on it',
    );
    assert(
      TS_VALID.test(ts),
      `Task.status.timestamp ${JSON.stringify(ts)} MUST be ISO 8601 UTC with 'Z'`,
    );
  },
};

export const taskHistoryShape: Contract = {
  id: 'transport.task_history_shape',
  specSection: '§4.1.1',
  description: 'Task.history (when present) is a well-formed Message array.',
  category: 'transport',
  async verify(agentUrl) {
    const task = await probeForTask(agentUrl);
    if (!task) return 'skipped — agent did not return a Task envelope';
    const history = task.history;
    if (history == null) return;
    assert(Array.isArray(history), 'Task.history MUST be an array when present');
    history.forEach((msg, i) => {
      assert(
        msg && typeof msg === 'object' && !Array.isArray(msg),
        `Task.history[${i}] MUST be a Message object`,
      );
      const m = msg as Record<string, unknown>;
      assert(
        typeof m.role === 'string' && RECOGNIZED_ROLES.has(m.role),
        `Task.history[${i}].role ${JSON.stringify(m.role)} not recognized`,
      );
      assert(
        Array.isArray(m.parts) && m.parts.length > 0,
        `Task.history[${i}].parts MUST be a non-empty array`,
      );
    });
  },
};

export const taskArtifactsShape: Contract = {
  id: 'transport.task_artifacts_shape',
  specSection: '§4.1.1',
  description: 'Task.artifacts (when present) is a well-formed Artifact array.',
  category: 'transport',
  async verify(agentUrl) {
    const task = await probeForTask(agentUrl);
    if (!task) return 'skipped — agent did not return a Task envelope';
    const artifacts = task.artifacts;
    if (artifacts == null) return;
    assert(Array.isArray(artifacts), 'Task.artifacts MUST be an array when present');
    artifacts.forEach((art, i) => {
      assert(
        art && typeof art === 'object' && !Array.isArray(art),
        `Task.artifacts[${i}] MUST be an Artifact object`,
      );
      const a = art as Record<string, unknown>;
      assert(
        typeof a.artifactId === 'string' && a.artifactId,
        `Task.artifacts[${i}].artifactId is REQUIRED, non-empty string`,
      );
      assert(
        Array.isArray(a.parts) && a.parts.length > 0,
        `Task.artifacts[${i}].parts MUST be a non-empty array`,
      );
    });
  },
};

// ---------------------------------------------------------------------------
// GetTask / CancelTask / ListTasks (§3.1.3, §3.1.4, §3.1.5)
// ---------------------------------------------------------------------------

export const tasksGetReturnsTask: Contract = {
  id: 'transport.tasks_get_returns_task',
  specSection: '§3.1.3',
  description: 'tasks/get returns the Task identified by id.',
  category: 'transport',
  async verify(agentUrl) {
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task envelope';
    const { body } = await jsonRpcCall(
      agentUrl,
      'tasks/get',
      { id: seed.id },
      `tg-${Math.random().toString(36).slice(2, 8)}`,
    );
    const env = (body ?? {}) as Record<string, unknown>;
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement tasks/get (-32601)';
    }
    const result = env.result;
    assert(looksLikeTask(result), 'tasks/get MUST return a Task object');
    assert(
      (result as { id: string }).id === seed.id,
      `tasks/get returned id ${JSON.stringify((result as { id: string }).id)} but requested ${JSON.stringify(seed.id)}`,
    );
  },
};

export const tasksGetNotFound: Contract = {
  id: 'transport.tasks_get_not_found',
  specSection: '§3.1.3',
  description: 'tasks/get on an unknown id returns TaskNotFoundError.',
  category: 'transport',
  async verify(agentUrl) {
    const bogus = crypto.randomUUID();
    const { body } = await jsonRpcCall(agentUrl, 'tasks/get', { id: bogus }, 'tgnf-1');
    const env = (body ?? {}) as Record<string, unknown>;
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement tasks/get (-32601)';
    }
    if ('result' in env && !error) {
      throw new Error(
        `tasks/get returned a result for bogus id ${bogus}; spec mandates ` +
          `TaskNotFoundError (${TASK_NOT_FOUND_CODE})`,
      );
    }
    const code = error?.code;
    if (code === TASK_NOT_FOUND_CODE) return;
    return (
      `agent rejected unknown taskId (good) but with code ${code} ` +
      `(${error?.message ?? '?'}); spec mandates ${TASK_NOT_FOUND_CODE}`
    );
  },
};

export const tasksCancelSetsCanceled: Contract = {
  id: 'transport.tasks_cancel_sets_canceled',
  specSection: '§3.1.5',
  description: 'tasks/cancel transitions the task to TASK_STATE_CANCELED.',
  category: 'transport',
  async verify(agentUrl) {
    const seed = await probeForTask(agentUrl);
    if (!seed) return 'skipped — agent did not return a Task envelope';
    const { body } = await jsonRpcCall(agentUrl, 'tasks/cancel', { id: seed.id }, 'tc-1');
    const env = (body ?? {}) as Record<string, unknown>;
    const error = env.error as Record<string, unknown> | undefined;
    if (error) {
      const code = error.code;
      if (code === -32601) {
        return 'skipped — agent does not implement tasks/cancel (-32601)';
      }
      if (code === TASK_NOT_FOUND_CODE) {
        return (
          'agent returned TaskNotFoundError on cancel — permitted when ' +
          'task is already canceled and purged; cannot verify state'
        );
      }
      throw new Error(`tasks/cancel failed with code ${code} (${error.message ?? '?'})`);
    }
    const result = env.result;
    assert(looksLikeTask(result), 'tasks/cancel result MUST be the updated Task');
    const state = (result as { status: { state: string } }).status.state;
    if (state === 'TASK_STATE_CANCELED') return;
    if (TERMINAL_TASK_STATES.has(state)) {
      return (
        `task ended in ${state} rather than TASK_STATE_CANCELED — accepted ` +
        '(cancel may have arrived after completion)'
      );
    }
    throw new Error(
      `after tasks/cancel, Task.status.state is ${JSON.stringify(state)}; ` +
        'expected TASK_STATE_CANCELED',
    );
  },
};

export const tasksCancelNotFound: Contract = {
  id: 'transport.tasks_cancel_not_found',
  specSection: '§3.1.5',
  description: 'tasks/cancel on an unknown id returns TaskNotFoundError.',
  category: 'transport',
  async verify(agentUrl) {
    const bogus = crypto.randomUUID();
    const { body } = await jsonRpcCall(agentUrl, 'tasks/cancel', { id: bogus }, 'tcnf-1');
    const env = (body ?? {}) as Record<string, unknown>;
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement tasks/cancel (-32601)';
    }
    if ('result' in env && !error) {
      throw new Error(
        `tasks/cancel returned a result for bogus id ${bogus}; spec mandates ` +
          `TaskNotFoundError (${TASK_NOT_FOUND_CODE})`,
      );
    }
    const code = error?.code;
    if (code === TASK_NOT_FOUND_CODE) return;
    return (
      `agent rejected cancel of unknown id (good) but with code ${code} ` +
      `(${error?.message ?? '?'}); spec mandates ${TASK_NOT_FOUND_CODE}`
    );
  },
};

export const tasksListSortedDesc: Contract = {
  id: 'transport.tasks_list_sorted_desc',
  specSection: '§3.1.4',
  description: 'tasks/list returns tasks sorted descending by status.timestamp.',
  category: 'transport',
  async verify(agentUrl) {
    const first = await probeForTask(agentUrl);
    if (!first) return 'skipped — agent did not return a Task envelope';
    await probeForTask(agentUrl);
    const { body } = await jsonRpcCall(agentUrl, 'tasks/list', {}, 'tl-1');
    const env = (body ?? {}) as Record<string, unknown>;
    const error = env.error as Record<string, unknown> | undefined;
    if (error?.code === -32601) {
      return 'skipped — agent does not implement tasks/list (-32601)';
    }
    const result = env.result;
    const tasks = Array.isArray(result) ? result : (result as { tasks?: unknown })?.tasks;
    assert(Array.isArray(tasks), 'tasks/list result MUST contain a `tasks` array');
    if (tasks.length < 2) {
      return `only ${tasks.length} task(s) returned; can't verify sort`;
    }
    const stamps: string[] = [];
    tasks.forEach((t, i) => {
      const ts = (t as { status?: { timestamp?: unknown } })?.status?.timestamp;
      assert(
        typeof ts === 'string' && ts,
        `tasks/list[${i}].status.timestamp is REQUIRED for sort`,
      );
      stamps.push(ts);
    });
    for (let i = 0; i < stamps.length - 1; i++) {
      assert(
        stamps[i] >= stamps[i + 1],
        `tasks/list not sorted descending at index ${i}: ${stamps[i]} < ${stamps[i + 1]}`,
      );
    }
  },
};

// ---------------------------------------------------------------------------
// Multi-turn (§3.4.2)
// ---------------------------------------------------------------------------

export const taskContextIdEchoed: Contract = {
  id: 'transport.task_context_id_echoed',
  specSection: '§3.4.2',
  description: 'Client-provided contextId is preserved on the response Task or rejected.',
  category: 'transport',
  async verify(agentUrl) {
    const clientCtx = `ctx-${crypto.randomUUID().slice(0, 12)}`;
    const task = await probeForTask(agentUrl, { contextId: clientCtx });
    if (!task) {
      return (
        'skipped — agent did not return a Task envelope, or rejected the ' +
        'client-provided contextId (§3.4.2 line 593 permits rejection)'
      );
    }
    const agentCtx = task.contextId;
    if (agentCtx === clientCtx) return;
    if (typeof agentCtx === 'string' && agentCtx) {
      throw new Error(
        `agent produced a different contextId ${JSON.stringify(agentCtx)} ` +
          `after the client supplied ${JSON.stringify(clientCtx)}; per §3.4.2 ` +
          'the agent must EITHER preserve the value OR reject the request',
      );
    }
    throw new Error(
      'Task.contextId is missing from the response; §3.4.2 line 591 ' +
        'requires it be included when established',
    );
  },
};
