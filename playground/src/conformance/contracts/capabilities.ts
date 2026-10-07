// Capability ↔ method consistency contracts. When an AgentCard claims
// a capability is `false`, the matching method must refuse. Strictness:
// 200+result is a hard fail (the agent lied about its capability);
// any error response is a soft pass with the deviation in the detail
// when the error code doesn't match the spec-mandated one.

import type { Op } from '../dialect';
import { pushSetParams } from '../dialect';
import { assert, jsonRpcCall } from '../transport';
import type { Contract } from '../types';
import { AgentProbe } from './_probe';

interface CapabilityProbeOpts {
  capabilityKey: 'streaming' | 'pushNotifications' | 'extendedAgentCard';
  capabilityClaimedTrueDetail: string;
  expectedCode: number;
  expectedCodeName: string;
  /** Operation probed, in whichever version the agent speaks. */
  op: Op;
  params: (probe: AgentProbe) => unknown;
  /** §-citation used in the soft-pass message. */
  specCite: string;
  /** Human label for the operation; defaults to the method name. */
  opLabel?: string;
}

async function runCapabilityProbe(
  agentUrl: string,
  opts: CapabilityProbeOpts,
): Promise<undefined | string> {
  const probe = await AgentProbe.create(agentUrl);
  // Read from the 1.0 view so a 0.3 card's top-level
  // supportsAuthenticatedExtendedCard counts as extendedAgentCard.
  if (probe.capability(opts.capabilityKey) === true) {
    return opts.capabilityClaimedTrueDetail;
  }
  const label = opts.opLabel ?? probe.method(opts.op);

  const { body, status } = await jsonRpcCall(
    agentUrl,
    probe.method(opts.op),
    opts.params(probe),
    `cap-${opts.capabilityKey}`,
    probe.headers(),
  );

  if (!body || typeof body !== 'object') {
    throw new Error(
      `agent advertises ${opts.capabilityKey}=false but ${label} ` +
        `returned non-JSON (status ${status})`,
    );
  }
  const obj = body as Record<string, unknown>;
  if ('result' in obj && !('error' in obj)) {
    throw new Error(
      `agent advertises ${opts.capabilityKey}=false but ${label} ` +
        `returned a result; per ${opts.specCite} it MUST return ` +
        `${opts.expectedCodeName} (${opts.expectedCode})`,
    );
  }
  const error = (obj.error ?? {}) as Record<string, unknown>;
  const code = error.code;
  if (code === opts.expectedCode) return; // strict pass
  // Soft pass: capability honored, wrong error code.
  return (
    `capability honored — agent refused ${label} as required ` +
    `(${opts.specCite}), but returned code ${code} ` +
    `(${error.message ?? '?'}); spec mandates ${opts.expectedCode} ` +
    `(${opts.expectedCodeName})`
  );
}

export const streamingCapabilityConsistency: Contract = {
  id: 'transport.streaming_capability_consistency',
  specSection: '§3.1.2',
  description: 'SendStreamingMessage returns -32004 when streaming=false.',
  category: 'transport',
  verify: (agentUrl) =>
    runCapabilityProbe(agentUrl, {
      capabilityKey: 'streaming',
      capabilityClaimedTrueDetail: 'skipped — agent advertises streaming=true',
      expectedCode: -32004,
      expectedCodeName: 'UnsupportedOperationError',
      op: 'stream',
      params: (p) => p.sendParams('probe'),
      specCite: '§3.1.2',
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
      op: 'push_set',
      params: (p) =>
        pushSetParams(
          p.dialect,
          '00000000-0000-0000-0000-000000000000',
          'https://example.invalid/webhook',
        ),
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
      op: 'extended_card',
      params: () => ({}),
      specCite: '§3.1.7',
      opLabel: 'extended-card op',
    }),
};

// `assert` is imported but kept for parity with the other contract
// modules; the helper above raises Error directly for clarity.
void assert;
