import { useMemo, useState } from 'react';
import type { Decision, Verdict } from './acsEvaluator';
import { type AgUiEvent, projectVerdict, resolveEscalation } from './agUiProjection';

/** One real verdict from the last canvas run, with a human-readable label
 *  (e.g. "step 2 · alice → carol · pre_tool_call"). Built in App.tsx. */
export interface RunVerdict {
  label: string;
  verdict: Verdict;
}

interface AgUiPanelProps {
  /** Real verdicts produced by the last scenario run (loaded YAML + active
   *  ACS manifest). Empty until the user runs a scenario with Preview ACS on. */
  runVerdicts?: RunVerdict[];
  scenarioName?: string;
  onOpenScenario?: () => void;
}

// --- the narrated governed run ------------------------------------------------

interface RunEvent {
  t: string;
  side: 'agent' | 'human';
  proto: string;
  gate?: string;
  desc: string;
  json?: string;
}

const RUN: RunEvent[] = [
  {
    t: 'RUN_STARTED',
    side: 'agent',
    proto: 'AG-UI lifecycle',
    desc: 'threadId t1, runId r1 — the run begins.',
  },
  {
    t: 'STATE_SNAPSHOT',
    side: 'human',
    proto: 'Sauvidya / PACE',
    desc: 'Accessibility envelope published before any gate (invariant B-5) so the UI adapts modality and timing.',
    json: `{
  "type": "STATE_SNAPSHOT",
  "snapshot": {
    "https://ravikiran438.github.io/sauvidya-pace/v1": {
      "supported_modalities": ["voice","large_text"],
      "language": "te", "response_window_ms": 300000
    }
  }
}`,
  },
  {
    t: 'RUN_FINISHED · interrupt',
    side: 'human',
    proto: 'Anumati / ACAP',
    gate: 'Consent gate',
    desc: 'Run pauses for a human decision before the consequential action. reason: confirmation.',
    json: `{
  "type": "RUN_FINISHED",
  "outcome": { "type": "interrupt", "interrupts": [ {
    "id": "acap-consent-sha256:9f2c",
    "reason": "confirmation",
    "message": "Share your pharmacy records with the pricing agent?",
    "metadata": { "governance": {
      "uri": "https://ravikiran438.github.io/agent-consent-protocol/v1",
      "type": "ConsentRecord", "policy_hash": "sha256:9f2c" } }
  } ] }
}`,
  },
  {
    t: 'resume',
    side: 'human',
    proto: 'Anumati / ACAP',
    gate: 'Human decides',
    desc: 'Same threadId. The decision — including a denial — is carried IN the payload (B-3), never as a bare cancel.',
    json: `{
  "resume": [ {
    "interruptId": "acap-consent-sha256:9f2c",
    "status": "resolved",
    "payload": { "decision": "accepted", "policy_hash": "sha256:9f2c" }
  } ]
}
// -> typed ConsentRecord(decision=ACCEPTED)`,
  },
  {
    t: 'TOOL_CALL_* / TEXT_MESSAGE_*',
    side: 'agent',
    proto: 'work',
    desc: 'The agent performs the now-authorized action and streams the output.',
  },
  {
    t: 'ACTIVITY',
    side: 'agent',
    proto: 'Pramana',
    desc: 'Each consequential output carries a ClaimAttestation as an inspectable Activity event — surfaced for audit, not a gate.',
    json: `{
  "type": "ACTIVITY", "activityType": "ATTESTATION",
  "value": {
    "claim": "lowest in-network price = $42.00",
    "source": "pharmacy_api#resp_88", "verified": true
  }
}`,
  },
  {
    t: 'RUN_FINISHED · interrupt',
    side: 'human',
    proto: 'Phala',
    gate: 'Satisfaction',
    desc: "End-of-task: 'did this serve you?' reason: input_required. (Or a volunteered MetaEvent thumbs-up.)",
    json: `{
  "type": "RUN_FINISHED",
  "outcome": { "type": "interrupt", "interrupts": [ {
    "id": "phala-sat-outcome-1",
    "reason": "input_required",
    "message": "Did this outcome serve you?",
    "metadata": { "governance": {
      "uri": "https://ravikiran438.github.io/phala-protocol/v1",
      "type": "SatisfactionRecord", "outcome_event_id": "outcome-1" } }
  } ] }
}`,
  },
  {
    t: 'resume',
    side: 'human',
    proto: 'Phala',
    gate: 'Human rates',
    desc: 'valence in [-1,1] -> typed SatisfactionRecord. The BeliefUpdate then propagates through the agent network, unchanged by transport.',
    json: `{
  "resume": [ {
    "interruptId": "phala-sat-outcome-1",
    "status": "resolved",
    "payload": { "valence": 0.8 }
  } ]
}
// -> SatisfactionRecord(valence=0.8, source=EXPLICIT, confidence=1.0)`,
  },
  {
    t: 'RUN_FINISHED',
    side: 'agent',
    proto: 'AG-UI lifecycle',
    desc: 'outcome: { type: success } — the loop is closed.',
  },
];

