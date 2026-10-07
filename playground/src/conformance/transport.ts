// HTTP helpers shared by every contract. Mirrors the constants the
// Python `a2a_testbed.transport.A2ATransport` exposes — A2A 1.0
// pins the well-known card path (RFC 8615) and the JSON-RPC endpoint
// (`/a2a/v1/`) so we hardcode them here instead of plumbing a
// Transport interface through every contract. Protocol-version
// handling lives in `dialect.ts` and `contracts/_probe.ts`.

import { createSweepCache } from './cache';
import type { Dialect } from './dialect';

const CARD_PATH = '/.well-known/agent-card.json';
const RPC_PATH = '/a2a/v1/';

const stripTrailing = (url: string) => url.replace(/\/$/, '');

export interface CardFetchResult {
  status: number;
  /** Raw response body string. Surfaced for contracts that need to
   *  inspect non-JSON characteristics (e.g. trailing whitespace,
   *  byte-order marks) without re-fetching. */
  raw: string;
  /** Parsed JSON, or null when the body wasn't JSON. */
  body: unknown;
}

// Half the conformance contracts each fetch the AgentCard
// independently; the cache cuts a typical sweep from ~10 redundant
// fetches to 1. Cleared between sweeps via the registry in cache.ts.
const cardCache = createSweepCache<string, CardFetchResult>();

export async function fetchCard(agentUrl: string): Promise<CardFetchResult> {
  return cardCache.getOrFetch(agentUrl, async () => {
    const url = stripTrailing(agentUrl) + CARD_PATH;
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    const raw = await res.text();
    let body: unknown = null;
    try {
      body = JSON.parse(raw);
    } catch {
      /* leave body as null; contract decides whether to fail */
    }
    return { status: res.status, raw, body };
  });
}

export interface RpcResult {
  status: number;
  raw: string;
  body: unknown;
}

export async function jsonRpcCall(
  agentUrl: string,
  method: string,
  params: unknown,
  id: string | number = 1,
  headers: Record<string, string> = {},
): Promise<RpcResult> {
  const url = stripTrailing(agentUrl) + RPC_PATH;
  const req = { jsonrpc: '2.0', id, method, params };
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(req),
  });
  const raw = await res.text();
  let body: unknown = null;
  // Streaming methods may answer with an SSE error frame instead of a
  // JSON body; surface the first frame as the envelope.
  const ctype = res.headers.get('content-type') ?? '';
  const text = ctype.includes('text/event-stream') ? firstSseData(raw) : raw;
  try {
    body = JSON.parse(text);
  } catch {
    /* leave body as null */
  }
  return { status: res.status, raw, body };
}

function firstSseData(raw: string): string {
  const block = raw.replace(/\r\n?/g, '\n').split('\n\n')[0] ?? '';
  return block
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n');
}

/** Protocol version the next sweep should use instead of the one the
 *  AgentCard advertises (`null` = negotiate from the card). Mirrors the
 *  CLI's `--protocol-version`. */
let pinnedProtocolVersion: Dialect | null = null;

export function setPinnedProtocolVersion(version: Dialect | null): void {
  pinnedProtocolVersion = version;
}

export function getPinnedProtocolVersion(): Dialect | null {
  return pinnedProtocolVersion;
}

/** Throw if `cond` is false. Mirrors Python's `assert` so every
 *  contract reads as a series of assertions. The runner converts
 *  these into ContractResults. */
export function assert(cond: unknown, message: string): asserts cond {
  if (!cond) throw new Error(message);
}
