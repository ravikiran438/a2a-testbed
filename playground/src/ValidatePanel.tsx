import { useCallback, useEffect, useState } from 'react';
import {
  type AcsFinding,
  isErrorFinding,
  isWarnFinding,
  validateAcsManifest,
} from './acsValidator';
import { type Finding, validateAgentCard } from './validator';

/** Which artifact the panel is validating. AgentCard validation fetches
 *  live extension manifests; ACS validation is fully local. */
export type ValidateTarget = 'agentcard' | 'acs';

// localStorage keys — one per target so switching tabs preserves both
// drafts. Pure browser-side; nothing leaves the machine.
const SAVED_CARD_KEY = 'a2a-testbed.playground.validator.card_v1';
const SAVED_ACS_KEY = 'a2a-testbed.playground.validator.acs_v1';

interface Props {
  /** Initial artifact to validate. Lets the home page deep-link
   *  straight to the ACS tab. */
  initialTarget?: ValidateTarget;
}

const SAMPLE_CARD = {
  name: 'demo-agent',
  description: 'Sample card declaring all four reference protocols.',
  url: 'https://example.com/demo-agent',
  version: '1.0.0',
  capabilities: {
    streaming: false,
    extensions: [
      {
        uri: 'https://ravikiran438.github.io/agent-consent-protocol/v1',
        description: 'Sample extension declaration.',
        required: true,
        params: {
          version: '1.0.0',
          document_uri: 'https://example.com/.well-known/usage-policy.json',
          document_hash: `sha256:${'a'.repeat(64)}`,
          effective_date: '2026-04-01T00:00:00Z',
          acceptance_required: false,
          natural_language_uri: 'https://example.com/terms',
        },
      },
      {
        uri: 'https://ravikiran438.github.io/phala-protocol/v1',
        description: 'Sample extension declaration.',
        required: false,
        params: {
          version: '1.0.0',
          outcome_endpoint: 'https://example.com/phala/outcome',
          satisfaction_endpoint: 'https://example.com/phala/satisfaction',
          belief_update_endpoint: 'https://example.com/phala/belief-updates',
          weight_keys: ['routing.preference'],
          learning_rate: 0.05,
          weight_bounds: { min: -1, max: 1 },
        },
      },
      {
        uri: 'https://ravikiran438.github.io/pratyahara-nerve/v1',
        description: 'Sample extension declaration.',
        required: true,
        params: {
          version: '1.0.0',
          neuron_type: 'processing',
          behavioral_fingerprint: `sha256:${'0'.repeat(64)}`,
          trust_score: 0.7,
          observer_ids: ['obs-1', 'obs-2'],
        },
      },
      {
        uri: 'https://ravikiran438.github.io/sauvidya-pace/v1',
        description: 'Sample extension declaration.',
        required: true,
        params: {
          version: '1.0.0',
          pcp_endpoint: 'https://example.com/pace/pcp',
          aic_endpoint: 'https://example.com/pace/aic/{principal_id}',
          violation_notice_endpoint: 'https://example.com/pace/violations',
          supported_modalities: ['voice'],
          supported_languages: ['en'],
        },
      },
    ],
  },
  skills: [
    {
      id: 'demo',
      name: 'Demo',
      description: 'Trivial demo skill.',
      tags: ['demo'],
    },
  ],
};

// Worked ACS manifest — mirrors examples/acs/email-agent.acs.yaml.
// An A2A handoff to `send_email` is shaped as a `pre_tool_call`; the
// builtin policy denies external recipients. Runs with no OPA backend.
const SAMPLE_ACS = `agent_control_specification_version: "0.3.1-beta"

metadata:
  name: "email-agent"
  description: "Must not hand off email sends to external recipients."

policies:
  email_policy:
    type: builtin
    default_decision: allow
    rules:
      - name: deny-external-domain
        field: "policy_target.value.message.to"
        op: endswith
        value: "@external.example"
        decision: deny
        description: "recipient address is outside the org"

intervention_points:
  pre_tool_call:
    policy_target: "$.tool_call.args"
    policy_target_kind: tool_args
    tool_name_from: "$.tool_call.name"
    policy: email_policy
    evidence:
      - recipient_classifier

tools:
  send_email:
    type: Tool
    id: send_email
    clearance: internal
    security_labels:
      - internal
`;