function RunEventRow({ ev }: { ev: RunEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={`agui-ev ${ev.side} ${ev.gate ? 'gate' : ''}`}>
      <button
        type="button"
        className="agui-ev-head"
        onClick={() => ev.json && setOpen((o) => !o)}
        style={{ cursor: ev.json ? 'pointer' : 'default' }}
      >
        <span className="agui-etype">{ev.t}</span>
        <span className="agui-proto">{ev.proto}</span>
        {ev.gate && <span className="agui-gate-tag">{ev.gate}</span>}
        {ev.json && <span className="agui-arrow">{open ? '▾' : '▸'}</span>}
      </button>
      <div className="agui-ev-desc">{ev.desc}</div>
      {open && ev.json && <pre className="inspector-json">{ev.json}</pre>}
    </li>
  );
}

// --- interactive verdict -> AG-UI projector -----------------------------------

const DECISIONS: Decision[] = ['allow', 'warn', 'deny', 'escalate'];

const DECISION_REASON: Record<Decision, string> = {
  allow: 'no rule matched; applied default decision',
  warn: 'recipient outside declared partner set',
  deny: 'recipient on block list',
  escalate: 'cross-border PII transfer needs human review',
};

function VerdictProjector() {
  const [decision, setDecision] = useState<Decision>('escalate');
  const [resolved, setResolved] = useState<Decision | null>(null);

  const verdict: Verdict = useMemo(
    () => ({
      decision,
      intervention_point: 'pre_tool_call',
      policy_id: 'pii-guard',
      reasons: [DECISION_REASON[decision]],
      rule_name: 'rule-1',
      failed_closed: false,
    }),
    [decision],
  );

  const event: AgUiEvent = useMemo(() => projectVerdict(verdict), [verdict]);
  const isEscalate = event.type === 'RUN_FINISHED';

  function decide(approved: boolean) {
    if (event.type !== 'RUN_FINISHED') return;
    const it = event.outcome.interrupts[0];
    setResolved(
      resolveEscalation(it, { interruptId: it.id, status: 'resolved', payload: { approved } }),
    );
  }

  return (
    <div className="agui-projector">
      <div className="agui-proj-controls">
        <span className="agui-proj-label">ACS verdict:</span>
        {DECISIONS.map((d) => (
          <button
            key={d}
            type="button"
            className={`btn small ${d === decision ? 'primary' : ''}`}
            onClick={() => {
              setDecision(d);
              setResolved(null);
            }}
          >
            {d}
          </button>
        ))}
      </div>
      <div className="agui-proj-maps">
        projects to{' '}
        <code>
          {event.type === 'RUN_FINISHED'
            ? 'RUN_FINISHED · interrupt (confirmation)'
            : event.type === 'RUN_ERROR'
              ? 'RUN_ERROR (acs_deny)'
              : 'CUSTOM annotation'}
        </code>
      </div>
      <pre className="inspector-json">{JSON.stringify(event, null, 2)}</pre>
      {isEscalate && (
        <div className="agui-resolve">
          <span className="agui-resolve-label">Human-in-the-loop:</span>
          <button type="button" className="btn small" onClick={() => decide(true)}>
            Approve
          </button>
          <button type="button" className="btn small" onClick={() => decide(false)}>
            Deny
          </button>
          {resolved && (
            <span className={`agui-resolved acs-${resolved}`}>
              resolved → <strong>{resolved}</strong>
              {resolved === 'deny' ? ' (fail-closed)' : ''}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** One real verdict from the last run, projected onto AG-UI. Same display as
 *  the Inspector row; escalate gets a fail-closed Approve/Deny. */
function RealVerdictRow({ label, verdict }: RunVerdict) {
  const [open, setOpen] = useState(false);
  const [resolved, setResolved] = useState<Decision | null>(null);
  const event: AgUiEvent = projectVerdict(verdict);
  const mapLabel =
    event.type === 'RUN_FINISHED'
      ? 'RUN_FINISHED · interrupt'
      : event.type === 'RUN_ERROR'
        ? 'RUN_ERROR'
        : 'CUSTOM';
  const isEscalate = event.type === 'RUN_FINISHED';

  function decide(approved: boolean) {
    if (event.type !== 'RUN_FINISHED') return;
    const it = event.outcome.interrupts[0];
    setResolved(
      resolveEscalation(it, { interruptId: it.id, status: 'resolved', payload: { approved } }),
    );
  }

  return (
    <li className={`agui-row acs-${verdict.decision}`}>
      <button type="button" className="agui-head" onClick={() => setOpen((o) => !o)}>
        <span className="agui-arrow">{open ? '▾' : '▸'}</span>
        <span className="acs-decision">{verdict.decision}</span>
        <span className="agui-maps">→ {mapLabel}</span>
        <span className="agui-ip">{label}</span>
      </button>
      {open && (
        <div className="agui-detail">
          <pre className="inspector-json">{JSON.stringify(event, null, 2)}</pre>
          {isEscalate && (
            <div className="agui-resolve">
              <span className="agui-resolve-label">Human-in-the-loop:</span>
              <button type="button" className="btn small" onClick={() => decide(true)}>
                Approve
              </button>
              <button type="button" className="btn small" onClick={() => decide(false)}>
                Deny
              </button>
              {resolved && (
                <span className={`agui-resolved acs-${resolved}`}>
                  resolved → <strong>{resolved}</strong>
                  {resolved === 'deny' ? ' (fail-closed)' : ''}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export function AgUiPanel({ runVerdicts = [], scenarioName, onOpenScenario }: AgUiPanelProps) {
  return (
    <div className="agui-shell">
      <div className="agui-intro">
        <h1>Governance over AG-UI</h1>
        <p>
          The testbed governs the agent&#8596;agent axis (A2A handoffs evaluated against an ACS
          manifest).{' '}
          <a href="https://github.com/ag-ui-protocol/ag-ui" target="_blank" rel="noreferrer">
            AG-UI
          </a>{' '}
          is the orthogonal agent&#8596;human axis. When a governance decision needs a person, it
          projects onto AG-UI's interrupt mechanism. These reference projections mirror{' '}
          <code>a2a_testbed.ag_ui</code> exactly.
        </p>
      </div>

      <section className="agui-block agui-interactive">
        <div className="agui-block-head">
          <span className="agui-badge interactive">Live · from your run</span>
          <h2>Your scenario's verdicts, projected onto AG-UI</h2>
        </div>
        {runVerdicts.length > 0 ? (
          <>
            <p className="agui-sub">
              The real ACS verdicts from your last run
              {scenarioName ? (
                <>
                  {' '}
                  of <strong>{scenarioName}</strong>
                </>
              ) : null}{' '}
              — computed from the loaded scenario and the active manifest, each projected by the
              same <code>projectVerdict</code> the testbed uses. Expand a row for the AG-UI event;{' '}
              <code>escalate</code> rows resolve fail-closed.
            </p>
            <ul className="agui-projection">
              {runVerdicts.map((rv, i) => (
                <RealVerdictRow key={i} label={rv.label} verdict={rv.verdict} />
              ))}
            </ul>
          </>
        ) : (
          <div className="agui-empty">
            <p className="agui-sub">
              No verdicts yet. Open <strong>Scenario</strong>, turn on <strong>Preview ACS</strong>{' '}
              (optionally load your own manifest), and <strong>Run</strong>. Then return here to see
              this scenario's real verdicts projected onto AG-UI.
            </p>
            {onOpenScenario && (
              <button type="button" className="btn small primary" onClick={onOpenScenario}>
                Open Scenario →
              </button>
            )}
          </div>
        )}
      </section>

      <section className="agui-block">
        <div className="agui-block-head">
          <span className="agui-badge reference">Sandbox</span>
          <h2>Or project any verdict by hand</h2>
        </div>
        <p className="agui-sub">
          The core primitive in isolation: one ACS verdict becomes one AG-UI event. Pick a verdict —
          <code>allow</code>/<code>warn</code> surface as a non-blocking annotation,{' '}
          <code>deny</code> is a terminal error, <code>escalate</code> becomes a human-in-the-loop
          interrupt you can resolve (fail-closed — only Approve yields <code>allow</code>). This
          control changes only this panel.
        </p>
        <VerdictProjector />
      </section>

      <div className="agui-divider">
        <span>composed across protocols ↓</span>
      </div>

      <section className="agui-block agui-reference">
        <div className="agui-block-head">
          <span className="agui-badge reference">Reference walkthrough · static</span>
          <h2>A full governed run, end to end</h2>
        </div>
        <p className="agui-sub">
          A fixed illustration — not driven by the selector above. One human-facing task carries{' '}
          <strong>several</strong> protocols over a single AG-UI run, and its gates are ACAP / PACE
          / Phala interrupts (not ACS verdicts). The <code>escalate</code> case above is where an
          ACS gate would slot into a run like this. Amber rows are the agent&#8596;human edge;{' '}
          <span className="agui-gate-tag inline">gates</span> pause for a person. Click a row with a
          ▸ for its wire JSON.
        </p>
        <ul className="agui-stream">
          {RUN.map((ev, i) => (
            <RunEventRow key={i} ev={ev} />
          ))}
        </ul>
      </section>

      <div className="agui-foot">
        Reference bindings:{' '}
        <a href="https://github.com/ravikiran438/sauvidya-pace" target="_blank" rel="noreferrer">
          PACE
        </a>
        ,{' '}
        <a
          href="https://github.com/ravikiran438/agent-consent-protocol"
          target="_blank"
          rel="noreferrer"
        >
          ACAP
        </a>
        ,{' '}
        <a href="https://github.com/ravikiran438/phala-protocol" target="_blank" rel="noreferrer">
          Phala
        </a>
        , and{' '}
        <a href="https://github.com/ravikiran438/a2a-testbed" target="_blank" rel="noreferrer">
          a2a-testbed
        </a>
        .
      </div>
    </div>
  );
}
