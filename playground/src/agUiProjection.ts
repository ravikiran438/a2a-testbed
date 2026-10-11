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
//
// AG-UI 1.0: RUN_FINISHED carries threadId + runId; every escalation gets a
// unique interrupt id; RunAgentInput.resume is an array of entries keyed by
// interruptId, and an interrupt with no entry addressed to it fails closed.

import type { Decision, Verdict } from './acsEvaluator';

// Stable governance identity for ACS verdicts on the AG-UI transport. Mirrors
// the role the per-protocol extension URI plays for the published protocols.
export const ACS_GOVERNANCE_URI = 'acs';
export const GOVERNANCE_KEY = 'governance';

/** The AG-UI protocol version these events are shaped for. */
export const AG_UI_PROTOCOL_VERSION = '1.0';

/** Placeholder ids for a verdict projected outside a real AG-UI run. */
export const DEFAULT_THREAD_ID = 'acs-governance';
export const DEFAULT_RUN_ID = 'acs-governance-run';

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
  | {
      type: 'RUN_FINISHED';
      threadId: string;
      runId: string;
      outcome: { type: 'interrupt'; interrupts: AgUiInterrupt[] };
    }
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

export interface ProjectOptions {
  /** Thread of the governed run (required on RUN_FINISHED in AG-UI 1.0). */
  threadId?: string;
  /** The governed run (required on RUN_FINISHED in AG-UI 1.0). */
  runId?: string;
  /** Overrides the generated, unique interrupt id. */
  interruptId?: string;
}

function randomHex12(): string {
  // crypto.randomUUID needs a secure context; fall back for plain-http hosts.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  }
  return Array.from({ length: 12 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
}

function newInterruptId(verdict: Verdict): string {
  const suffix = randomHex12();
  return `acs-escalate-${verdict.intervention_point}-${suffix}`;
}

/** Render one ACS Verdict as a single AG-UI event. escalate -> human-in-the-
 *  loop interrupt; deny -> terminal RUN_ERROR; allow/warn -> CUSTOM annotation. */
export function projectVerdict(verdict: Verdict, opts: ProjectOptions = {}): AgUiEvent {
  const meta = governanceMeta(verdict);

  if (verdict.decision === 'escalate') {
    return {
      type: 'RUN_FINISHED',
      threadId: opts.threadId ?? DEFAULT_THREAD_ID,
      runId: opts.runId ?? DEFAULT_RUN_ID,
      outcome: {
        type: 'interrupt',
        interrupts: [
          {
            id: opts.interruptId ?? newInterruptId(verdict),
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

/** The resume entry addressed to `interruptId`, or undefined. In the AG-UI
 *  1.0 resume array entries match on interruptId; a single entry is accepted
 *  when its interruptId matches or is absent, and rejected when it differs. */
function resumeEntryFor(
  interruptId: string,
  resume: ResumeInput | readonly ResumeInput[],
): ResumeInput | undefined {
  if (!Array.isArray(resume)) {
    const entry = resume as ResumeInput;
    return entry.interruptId === undefined || entry.interruptId === interruptId ? entry : undefined;
  }
  return resume.find((e) => e?.interruptId === interruptId);
}

/** Resolve a human's response to an ACS escalation interrupt. `resume` is the
 *  AG-UI RunAgentInput.resume array or one entry from it. Returns 'allow' only
 *  when the entry addressed to this interrupt is 'resolved' with
 *  payload.approved === true. Everything else — explicit denial, an abandoned
 *  'cancelled' resume, a missing payload, or no entry for this interrupt —
 *  resolves fail-closed to 'deny'. Throws if the interrupt is not an ACS
 *  escalation (governance identity check). */
export function resolveEscalation(
  interrupt: AgUiInterrupt,
  resume: ResumeInput | readonly ResumeInput[],
): Decision {
  const gov = interrupt.metadata?.[GOVERNANCE_KEY];
  if (!gov || gov.uri !== ACS_GOVERNANCE_URI || gov.decision !== 'escalate') {
    throw new Error('interrupt is not an ACS escalation');
  }
  const entry = resumeEntryFor(interrupt.id, resume);
  if (!entry) return 'deny'; // no answer for this interrupt -> fail-closed
  if (entry.status !== 'resolved') return 'deny'; // cancelled / abandoned -> fail-closed
  const payload = entry.payload;
  const approved = payload && typeof payload === 'object' ? payload.approved : undefined;
  return approved === true ? 'allow' : 'deny';
}