const cardKindLabel: Record<Finding['kind'], string> = {
  declared_ok: 'declared_ok',
  declared_invalid: 'declared_invalid',
  manifest_unreachable: 'manifest_unreachable',
  manifest_malformed: 'manifest_malformed',
  no_payload: 'no_payload',
};

const cardKindClass: Record<Finding['kind'], string> = {
  declared_ok: 'finding-ok',
  declared_invalid: 'finding-fail',
  manifest_unreachable: 'finding-warn',
  manifest_malformed: 'finding-warn',
  no_payload: 'finding-warn',
};

function acsKindClass(kind: AcsFinding['kind']): string {
  if (isErrorFinding(kind)) return 'finding-fail';
  if (isWarnFinding(kind)) return 'finding-warn';
  return 'finding-ok';
}

function loadSaved(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    // localStorage can throw in private browsing or when disabled.
    return fallback;
  }
}

export function ValidatePanel({ initialTarget = 'agentcard' }: Props) {
  const [target, setTarget] = useState<ValidateTarget>(initialTarget);
  // Keep separate drafts per target.
  const [cardText, setCardText] = useState<string>(() =>
    loadSaved(SAVED_CARD_KEY, JSON.stringify(SAMPLE_CARD, null, 2)),
  );
  const [acsText, setAcsText] = useState<string>(() => loadSaved(SAVED_ACS_KEY, SAMPLE_ACS));
  const [cardFindings, setCardFindings] = useState<Finding[] | null>(null);
  const [acsFindings, setAcsFindings] = useState<AcsFinding[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Honor a changed deep-link target (home page -> ACS tab).
  useEffect(() => {
    setTarget(initialTarget);
  }, [initialTarget]);

  const text = target === 'agentcard' ? cardText : acsText;
  const setText = target === 'agentcard' ? setCardText : setAcsText;
  const saveKey = target === 'agentcard' ? SAVED_CARD_KEY : SAVED_ACS_KEY;

  // Debounced persist of the active draft.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      try {
        localStorage.setItem(saveKey, text);
        setSavedAt(Date.now());
      } catch {
        // ignore write failures (quota, private mode, etc.)
      }
    }, 500);
    return () => window.clearTimeout(handle);
  }, [text, saveKey]);

  const switchTarget = useCallback((next: ValidateTarget) => {
    setTarget(next);
    setError(null);
    setSavedAt(null);
  }, []);

  const onValidate = useCallback(async () => {
    setError(null);
    setBusy(true);
    setCardFindings(null);
    setAcsFindings(null);
    try {
      if (target === 'agentcard') {
        const card = JSON.parse(cardText);
        setCardFindings(await validateAgentCard(card));
      } else {
        // Fully local; mirrors `a2a-testbed acs validate`.
        // validateAcsManifest returns { ok, parsed, findings } — store
        // the findings array, not the whole result object.
        setAcsFindings(validateAcsManifest(acsText).findings);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [target, cardText, acsText]);

  const onLoadSample = useCallback(() => {
    if (target === 'agentcard') {
      setCardText(JSON.stringify(SAMPLE_CARD, null, 2));
      setCardFindings(null);
    } else {
      setAcsText(SAMPLE_ACS);
      setAcsFindings(null);
    }
    setError(null);
  }, [target]);

  const onClearSaved = useCallback(() => {
    try {
      localStorage.removeItem(saveKey);
    } catch {
      /* ignore */
    }
    if (target === 'agentcard') {
      setCardText(JSON.stringify(SAMPLE_CARD, null, 2));
      setCardFindings(null);
    } else {
      setAcsText(SAMPLE_ACS);
      setAcsFindings(null);
    }
    setError(null);
    setSavedAt(null);
  }, [target, saveKey]);

  const isAcs = target === 'acs';
  const validateLabel = isAcs
    ? busy
      ? 'Validating…'
      : 'Validate ACS manifest'
    : busy
      ? 'Validating…'
      : 'Validate against live manifests';

  // ACS summary counts.
  const acsOk = acsFindings ? !acsFindings.some((f) => isErrorFinding(f.kind)) : false;
  const acsErrors = acsFindings?.filter((f) => isErrorFinding(f.kind)).length ?? 0;
  const acsWarns = acsFindings?.filter((f) => isWarnFinding(f.kind)).length ?? 0;

  // AgentCard summary counts.
  const okCount = cardFindings?.filter((f) => f.kind === 'declared_ok').length ?? 0;
  const total = cardFindings?.length ?? 0;

  return (
    <div className="validate-panel">
      {/* Target toggle: AgentCard (live manifests) vs ACS manifest (local). */}
      <div className="validate-target">
        <button
          className={`vt-btn ${target === 'agentcard' ? 'active' : ''}`}
          onClick={() => switchTarget('agentcard')}
        >
          AgentCard
        </button>
        <button className={`vt-btn ${isAcs ? 'active' : ''}`} onClick={() => switchTarget('acs')}>
          ACS manifest
        </button>
      </div>

      <p className="validate-blurb">
        {isAcs ? (
          <>
            Validate an <strong>Agent Control Specification</strong> manifest entirely in your
            browser — the same structural and semantic checks <code>a2a-testbed acs validate</code>{' '}
            runs in Python, no backend.
          </>
        ) : (
          <>
            Validate an <strong>AgentCard</strong> and every declared extension against its
            published JSON Schema manifest. Fetches live manifests; runs in your browser.
          </>
        )}
      </p>

      <div className="validate-controls">
        <button className="btn primary" onClick={onValidate} disabled={busy}>
          {validateLabel}
        </button>
        <button className="btn" onClick={onLoadSample} disabled={busy}>
          Load sample
        </button>
        <button className="btn" onClick={onClearSaved} disabled={busy}>
          Clear saved
        </button>
        {savedAt && (
          <span
            className="saved-hint"
            title="Stored in your browser via localStorage; nothing leaves your machine."
          >
            ✓ saved locally
          </span>
        )}
      </div>

      <textarea
        className="card-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        placeholder={isAcs ? 'Paste an ACS manifest (YAML) here…' : 'Paste an AgentCard JSON here…'}
        rows={isAcs ? 16 : 10}
      />

      {error && (
        <div className="validate-error">
          <strong>{isAcs ? 'Parse error:' : 'JSON parse error:'}</strong> {error}
        </div>
      )}

      {/* ACS findings */}
      {isAcs && acsFindings && (
        <div className="findings">
          <div className="findings-summary">
            {acsOk ? (
              <span className="finding-ok-text">Valid</span>
            ) : (
              <span className="finding-fail-text">Invalid</span>
            )}{' '}
            · {acsErrors} error{acsErrors === 1 ? '' : 's'} · {acsWarns} warning
            {acsWarns === 1 ? '' : 's'}
          </div>
          {acsFindings.map((f, i) => (
            <div key={i} className={`finding ${acsKindClass(f.kind)}`}>
              <div className="finding-head">
                <span className="finding-kind">{f.kind}</span>
                {f.locus && <span className="finding-manifest">{f.locus}</span>}
              </div>
              <div className="finding-detail">{f.detail}</div>
              {f.errors && f.errors.length > 0 && (
                <ul className="finding-errors">
                  {f.errors.map((e, j) => (
                    <li key={j}>
                      <code>{e}</code>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {/* AgentCard findings */}
      {!isAcs && cardFindings && (
        <div className="findings">
          <div className="findings-summary">
            {okCount}/{total} extensions validated
          </div>
          {cardFindings.map((f, i) => (
            <div key={i} className={`finding ${cardKindClass[f.kind]}`}>
              <div className="finding-head">
                <span className="finding-kind">{cardKindLabel[f.kind]}</span>
                {f.manifestName && (
                  <span className="finding-manifest">
                    {f.manifestName} v{f.manifestVersion}
                  </span>
                )}
              </div>
              <code className="finding-uri">{f.uri}</code>
              <div className="finding-detail">{f.detail}</div>
              {f.errors && f.errors.length > 0 && (
                <ul className="finding-errors">
                  {f.errors.map((e, j) => (
                    <li key={j}>
                      <code>{e.instancePath || '<root>'}</code>: {e.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
