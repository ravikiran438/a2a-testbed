// JSON-RPC envelope, version, id-echo, error-code, and required-fields
// contracts. Every probe uses message/send (the one method every A2A
// agent must implement) so the same response can be reused for several
// shape checks.

import {
  assert,
  buildMessageSendParams,
  jsonRpcCall,
} from '../transport';
import type { Contract } from '../types';

function asObject(b: unknown): Record<string, unknown> {
  if (!b || typeof b !== 'object') {
    throw new Error('response body is not a JSON object');
  }
  return b as Record<string, unknown>;
}

export const jsonrpcEnvelope: Contract = {
  id: 'transport.jsonrpc_envelope',
  specSection: '§3.1.1',
  description:
    'jsonrpc field, id matching, exactly one of result/error.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      buildMessageSendParams('envelope-probe'),
      'envelope-1',
    );
    const obj = asObject(body);
    assert(
      obj.jsonrpc === '2.0',
      `response.jsonrpc MUST be "2.0", got ${JSON.stringify(obj.jsonrpc)}`,
    );
    assert(
      'id' in obj,
      'response MUST include an id field (echo of request id)',
    );
    const hasResult = 'result' in obj;
    const hasError = 'error' in obj;
    assert(
      hasResult !== hasError,
      'response MUST include exactly one of result OR error',
    );
  },
};

export const jsonrpcVersionField: Contract = {
  id: 'transport.jsonrpc_version_field',
  specSection: '§9.3',
  description: 'Every response carries jsonrpc: "2.0".',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      buildMessageSendParams('version-probe'),
      'version-1',
    );
    const obj = asObject(body);
    assert(
      obj.jsonrpc === '2.0',
      `jsonrpc field MUST be "2.0", got ${JSON.stringify(obj.jsonrpc)}`,
    );
  },
};

export const jsonrpcIdEcho: Contract = {
  id: 'transport.jsonrpc_id_echo',
  specSection: '§9.3',
  description: 'Response id matches the request id.',
  category: 'transport',
  async verify(agentUrl) {
    const requestId = 'echo-' + Math.random().toString(36).slice(2, 10);
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      buildMessageSendParams('id-echo-probe'),
      requestId,
    );
    const obj = asObject(body);
    assert(
      obj.id === requestId,
      `response.id ${JSON.stringify(obj.id)} does not echo request id ${JSON.stringify(requestId)}`,
    );
  },
};

export const jsonrpcResultXorError: Contract = {
  id: 'transport.jsonrpc_result_xor_error',
  specSection: '§5',
  description: 'Exactly one of result / error per response.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      buildMessageSendParams('xor-probe'),
      'xor-1',
    );
    const obj = asObject(body);
    assert(
      ('result' in obj) !== ('error' in obj),
      'response MUST include exactly one of result OR error (never both, never neither)',
    );
  },
};

export const jsonrpcErrorCodeRange: Contract = {
  id: 'transport.jsonrpc_error_code_range',
  specSection: '§9.5',
  description:
    'A2A-specific error codes live in the documented range.',
  category: 'transport',
  async verify(agentUrl) {
    // Trigger a known error: send a malformed message/send (missing message).
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      {},
      'errcode-1',
    );
    const obj = asObject(body);
    if (!('error' in obj)) {
      throw new Error(
        'agent did not emit an error response for a malformed message/send call',
      );
    }
    const err = obj.error as Record<string, unknown>;
    const code = err.code;
    assert(
      typeof code === 'number',
      `error.code MUST be a number, got ${typeof code}`,
    );
    // Standard JSON-RPC range OR A2A-specific range.
    const ok =
      // JSON-RPC reserved
      (code >= -32768 && code <= -32000) ||
      // A2A range overlaps the reserved JSON-RPC space; spec §9.5
      // allows either as long as the agent uses the documented codes.
      (code >= -32099 && code <= -32001);
    assert(
      ok,
      `error.code ${code} is outside the JSON-RPC + A2A documented range`,
    );
  },
};

export const methodNotFound: Contract = {
  id: 'transport.method_not_found',
  specSection: '§9',
  description: 'Unknown method returns -32601.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await jsonRpcCall(
      agentUrl,
      'this/method/does/not/exist',
      {},
      'mnf-1',
    );
    const obj = asObject(body);
    assert(
      'error' in obj,
      'agent did not return an error for an unknown method',
    );
    const err = obj.error as Record<string, unknown>;
    assert(
      err.code === -32601,
      `method-not-found MUST return -32601, got ${err.code}`,
    );
  },
};

export const errorDataAtype: Contract = {
  id: 'transport.error_data_atype',
  specSection: '§3.3.2',
  description: 'error.data[*] entries carry @type per ProtoJSON Any.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      {},
      'errdata-1',
    );
    if (!body || typeof body !== 'object') return;
    const error = (body as Record<string, unknown>).error;
    if (!error || typeof error !== 'object') return;
    const data = (error as Record<string, unknown>).data;
    if (data == null) return; // OPTIONAL field
    assert(
      Array.isArray(data),
      'error.data MUST be an array when present',
    );
    const offenders: string[] = [];
    data.forEach((entry, i) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
        offenders.push(`error.data[${i}] is not an object`);
        return;
      }
      const atype = (entry as Record<string, unknown>)['@type'];
      if (typeof atype !== 'string' || !atype) {
        offenders.push(
          `error.data[${i}] missing required '@type' key (§3.3.2)`,
        );
      }
    });
    assert(offenders.length === 0, offenders.join('; '));
  },
};

export const sendMessageRequiredFields: Contract = {
  id: 'transport.send_message_required_fields',
  specSection: '§3.1.1',
  description: 'message/send rejects requests missing required fields.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await jsonRpcCall(
      agentUrl,
      'message/send',
      {},
      'reqfields-1',
    );
    const obj = asObject(body);
    assert(
      'error' in obj,
      'message/send with empty params MUST return an error (missing message)',
    );
  },
};
