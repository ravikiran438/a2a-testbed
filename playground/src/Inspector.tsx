import { useState } from 'react';
import type { Verdict } from './acsEvaluator';
import { type AgUiEvent, projectVerdict, resolveEscalation } from './agUiProjection';
import type { AgentCard, ScenarioStep } from './scenario';

export type InspectorTarget =
  | { kind: 'agent'; id: string; cardId: string }
  | { kind: 'step'; index: number };

/**
 * Minimal agent metadata used by the inspector when the full
 * AgentCard isn't loaded yet (custom-scenario flow before the
 * user has uploaded that agent's JSON).
 */
export interface AgentMeta {
  id: string;
  label: string;
  role: string;
  cardHint?: string;
}

/**
 * Output of a real HTTP execution against an external agent.
 * Populated by App.tsx#runScenario for steps whose target carries
 * `runtime: external` + `url`. Animation-only steps don't produce
 * one of these. Shape kept small + serializable so it can also
 * land in localStorage someday without churn.
 */
export interface StepRunResult {
  /** True when the response satisfied every expect check. */
  ok: boolean;
  /** Always true here — present for forward-compatibility if we
   *  ever record results for simulated steps too. */
  executedExternal: boolean;
  /** HTTP status code; 0 when the fetch itself failed. */
  status: number;
  /** First ~400 chars of the response body. */
  bodySnippet: string;
  /** Per-check breakdown for the inspector. */
  checks: Array<{ name: string; ok: boolean; detail: string }>;
  /** Network-level error string when the fetch failed. */
  error?: string;
}

interface Props {
  target: InspectorTarget | null;
  agentCard?: AgentCard;
  agentMeta?: AgentMeta;
  step?: ScenarioStep;
  /** Real-execution result for the focused step, if any. */
  stepResult?: StepRunResult;
  /** ACS runtime-governance verdicts for the focused step, if any. */
  acsVerdicts?: Verdict[];
  onLoadCardForAgent?: (cardId: string) => void;
}

