// Browser-side mirror of the Python `_task_helpers.py` streaming /
// push helpers. SSE consumption uses the standard fetch() Response
// body — Cloudflare Workers + the math-agent already return event-stream
// bodies in browser-readable form, no preflight tweaks needed.

import { cardToV10 } from '../dialect';
import { fetchCard, jsonRpcCall } from '../transport';

export const PUSH_RECEIVER_BASE = 'https://push.a2a-testbed.com';

/** Receiver the push contracts use; overridable for offline runs (the
 *  Python side reads A2A_TESTBED_PUSH_RECEIVER). */
let pushReceiverBase = PUSH_RECEIVER_BASE;

export function setPushReceiverBase(url: string | null): void {
  pushReceiverBase = (url ?? PUSH_RECEIVER_BASE).replace(/\/$/, '');
}

export function getPushReceiverBase(): string {
  return pushReceiverBase;
}

export interface SseEvent {
  [k: string]: unknown;
}

const RPC_PATH = '/a2a/v1/';

/**
 * POST a JSON-RPC method whose response is an SSE stream. Returns
 * the parsed `data:` payloads in order. Throws when the response
 * isn't `text/event-stream` so callers can surface a clear failure.
 */
export async function streamSseEvents(
  agentUrl: string,
  method: string,
  params: unknown,
  opts: { maxEvents?: number; headers?: Record<string, string>; requestId?: string } = {},
): Promise<SseEvent[]> {
  const url = agentUrl.replace(/\/$/, '') + RPC_PATH;
  const req = {
    jsonrpc: '2.0',
    id: opts.requestId ?? `sse-${Math.random().toString(36).slice(2, 10)}`,
    method,
    params,
  };
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'text/event-stream',
      ...(opts.headers ?? {}),
    },
    body: JSON.stringify(req),
  });
  const ctype = res.headers.get('content-type') ?? '';
  if (!ctype.toLowerCase().includes('text/event-stream')) {
    // Not SSE — surface the JSON-RPC error if the agent sent one.
    const raw = await res.text().catch(() => '');
    throw new SseFormatError(`expected text/event-stream, got ${JSON.stringify(ctype)}`, raw);
  }
  const reader = res.body?.getReader();
  if (!reader) throw new SseFormatError('no response body to stream');
  const decoder = new TextDecoder();
  const max = opts.maxEvents ?? 50;
  const events: SseEvent[] = [];
  let buffer = '';
  while (events.length < max) {
    const { value, done } = await reader.read();
    if (done) break;
    // SSE allows CRLF, LF or CR line endings; sse-starlette (used by
    // the a2a-sdk) emits CRLF. Normalize, holding back a trailing CR
    // whose LF may arrive in the next chunk.
    buffer += decoder.decode(value, { stream: true });
    const held = buffer.endsWith('\r') ? '\r' : '';
    if (held) buffer = buffer.slice(0, -1);
    buffer = buffer.replace(/\r\n?/g, '\n');
    while (buffer.includes('\n\n')) {
      const idx = buffer.indexOf('\n\n');
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const parsed = parseSseBlock(block);
      if (parsed) events.push(parsed);
      if (events.length >= max) break;
    }
    buffer += held;
  }
  buffer = buffer.replace(/\r\n?/g, '\n');
  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed) events.push(parsed);
  }
  return events;
}

function parseSseBlock(block: string): SseEvent | null {
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  try {
    const parsed = JSON.parse(dataLines.join('\n'));
    return parsed && typeof parsed === 'object' ? (parsed as SseEvent) : null;
  } catch {
    return null;
  }
}

export class SseFormatError extends Error {
  /** JSON-RPC error code when the agent answered with a plain error envelope. */
  readonly errorCode: number | null;

  constructor(message: string, body = '') {
    super(message);
    let code: number | null = null;
    try {
      const parsed = JSON.parse(body) as { error?: { code?: unknown } };
      if (typeof parsed?.error?.code === 'number') code = parsed.error.code;
    } catch {
      /* not JSON */
    }
    this.errorCode = code;
  }
}

/**
 * Capability-gated skip checks. Streaming / push contracts only
 * apply when the AgentCard advertises the matching capability.
 */
export function streamingSkipDetail(card: Record<string, unknown> | null): string | null {
  const caps = (cardToV10(card).capabilities ?? null) as Record<string, unknown> | null;
  return caps?.streaming === true
    ? null
    : 'skipped — agent does not advertise capabilities.streaming=true';
}

export function pushSkipDetail(card: Record<string, unknown> | null): string | null {
  const caps = (cardToV10(card).capabilities ?? null) as Record<string, unknown> | null;
  return caps?.pushNotifications === true
    ? null
    : 'skipped — agent does not advertise capabilities.pushNotifications=true';
}

export async function fetchCardJson(agentUrl: string): Promise<Record<string, unknown>> {
  // Delegates to transport.fetchCard so the per-sweep cache is
  // shared. Streaming/push/subscribe contracts each call this for
  // capability lookup; without sharing they'd each fire a separate
  // GET against the agent.
  const { body } = await fetchCard(agentUrl);
  return body && typeof body === 'object' ? (body as Record<string, unknown>) : {};
}

export function freshToken(): string {
  return `tok-${crypto.randomUUID()}`;
}

export async function readReceivedHooks(token: string): Promise<Array<Record<string, unknown>>> {
  const res = await fetch(`${pushReceiverBase}/received/${encodeURIComponent(token)}`);
  if (!res.ok) return [];
  try {
    const body = (await res.json()) as { hooks?: unknown };
    return Array.isArray(body.hooks) ? (body.hooks as Array<Record<string, unknown>>) : [];
  } catch {
    return [];
  }
}

/** Plain JSON-RPC call wrapped to swallow non-JSON noise. */
export async function callMethod(
  agentUrl: string,
  method: string,
  params: unknown,
): Promise<Record<string, unknown>> {
  const { body } = await jsonRpcCall(
    agentUrl,
    method,
    params,
    `call-${Math.random().toString(36).slice(2, 10)}`,
  );
  return (body ?? {}) as Record<string, unknown>;
}
