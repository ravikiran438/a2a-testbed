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
  onLoadCardForAgent?: (cardId: string) => void;
}

export function Inspector({
  target,
  agentCard,
  agentMeta,
  step,
  stepResult,
  onLoadCardForAgent,
}: Props) {
  if (!target) {
    return (
      <div className="inspector-empty">
        Click an agent or an edge to inspect its AgentCard or message
        payload.
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
          <div className="inspector-value description">
            {agentCard.description}
          </div>
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
          <pre className="inspector-json">
            {JSON.stringify(agentCard, null, 2)}
          </pre>
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
          <div className="inspector-value">
            {agentMeta.role.replace('_', ' ')}
          </div>
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
            The scenario YAML referenced{' '}
            {filename ? <code>{filename}</code> : 'a card file'}, but the
            browser can&apos;t follow file paths. Upload the JSON to see
            the full card here.
          </div>
          {onLoadCardForAgent && (
            <button
              className="btn primary small"
              onClick={() => onLoadCardForAgent(agentMeta.id)}
            >
              {filename ? `Upload ${filename}` : 'Upload card JSON'}
            </button>
          )}
        </div>
      </div>
    );
  }

  if (target.kind === 'step' && step) {
    const validationClass =
      step.validation?.finding === 'declared_ok'
        ? 'finding-ok'
        : 'finding-fail';
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

        {/* User-authored expectations from the YAML. When the step
            ran against a real external agent we render the live
            check results; otherwise the static "not enforced" note. */}
        {step.expect && stepResult && (
          <div className="inspector-section">
            <div className="inspector-label">Live result</div>
            <div
              className={`inspector-finding ${
                stepResult.ok ? 'finding-ok' : 'finding-fail'
              }`}
            >
              <strong>
                {stepResult.ok ? '✓ all checks passed' : '✗ failed'}
              </strong>
              <div>
                HTTP {stepResult.status || '—'}
                {stepResult.error ? ` · ${stepResult.error}` : ''}
              </div>
            </div>
            <ul className="inspector-checks">
              {stepResult.checks.map((c, i) => (
                <li
                  key={i}
                  className={c.ok ? 'check-ok' : 'check-fail'}
                >
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
              <strong>Not enforced for this step.</strong> The browser
              runs real HTTP only for agents declared{' '}
              <code>runtime: external</code> with a <code>url:</code>.
              For other steps, run the scenario through the CLI:{' '}
              <code>a2a-testbed run scenario.yaml</code>
            </div>
            <pre className="inspector-json">
              {JSON.stringify(step.expect, null, 2)}
            </pre>
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
          <pre className="inspector-json">
            {JSON.stringify(step.message, null, 2)}
          </pre>
        </div>
      </div>
    );
  }

  return null;
}
