import { useCallback, useEffect, useState } from 'react';
import { validateAgentCard, type Finding } from './validator';

// localStorage key for persisting the validator's textarea content
// across reloads. Pure browser-side; no backend involvement.
const SAVED_CARD_KEY = 'a2a-testbed.playground.validator.card_v1';

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
          document_uri:
            'https://example.com/.well-known/usage-policy.json',
          document_hash: 'sha256:' + 'a'.repeat(64),
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
          belief_update_endpoint:
            'https://example.com/phala/belief-updates',
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
          behavioral_fingerprint: 'sha256:' + '0'.repeat(64),
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

const kindLabel: Record<Finding['kind'], string> = {
  declared_ok: 'declared_ok',
  declared_invalid: 'declared_invalid',
  manifest_unreachable: 'manifest_unreachable',
  manifest_malformed: 'manifest_malformed',
  no_payload: 'no_payload',
};

const kindClass: Record<Finding['kind'], string> = {
  declared_ok: 'finding-ok',
  declared_invalid: 'finding-fail',
  manifest_unreachable: 'finding-warn',
  manifest_malformed: 'finding-warn',
  no_payload: 'finding-warn',
};

function loadSavedCard(): string {
  try {
    const saved = localStorage.getItem(SAVED_CARD_KEY);
    return saved ?? JSON.stringify(SAMPLE_CARD, null, 2);
  } catch {
    // localStorage can throw in private browsing or when disabled.
    return JSON.stringify(SAMPLE_CARD, null, 2);
  }
}

export function ValidatePanel() {
  const [text, setText] = useState<string>(loadSavedCard);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Debounced persist: write the textarea contents to localStorage
  // half a second after the user stops typing. Keeps the keystroke
  // path fast and avoids excessive writes.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      try {
        localStorage.setItem(SAVED_CARD_KEY, text);
        setSavedAt(Date.now());
      } catch {
        // ignore write failures (quota, private mode, etc.)
      }
    }, 500);
    return () => window.clearTimeout(handle);
  }, [text]);

  const onValidate = useCallback(async () => {
    setError(null);
    setBusy(true);
    setFindings(null);
    try {
      const card = JSON.parse(text);
      const result = await validateAgentCard(card);
      setFindings(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [text]);

  const onLoadSample = useCallback(() => {
    setText(JSON.stringify(SAMPLE_CARD, null, 2));
    setFindings(null);
    setError(null);
  }, []);

  const onClearSaved = useCallback(() => {
    try {
      localStorage.removeItem(SAVED_CARD_KEY);
    } catch {
      /* ignore */
    }
    setText(JSON.stringify(SAMPLE_CARD, null, 2));
    setFindings(null);
    setError(null);
    setSavedAt(null);
  }, []);

  const okCount = findings?.filter((f) => f.kind === 'declared_ok').length ?? 0;
  const total = findings?.length ?? 0;

  return (
    <div className="validate-panel">
      <div className="validate-controls">
        <button
          className="btn primary"
          onClick={onValidate}
          disabled={busy}
        >
          {busy ? 'Validating…' : 'Validate against live manifests'}
        </button>
        <button className="btn" onClick={onLoadSample} disabled={busy}>
          Load sample
        </button>
        <button className="btn" onClick={onClearSaved} disabled={busy}>
          Clear saved
        </button>
        {savedAt && (
          <span className="saved-hint" title="Stored in your browser via localStorage; nothing leaves your machine.">
            ✓ saved locally
          </span>
        )}
      </div>

      <textarea
        className="card-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        placeholder="Paste an AgentCard JSON here…"
        rows={10}
      />

      {error && (
        <div className="validate-error">
          <strong>JSON parse error:</strong> {error}
        </div>
      )}

      {findings && (
        <div className="findings">
          <div className="findings-summary">
            {okCount}/{total} extensions validated
          </div>
          {findings.map((f, i) => (
            <div key={i} className={`finding ${kindClass[f.kind]}`}>
              <div className="finding-head">
                <span className="finding-kind">{kindLabel[f.kind]}</span>
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
