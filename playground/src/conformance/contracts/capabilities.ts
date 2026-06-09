// Capability ↔ method consistency contracts. When an AgentCard claims
// a capability is `false`, the matching method must refuse. Strictness:
// 200+result is a hard fail (the agent lied about its capability);
// any error response is a soft pass with the deviation in the detail
// when the error code doesn't match the spec-mandated one.

import { assert, fetchCard, jsonRpcCall } from '../transport';
import type { Contract } from '../types';

interface CapabilityProbeOpts {
  capabilityKey: 'streaming' | 'pushNotifications' | 'extendedAgentCard';
  capabilityClaimedTrueDetail: string;
  expectedCode: number;
  expectedCodeName: string;
  method: string;
  params: unknown;
  /** §-citation used in the soft-pass message. */
  specCite: string;
  /** Human label for the operation, e.g. "message/stream". */
  opLabel: string;
}

async function runCapabilityProbe(
  agentUrl: string,
  opts: CapabilityProbeOpts,
): Promise<undefined | string> {
  const { body: card } = await fetchCard(agentUrl);
  const claim = (card as { capabilities?: Record<string, unknown> })?.capabilities?.[
    opts.capabilityKey
  ];
  if (claim === true) {
    return opts.capabilityClaimedTrueDetail;
  }

  const { body, status } = await jsonRpcCall(
    agentUrl,
    opts.method,
    opts.params,
    `cap-${opts.capabilityKey}`,
  );

  if (!body || typeof body !== 'object') {
    throw new Error(
      `agent advertises ${opts.capabilityKey}=false but ${opts.opLabel} ` +
        `returned non-JSON (status ${status})`,
    );
  }
  const obj = body as Record<string, unknown>;
  if ('result' in obj && !('error' in obj)) {
    throw new Error(
      `agent advertises ${opts.capabilityKey}=false but ${opts.opLabel} ` +
        `returned a result; per ${opts.specCite} it MUST return ` +
        `${opts.expectedCodeName} (${opts.expectedCode})`,
    );
  }
  const error = (obj.error ?? {}) as Record<string, unknown>;
  const code = error.code;
  if (code === opts.expectedCode) return; // strict pass
  // Soft pass: capability honored, wrong error code.
  return (
    `capability honored — agent refused ${opts.opLabel} as required ` +
    `(${opts.specCite}), but returned code ${code} ` +
    `(${error.message ?? '?'}); spec mandates ${opts.expectedCode} ` +
    `(${opts.expectedCodeName})`
  );
}

export const streamingCapabilityConsistency: Contract = {
  id: 'transport.streaming_capability_consistency',
  specSection: '§3.1.2',
  description: 'message/stream returns -32004 when streaming=false.',
  category: 'transport',
  verify: (agentUrl) =>
    runCapabilityProbe(agentUrl, {
      capabilityKey: 'streaming',
      capabilityClaimedTrueDetail: 'skipped — agent advertises streaming=true',
      expectedCode: -32004,
      expectedCodeName: 'UnsupportedOperationError',
      method: 'message/stream',
      params: {
        message: {
          messageId: 'cap-stream-probe',
          role: 'user',
          parts: [{ kind: 'text', text: 'probe' }],
        },
      },
      specCite: '§3.1.2',
      opLabel: 'message/stream',
    }),
};

export const pushNotificationsCapabilityConsistency: Contract = {
  id: 'transport.push_notifications_capability_consistency',
  specSection: '§3.5',
  description: 'Push config returns -32003 when pushNotifications=false.',
  category: 'transport',
  verify: (agentUrl) =>
    runCapabilityProbe(agentUrl, {
      capabilityKey: 'pushNotifications',
      capabilityClaimedTrueDetail: 'skipped — agent advertises pushNotifications=true',
      expectedCode: -32003,
      expectedCodeName: 'PushNotificationNotSupportedError',
      method: 'tasks/pushNotificationConfig/set',
      params: {
        taskId: '00000000-0000-0000-0000-000000000000',
        pushNotificationConfig: {
          url: 'https://example.invalid/webhook',
        },
      },
      specCite: '§3.5',
      opLabel: 'push config',
    }),
};

export const extendedCardCapabilityConsistency: Contract = {
  id: 'transport.extended_card_capability_consistency',
  specSection: '§3.1.7',
  description: 'Extended-card op returns -32004 when extendedAgentCard=false.',
  category: 'transport',
  verify: (agentUrl) =>
    runCapabilityProbe(agentUrl, {
      capabilityKey: 'extendedAgentCard',
      capabilityClaimedTrueDetail: 'skipped — agent advertises extendedAgentCard=true',
      expectedCode: -32004,
      expectedCodeName: 'UnsupportedOperationError',
      method: 'agent/getAuthenticatedExtendedCard',
      params: {},
      specCite: '§3.1.7',
      opLabel: 'extended-card op',
    }),
};

// `assert` is imported but kept for parity with the other contract
// modules; the helper above raises Error directly for clarity.
void assert;
