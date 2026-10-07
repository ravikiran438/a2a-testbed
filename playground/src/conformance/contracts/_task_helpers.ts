// Shared helpers for the Task / multi-turn contract families.
// Browser-side mirror of
// `src/a2a_testbed/contracts/transport/_task_helpers.py`. Sending
// probes in the right protocol version lives in `_probe.ts`.

export interface TaskShape {
  id: string;
  status: { state: string; timestamp?: string; [k: string]: unknown };
  contextId?: string;
  history?: unknown[];
  artifacts?: unknown[];
  [k: string]: unknown;
}

export const VALID_TASK_STATES: ReadonlySet<string> = new Set([
  'TASK_STATE_UNSPECIFIED',
  'TASK_STATE_SUBMITTED',
  'TASK_STATE_WORKING',
  'TASK_STATE_INPUT_REQUIRED',
  'TASK_STATE_COMPLETED',
  'TASK_STATE_CANCELED',
  'TASK_STATE_FAILED',
  'TASK_STATE_REJECTED',
  'TASK_STATE_AUTH_REQUIRED',
]);

export const TERMINAL_TASK_STATES: ReadonlySet<string> = new Set([
  'TASK_STATE_COMPLETED',
  'TASK_STATE_CANCELED',
  'TASK_STATE_FAILED',
  'TASK_STATE_REJECTED',
]);

export const TASK_NOT_FOUND_CODE = -32001;

export function looksLikeTask(value: unknown): value is TaskShape {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  if (typeof v.id !== 'string') return false;
  const status = v.status;
  if (!status || typeof status !== 'object') return false;
  return typeof (status as Record<string, unknown>).state === 'string';
}
