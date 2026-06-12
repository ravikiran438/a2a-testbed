// Browser-side AG-UI projection — mirrors a2a_testbed/ag_ui/projection.py.
//
// AG-UI (Agent-User Interaction protocol) is the agent <-> human transport.
// The testbed evaluates inter-agent exchanges against an ACS manifest and
// produces a normalized Verdict (allow / warn / deny / escalate). This module
// renders those verdicts onto the AG-UI event stream under the cross-cutting
// "Governance over AG-UI" convention, so a governed scenario can be replayed
// with a human in the loop:
//
//   * allow    -> a CUSTOM annotation; the run continues.
//   * warn     -> a CUSTOM annotation (surfaced, non-blocking); continues.
//   * deny     -> a terminal RUN_ERROR; the action is blocked.
//   * escalate -> a RUN_FINISHED interrupt (reason "confirmation"): the run
//                 pauses for human review; the resume decides allow vs. deny.
//
// Resolution is fail-closed — an abandoned (cancelled) or un-approved resume
// resolves to deny. Keep in lockstep with projection.py: a behavior change in
// one must land in both (two-surfaces parity).

import type { Decision, Verdict } from './acsEvaluator';

// Stable governance identity for ACS verdicts on the AG-UI transport. Mirrors
// the role the per-protocol extension URI plays for the published protocols.
export const ACS_GOVERNANCE_URI = 'acs';
export const GOVERNANCE_KEY = 'governance';

export interface GovernanceMeta {
  uri: string;
  type: 'Verdict';
  decision: Decision;
  intervention_point: string;
  policy_id?: string | null;
  rule_name?: string | null;
  failed_closed: boolean;
}

export interface AgUiInterrupt {
  id: string;
  reason: string;
  message: string;
  responseSchema: Record<string, unknown>;
  metadata: { [GOVERNANCE_KEY]: GovernanceMeta };
}

export type AgUiEvent =
  | { type: 'RUN_FINISHED'; outcome: { type: 'interrupt'; interrupts: AgUiInterrupt[] } }
  | {
      type: 'RUN_ERROR';
      message: string;
      code: string;
      metadata: { [GOVERNANCE_KEY]: GovernanceMeta };
    }
  | {
      type: 'CUSTOM';
      name: string;
      value: {
        decision: Decision;
        intervention_point: string;
        reasons: string[];
        policy_id?: string | null;
      };
    };

export interface ResumeInput {
  interruptId?: string;
  status: 'resolved' | 'cancelled';
  payload?: { approved?: boolean } | null;
}

const APPROVAL_SCHEMA: Record<string, unknown> = {
  type: 'object',
  properties: {
    approved: {
      type: 'boolean',
      description: 'True to allow the escalated action, false to deny it.',
    },
  },
  required: ['approved'],
};

function governanceMeta(verdict: Verdict): GovernanceMeta {
  return {
    uri: ACS_GOVERNANCE_URI,
    type: 'Verdict',
    decision: verdict.decision,
    intervention_point: verdict.intervention_point,
    policy_id: verdict.policy_id ?? null,
    rule_name: verdict.rule_name ?? null,
    failed_closed: verdict.failed_closed,
  };
}

function reasonText(verdict: Verdict): string {
  return verdict.reasons?.length ? verdict.reasons.join('; ') : verdict.decision;
}

/** Render one ACS Verdict as a single AG-UI event. escalate -> human-in-the-
 *  loop interrupt; deny -> terminal RUN_ERROR; allow/warn -> CUSTOM annotation. */
export function projectVerdict(verdict: Verdict): AgUiEvent {
  const meta = governanceMeta(verdict);

  if (verdict.decision === 'escalate') {
    return {
      type: 'RUN_FINISHED',
      outcome: {
        type: 'interrupt',
        interrupts: [
          {
            id: `acs-escalate-${verdict.intervention_point}`,
            reason: 'confirmation',
            message: reasonText(verdict),
            responseSchema: APPROVAL_SCHEMA,
            metadata: { [GOVERNANCE_KEY]: meta },
          },
        ],
      },
    };
  }

  if (verdict.decision === 'deny') {
    return {
      type: 'RUN_ERROR',
      message: reasonText(verdict),
      code: 'acs_deny',
      metadata: { [GOVERNANCE_KEY]: meta },
    };
  }

  // allow or warn: a non-blocking annotation the UI can surface.
  return {
    type: 'CUSTOM',
    name: ACS_GOVERNANCE_URI,
    value: {
      decision: verdict.decision,
      intervention_point: verdict.intervention_point,
      reasons: [...(verdict.reasons ?? [])],
      policy_id: verdict.policy_id ?? null,
    },
  };
}

/** Resolve a human's response to an ACS escalation interrupt. Returns 'allow'
 *  only when the resume is 'resolved' with payload.approved === true.
 *  Everything else — explicit denial, an abandoned 'cancelled' resume, or a
 *  missing payload — resolves fail-closed to 'deny'. Throws if the interrupt is
 *  not an ACS escalation (governance identity check). */
export function resolveEscalation(interrupt: AgUiInterrupt, resume: ResumeInput): Decision {
  const gov = interrupt.metadata?.[GOVERNANCE_KEY];
  if (!gov || gov.uri !== ACS_GOVERNANCE_URI || gov.decision !== 'escalate') {
    throw new Error('interrupt is not an ACS escalation');
  }
  if (resume.status !== 'resolved') return 'deny'; // cancelled / abandoned -> fail-closed
  return resume.payload?.approved === true ? 'allow' : 'deny';
}
