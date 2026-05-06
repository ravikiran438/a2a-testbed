// HTTP helpers shared by every contract. Mirrors the constants the
// Python `a2a_testbed.transport.A2ATransport` exposes — A2A 1.0
// pins the well-known card path (RFC 8615) and the JSON-RPC endpoint
// (`/a2a/v1/`) so we hardcode them here instead of plumbing a
// Transport interface through every contract.

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

export async function fetchCard(agentUrl: string): Promise<CardFetchResult> {
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
): Promise<RpcResult> {
  const url = stripTrailing(agentUrl) + RPC_PATH;
  const req = { jsonrpc: '2.0', id, method, params };
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(req),
  });
  const raw = await res.text();
  let body: unknown = null;
  try {
    body = JSON.parse(raw);
  } catch {
    /* leave body as null */
  }
  return { status: res.status, raw, body };
}

/** Build a vanilla `message/send` request body — used by contracts
 *  that just need to make any well-formed call to inspect the
 *  response envelope. */
export function buildMessageSendParams(text: string): unknown {
  return {
    message: {
      messageId: 'browser-conformance',
      role: 'user',
      parts: [{ kind: 'text', text }],
    },
  };
}

/** Throw if `cond` is false. Mirrors Python's `assert` so every
 *  contract reads as a series of assertions. The runner converts
 *  these into ContractResults. */
export function assert(cond: unknown, message: string): asserts cond {
  if (!cond) throw new Error(message);
}
