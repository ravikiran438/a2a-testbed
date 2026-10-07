// AgentProbe: one agent under test, addressed in the A2A dialect its
// card advertises. Browser-side mirror of `AgentProbe` in
// `src/a2a_testbed/contracts/transport/_task_helpers.py`.

import {
  cardToV10,
  type Dialect,
  detectDialect,
  type MessageOpts,
  method,
  normalizePushConfig,
  normalizePushConfigList,
  normalizeSendResult,
  normalizeTask,
  type Op,
  requestHeaders,
  sendParams,
  textMessage,
  unwrapStreamFrame,
} from '../dialect';
import { fetchCard, getPinnedProtocolVersion, jsonRpcCall } from '../transport';
import { type SseEvent, streamSseEvents } from './_streaming_helpers';
import { looksLikeTask, type TaskShape } from './_task_helpers';

type Json = Record<string, unknown>;

export const METHOD_NOT_FOUND_CODE = -32601;
export const TASK_NOT_CANCELABLE_CODE = -32002;
export const UNSUPPORTED_OPERATION_CODE = -32004;

/** Text that makes the reference task runner work for ~N×50ms, long
 *  enough to act on a running task. */
export const LONG_TASK_TEXT = 'count: 12 long-running probe';

export function errorCode(env: unknown): number | null {
  if (!env || typeof env !== 'object') return null;
  const err = (env as Json).error;
  if (!err || typeof err !== 'object') return null;
  const code = (err as Json).code;
  return typeof code === 'number' ? code : null;
}

function randHex(): string {
  return Math.random().toString(36).slice(2, 10);
}

export class AgentProbe {
  readonly agentUrl: string;
  /** Raw AgentCard JSON (any version); `{}` when unreachable. */
  readonly card: Json;
  /** The card in the 1.0 layout (0.3 cards converted). */
  readonly cardV1: Json;
  readonly dialect: Dialect;

  constructor(agentUrl: string, card: Json, cardV1: Json, dialect: Dialect) {
    this.agentUrl = agentUrl;
    this.card = card;
    this.cardV1 = cardV1;
    this.dialect = dialect;
  }

  static async create(agentUrl: string): Promise<AgentProbe> {
    const { body } = await fetchCard(agentUrl);
    const card = body && typeof body === 'object' && !Array.isArray(body) ? (body as Json) : {};
    const dialect = getPinnedProtocolVersion() ?? detectDialect(card);
    return new AgentProbe(agentUrl, card, cardToV10(card), dialect);
  }

  get isLegacy(): boolean {
    return this.dialect === '0.3';
  }

  headers(): Record<string, string> {
    return requestHeaders(this.dialect);
  }

  method(op: Op): string {
    return method(this.dialect, op);
  }

  message(text: string, opts: MessageOpts = {}): Json {
    return textMessage(this.dialect, text, opts);
  }

  sendParams(text: string, blocking?: boolean, opts: MessageOpts = {}): Json {
    return sendParams(this.dialect, this.message(text, opts), blocking);
  }

  capability(name: string): unknown {
    const caps = this.cardV1.capabilities;
    return caps && typeof caps === 'object' ? (caps as Json)[name] : undefined;
  }

  // -- result normalization (0.3 → 1.0; 1.0 payloads pass through) --

  taskOf(value: unknown): unknown {
    return this.isLegacy ? normalizeTask(value) : value;
  }

  pushConfigOf(value: unknown): Json | null {
    return normalizePushConfig(this.dialect, value);
  }

  pushConfigListOf(value: unknown): Json[] | null {
    return normalizePushConfigList(this.dialect, value);
  }

  /** Call `op`; returns the parsed JSON-RPC envelope ({} if not JSON). */
  async call(op: Op, params: unknown, id = `call-${randHex()}`): Promise<Json> {
    const { body } = await jsonRpcCall(this.agentUrl, this.method(op), params, id, this.headers());
    return body && typeof body === 'object' ? (body as Json) : {};
  }

  /** SSE events of `op`, unwrapped to 1.0 StreamResponse objects. */
  async stream(op: Op, params: unknown): Promise<SseEvent[]> {
    const frames = await this.streamFrames(op, params);
    return frames.map((f) => unwrapStreamFrame(this.dialect, f) as SseEvent);
  }

  /** Raw parsed SSE `data:` payloads. */
  streamFrames(op: Op, params: unknown, requestId?: string): Promise<SseEvent[]> {
    return streamSseEvents(this.agentUrl, this.method(op), params, {
      headers: this.headers(),
      requestId,
    });
  }

  /** Send a message and return the resulting Task (1.0 shape), if any. */
  async sendForTask(
    opts: { text?: string; blocking?: boolean; contextId?: string; taskId?: string } = {},
  ): Promise<TaskShape | null> {
    const env = await this.call(
      'send',
      this.sendParams(opts.text ?? 'task-probe', opts.blocking === false ? false : undefined, {
        contextId: opts.contextId,
        taskId: opts.taskId,
      }),
      `task-probe-${randHex()}`,
    );
    const result = normalizeSendResult(this.dialect, env.result);
    const task = result && typeof result === 'object' ? (result as Json).task : undefined;
    return looksLikeTask(task) ? task : null;
  }
}
