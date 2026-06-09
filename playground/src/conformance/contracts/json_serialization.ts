// JSON serialization contracts: camelCase field names + ISO 8601
// timestamps with 'Z' suffix. Both walk the response tree, so we
// share a tiny helper.

import { assert, buildMessageSendParams, fetchCard, jsonRpcCall } from '../transport';
import type { Contract } from '../types';

function walkStrings(node: unknown, path: string, out: Array<[string, string]>): void {
  if (node && typeof node === 'object') {
    if (Array.isArray(node)) {
      node.forEach((v, i) => walkStrings(v, `${path}[${i}]`, out));
    } else {
      for (const [k, v] of Object.entries(node)) {
        walkStrings(v, path ? `${path}.${k}` : k, out);
      }
    }
  } else if (typeof node === 'string') {
    out.push([path || '<root>', node]);
  }
}

function walkKeys(node: unknown, path: string, out: Array<[string, string]>): void {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return;
  for (const [k, v] of Object.entries(node)) {
    out.push([path, k]);
    walkKeys(v, path ? `${path}.${k}` : k, out);
  }
  if (Array.isArray(node)) {
    (node as unknown[]).forEach((v, i) => walkKeys(v, `${path}[${i}]`, out));
  }
}

const SNAKE = /[a-z]_[a-z]/;

export const jsonCamelCase: Contract = {
  id: 'transport.json_camel_case',
  specSection: '§5.5',
  description: 'JSON field names use camelCase, not snake_case.',
  category: 'transport',
  async verify(agentUrl) {
    // Walk both the AgentCard and a message/send response — most A2A
    // agents emit different fields in each.
    const { body: card } = await fetchCard(agentUrl);
    const { body: rpcResp } = await jsonRpcCall(
      agentUrl,
      'message/send',
      buildMessageSendParams('camel-case-probe'),
      'camel-1',
    );
    const offenders: string[] = [];
    const collectKeys = (root: unknown, label: string) => {
      const keys: Array<[string, string]> = [];
      walkKeys(root, '', keys);
      for (const [, k] of keys) {
        if (SNAKE.test(k)) offenders.push(`${label}: ${k}`);
      }
    };
    collectKeys(card, 'card');
    collectKeys(rpcResp, 'rpc');
    assert(
      offenders.length === 0,
      `snake_case keys found (spec §5.5 mandates camelCase): ${offenders.slice(0, 5).join(', ')}${offenders.length > 5 ? ` (+${offenders.length - 5} more)` : ''}`,
    );
  },
};

const TS_LIKE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const TS_VALID = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

export const iso8601Timestamps: Contract = {
  id: 'transport.iso8601_timestamps',
  specSection: '§5.6.1',
  description: "Response timestamps end with 'Z' (UTC).",
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      buildMessageSendParams('iso8601-probe'),
      'iso-1',
    );
    if (!body) return;
    const strings: Array<[string, string]> = [];
    walkStrings(body, '', strings);
    const offenders: string[] = [];
    for (const [path, value] of strings) {
      if (!TS_LIKE.test(value)) continue;
      if (!TS_VALID.test(value)) {
        offenders.push(`${path}=${JSON.stringify(value)}`);
      }
    }
    assert(
      offenders.length === 0,
      `timestamps MUST be ISO 8601 UTC with 'Z' suffix: ${offenders.join('; ')}`,
    );
  },
};
