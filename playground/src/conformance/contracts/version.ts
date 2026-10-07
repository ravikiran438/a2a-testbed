// Protocol-version contracts. Browser-side mirror of
// `advertised_version_served.py`, `version_not_supported.py` and
// `send_message_result_shape.py`.

import {
  type Dialect,
  method,
  requestHeaders,
  sendParams,
  textMessage,
  VERSION_HEADER,
} from '../dialect';
import { assert, jsonRpcCall } from '../transport';
import type { Contract } from '../types';
import { AgentProbe, errorCode, METHOD_NOT_FOUND_CODE } from './_probe';

const VERSION_NOT_SUPPORTED_CODE = -32009;

export const advertisedVersionServed: Contract = {
  id: 'transport.advertised_version_served',
  specSection: '§3.6.2',
  description:
    'Agent answers the JSON-RPC method names of the protocolVersion its AgentCard advertises.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await AgentProbe.create(agentUrl);
    assert(Object.keys(probe.card).length > 0, 'card endpoint did not return a JSON AgentCard');
    const env = await probe.call('send', probe.sendParams('version probe'));
    const code = errorCode(env);
    const advertised = probe.dialect;
    if (code === METHOD_NOT_FOUND_CODE) {
      // Name the mismatch precisely: does the other version's name work?
      const other: Dialect = advertised === '1.0' ? '0.3' : '1.0';
      const { body } = await jsonRpcCall(
        agentUrl,
        method(other, 'send'),
        sendParams(other, textMessage(other, 'version probe')),
        'version-alt',
        requestHeaders(other),
      );
      const alt = (body ?? {}) as Record<string, unknown>;
      if ('result' in alt && errorCode(alt) === null) {
        throw new Error(
          `AgentCard advertises A2A ${advertised} (JSONRPC) but the agent returned ` +
            `MethodNotFound for ${JSON.stringify(probe.method('send'))} and only answers the ` +
            `A2A ${other} name ${JSON.stringify(method(other, 'send'))}; either serve the ` +
            `A2A ${advertised} method names or advertise protocolVersion ${JSON.stringify(other)} (§3.6.2, §9.1)`,
        );
      }
      throw new Error(
        `AgentCard advertises A2A ${advertised} (JSONRPC) but the agent returned ` +
          `MethodNotFound for ${JSON.stringify(probe.method('send'))} (§9.1)`,
      );
    }
    if (code === VERSION_NOT_SUPPORTED_CODE) {
      throw new Error(
        `agent rejected A2A-Version ${advertised} with VersionNotSupportedError although ` +
          'its AgentCard advertises that version (§3.6.2)',
      );
    }
    assert(
      Object.keys(env).length > 0,
      `${probe.method('send')} did not return a JSON-RPC envelope`,
    );
    return `agent serves A2A ${advertised} as advertised (${probe.method('send')})`;
  },
};

export const versionNotSupported: Contract = {
  id: 'transport.version_not_supported',
  specSection: '§3.6.2',
  description: 'Requests for an unsupported A2A-Version return VersionNotSupportedError -32009.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await AgentProbe.create(agentUrl);
    if (probe.isLegacy) {
      return 'skipped — A2A 0.3 agent; version negotiation was introduced in 1.0';
    }
    const { body, status } = await jsonRpcCall(
      agentUrl,
      probe.method('send'),
      probe.sendParams('version negotiation probe'),
      'version-not-supported-probe',
      { ...probe.headers(), [VERSION_HEADER]: '99.0' },
    );
    assert(
      body && typeof body === 'object',
      `request with A2A-Version 99.0 returned non-JSON (status ${status})`,
    );
    const env = body as Record<string, unknown>;
    if ('result' in env && !env.error) {
      throw new Error(
        'agent processed a request for A2A-Version 99.0; §3.6.2 requires ' +
          'VersionNotSupportedError (-32009)',
      );
    }
    const code = errorCode(env);
    if (code === VERSION_NOT_SUPPORTED_CODE) return;
    const message = (env.error as { message?: unknown } | undefined)?.message;
    return (
      `agent refused A2A-Version 99.0 (good) but with code ${code} (${message ?? '?'}); ` +
      `spec mandates ${VERSION_NOT_SUPPORTED_CODE} (VersionNotSupportedError)`
    );
  },
};

const ONEOF = ['task', 'message'];

export const sendMessageResultShape: Contract = {
  id: 'transport.send_message_result_shape',
  specSection: '§9.4.1',
  description: 'SendMessage result is exactly one of {task} / {message}.',
  category: 'transport',
  async verify(agentUrl) {
    const probe = await AgentProbe.create(agentUrl);
    const env = await probe.call('send', probe.sendParams('result-shape probe'));
    if (errorCode(env) !== null) {
      return `skipped — ${probe.method('send')} returned error ${errorCode(env)}; result shape not observable`;
    }
    const result = env.result;
    assert(
      result && typeof result === 'object' && !Array.isArray(result),
      `${probe.method('send')} result MUST be an object`,
    );
    const r = result as Record<string, unknown>;
    if (probe.isLegacy) {
      assert(
        typeof r.kind === 'string' && ONEOF.includes(r.kind),
        `A2A 0.3 message/send result MUST be a Task or Message with kind 'task' / 'message'; got kind=${JSON.stringify(r.kind)}`,
      );
      return `A2A 0.3 result kind=${JSON.stringify(r.kind)}`;
    }
    const keys = Object.keys(r);
    const present = ONEOF.filter((k) => k in r);
    assert(
      present.length === 1,
      `SendMessage result MUST contain exactly one of 'task' / 'message' (SendMessageResponse, §3.2.2); got keys ${keys.sort()}` +
        ('status' in r && 'id' in r ? ' — this looks like a bare Task (the A2A 0.3 shape)' : ''),
    );
    const member = present[0] as string;
    assert(r[member] && typeof r[member] === 'object', `result.${member} MUST be an object`);
    assert(
      keys.length === 1,
      `SendMessage result carries extra keys beside ${JSON.stringify(member)}: ${keys.filter((k) => k !== member)}`,
    );
  },
};