export function Inspector({
  target,
  agentCard,
  agentMeta,
  step,
  stepResult,
  acsVerdicts,
  onLoadCardForAgent,
}: Props) {
  if (!target) {
    return (
      <div className="inspector-empty">
        Click an agent or an edge to inspect its AgentCard or message payload.
      </div>
    );
  }

  // Agent click — full AgentCard is loaded.
  if (target.kind === 'agent' && agentCard) {
    return (
      <div className="inspector-body">
        <div className="inspector-section">
          <div className="inspector-label">Name</div>
          <div className="inspector-value">{agentCard.name}</div>
        </div>
        <div className="inspector-section">
          <div className="inspector-label">Description</div>
          <div className="inspector-value description">{agentCard.description}</div>
        </div>
        <div className="inspector-section">
          <div className="inspector-label">Declared extensions</div>
          <ul className="inspector-extensions">
            {agentCard.capabilities.extensions.map((ext) => (
              <li key={ext.uri}>
                <code>{ext.uri}</code>
                <div className="ext-desc">{ext.description}</div>
              </li>
            ))}
          </ul>
        </div>
        <div className="inspector-section">
          <div className="inspector-label">AgentCard JSON</div>
          <pre className="inspector-json">{JSON.stringify(agentCard, null, 2)}</pre>
        </div>
      </div>
    );
  }

  // Agent click — card not loaded yet. Show what we know (id, role,
  // path hint) and offer a one-click upload.
  if (target.kind === 'agent' && agentMeta) {
    const filename = agentMeta.cardHint?.split(/[\\/]/).pop();
    return (
      <div className="inspector-body">
        <div className="inspector-section">
          <div className="inspector-label">Agent ID</div>
          <div className="inspector-value">
            <code>{agentMeta.id}</code>
          </div>
        </div>
        <div className="inspector-section">
          <div className="inspector-label">Role</div>
          <div className="inspector-value">{agentMeta.role.replace('_', ' ')}</div>
        </div>
        {agentMeta.cardHint && (
          <div className="inspector-section">
            <div className="inspector-label">Expected AgentCard file</div>
            <div className="inspector-value">
              <code>{agentMeta.cardHint}</code>
            </div>
          </div>
        )}
        <div className="inspector-pending">
          <strong>AgentCard not loaded.</strong>
          <div>
            The scenario YAML referenced {filename ? <code>{filename}</code> : 'a card file'}, but
            the browser can&apos;t follow file paths. Upload the JSON to see the full card here.
          </div>
          {onLoadCardForAgent && (
            <button className="btn primary small" onClick={() => onLoadCardForAgent(agentMeta.id)}>
              {filename ? `Upload ${filename}` : 'Upload card JSON'}
            </button>
          )}
        </div>
      </div>
    );
  }

  if (target.kind === 'step' && step) {
    const validationClass =
      step.validation?.finding === 'declared_ok' ? 'finding-ok' : 'finding-fail';
    return (
      <div className="inspector-body">
        <div className="inspector-section">
          <div className="inspector-label">Step</div>
          <div className="inspector-value">
            {step.from} <span className="arrow">→</span> {step.to}
          </div>
        </div>
        <div className="inspector-section">
          <div className="inspector-label">Action</div>
          <div className="inspector-value">{step.action}</div>
        </div>
        {step.extension_uri && (
          <div className="inspector-section">
            <div className="inspector-label">Extension URI</div>
            <div className="inspector-value">
              <code>{step.extension_uri}</code>
            </div>
          </div>
        )}

        {/* ACS runtime-governance verdicts for this step's handoff,
            when an ACS manifest is applied. One row per evaluated
            intervention point, colored by decision. */}
        {acsVerdicts && acsVerdicts.length > 0 && (
          <div className="inspector-section">
            <div className="inspector-label">ACS governance</div>
            <ul className="inspector-checks acs-verdicts">
              {acsVerdicts.map((v, i) => (
                <li key={i} className={`acs-${v.decision}`}>
                  <span className="acs-decision">{v.decision}</span>
                  <span className="check-name">{v.intervention_point}</span>
                  <span className="check-detail">
                    {(v.reasons || []).join('; ')}
                    {v.failed_closed ? ' (fail-closed)' : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Governance over AG-UI: each ACS verdict for this handoff,
            projected onto the agent<->human transport. escalate becomes
            an interactive human-in-the-loop interrupt; deny a RUN_ERROR;
            allow/warn a CUSTOM annotation. Mirrors a2a_testbed.ag_ui. */}
        {acsVerdicts && acsVerdicts.length > 0 && (
          <div className="inspector-section">
            <div className="inspector-label">Governance over AG-UI</div>
            <ul className="agui-projection">
              {acsVerdicts.map((v, i) => (
                <AgUiVerdictRow key={i} verdict={v} />
              ))}
            </ul>
          </div>
        )}

        {/* User-authored expectations from the YAML. When the step
            ran against a real external agent we render the live
            check results; otherwise the static "not enforced" note. */}
        {step.expect && stepResult && (
          <div className="inspector-section">
            <div className="inspector-label">Live result</div>
            <div className={`inspector-finding ${stepResult.ok ? 'finding-ok' : 'finding-fail'}`}>
              <strong>{stepResult.ok ? '✓ all checks passed' : '✗ failed'}</strong>
              <div>
                HTTP {stepResult.status || '—'}
                {stepResult.error ? ` · ${stepResult.error}` : ''}
              </div>
            </div>
            <ul className="inspector-checks">
              {stepResult.checks.map((c, i) => (
                <li key={i} className={c.ok ? 'check-ok' : 'check-fail'}>
                  <span className="check-mark">{c.ok ? '✓' : '✗'}</span>
                  <span className="check-name">{c.name}</span>
                  <span className="check-detail">{c.detail}</span>
                </li>
              ))}
            </ul>
            {stepResult.bodySnippet && (
              <>
                <div className="inspector-label" style={{ marginTop: 8 }}>
                  Response body (first 400 chars)
                </div>
                <pre className="inspector-json">{stepResult.bodySnippet}</pre>
              </>
            )}
          </div>
        )}
        {step.expect && !stepResult && (
          <div className="inspector-section">
            <div className="inspector-label">Expectations (from YAML)</div>
            <div className="inspector-not-enforced">
              <strong>Not enforced for this step.</strong> The browser runs real HTTP only for
              agents declared <code>runtime: external</code> with a <code>url:</code>. For other
              steps, run the scenario through the CLI: <code>a2a-testbed run scenario.yaml</code>
            </div>
            <pre className="inspector-json">{JSON.stringify(step.expect, null, 2)}</pre>
          </div>
        )}

        {/* Real validation finding — only present on the bundled
            scenario where each step has a hand-authored outcome.
            Custom-loaded scenarios don't carry findings. */}
        {step.validation && (
          <div className="inspector-section">
            <div className="inspector-label">Validation</div>
            <div className={`inspector-finding ${validationClass}`}>
              <strong>{step.validation.finding}</strong>
              <div>{step.validation.detail}</div>
            </div>
          </div>
        )}

        <div className="inspector-section">
          <div className="inspector-label">Message payload</div>
          <pre className="inspector-json">{JSON.stringify(step.message, null, 2)}</pre>
        </div>
      </div>
    );
  }

  return null;
}

/**
 * One ACS verdict, projected onto AG-UI. Shows the event type the verdict
 * maps to and its wire JSON. For an `escalate` verdict the projection is a
 * human-in-the-loop interrupt, so we render Approve/Deny — the resolution is
 * fail-closed (only Approve yields `allow`), mirroring resolveEscalation().
 */
function AgUiVerdictRow({ verdict }: { verdict: Verdict }) {
  const [open, setOpen] = useState(false);
  const [resolved, setResolved] = useState<'allow' | 'deny' | null>(null);
  const event: AgUiEvent = projectVerdict(verdict);

  const label =
    event.type === 'RUN_FINISHED'
      ? 'RUN_FINISHED · interrupt'
      : event.type === 'RUN_ERROR'
        ? 'RUN_ERROR'
        : 'CUSTOM';

  const isEscalate = event.type === 'RUN_FINISHED';

  function decide(approved: boolean) {
    if (event.type !== 'RUN_FINISHED') return;
    const interrupt = event.outcome.interrupts[0];
    const decision = resolveEscalation(interrupt, {
      interruptId: interrupt.id,
      status: 'resolved',
      payload: { approved },
    });
    setResolved(decision as 'allow' | 'deny');
  }

  return (
    <li className={`agui-row acs-${verdict.decision}`}>
      <button type="button" className="agui-head" onClick={() => setOpen((o) => !o)}>
        <span className="agui-arrow">{open ? '▾' : '▸'}</span>
        <span className="acs-decision">{verdict.decision}</span>
        <span className="agui-maps">→ {label}</span>
        <span className="agui-ip">{verdict.intervention_point}</span>
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
