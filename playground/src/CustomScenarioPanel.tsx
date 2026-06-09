import { useCallback, useEffect, useRef, useState } from 'react';
import { type LoadedScenario, parseScenarioYaml, ScenarioLoadError } from './scenarioLoader';

const SAVED_YAML_KEY = 'a2a-testbed.playground.custom_scenario_yaml';

const SAMPLE_YAML = `# Paste your CLI scenario YAML here.
# The same YAML works in both the CLI ('a2a-testbed run') and this
# playground; the browser ignores execution-only fields (paths,
# runtimes, reports) and visualizes the message graph.

name: "Demo: alice ↔ bob with an observer"
description: |
  Smallest possible 3-agent scenario. Replace with your own.

agents:
  - id: alice
    role: principal
  - id: bob
    role: service_provider
  - id: watcher
    role: observer

flow:
  - from: alice
    to: bob
    action: ping
    message: "ping: hello"
  - from: bob
    to: alice
    action: pong
    message: "pong: hi back"
`;

interface Props {
  open: boolean;
  onClose: () => void;
  onLoad: (scenario: LoadedScenario, sourceText: string) => void;
}

export function CustomScenarioPanel({ open, onClose, onLoad }: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [text, setText] = useState<string>(() => {
    try {
      return localStorage.getItem(SAVED_YAML_KEY) ?? SAMPLE_YAML;
    } catch {
      return SAMPLE_YAML;
    }
  });
  const [error, setError] = useState<string | null>(null);

  // Persist textarea content like the validator does.
  useEffect(() => {
    if (!open) return;
    const handle = window.setTimeout(() => {
      try {
        localStorage.setItem(SAVED_YAML_KEY, text);
      } catch {
        /* ignore */
      }
    }, 500);
    return () => window.clearTimeout(handle);
  }, [text, open]);

  // Close on ESC.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const onFile = useCallback(async (file: File) => {
    try {
      const t = await file.text();
      setText(t);
      setError(null);
    } catch (err) {
      setError(`Could not read file: ${(err as Error).message}`);
    }
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      const file = e.dataTransfer.files?.[0];
      if (file) onFile(file);
    },
    [onFile],
  );

  const onDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const [info, setInfo] = useState<string | null>(null);

  const onLoadClick = useCallback(() => {
    setError(null);
    setInfo(null);
    try {
      const scenario = parseScenarioYaml(text);

      const notes: string[] = [];
      const skipped = scenario.skippedNonMessageSteps;
      if (skipped > 0) {
        // Build a small breakdown like "1 observe, 2 advance_time".
        const breakdown = Object.entries(scenario.skippedKinds)
          .map(([kind, count]) => `${count} ${kind}`)
          .join(', ');
        notes.push(
          `${skipped} non-message step${
            skipped === 1 ? '' : 's'
          } skipped (${breakdown}). The browser visualizes wire ` +
            `traffic only — clock advances and observer ticks have ` +
            `no edge to draw.`,
        );
      }
      if (scenario.cardsTotal > 0 && scenario.cardsResolved < scenario.cardsTotal) {
        const missing = scenario.cardsTotal - scenario.cardsResolved;
        notes.push(
          `${missing} agent${
            missing === 1 ? '' : 's'
          } show a "?" badge — click it on the canvas to upload that agent's card JSON.`,
        );
      }

      if (notes.length > 0) {
        setInfo(notes.join(' '));
        window.setTimeout(() => {
          onLoad(scenario, text);
          onClose();
          setInfo(null);
        }, 2400);
        return;
      }

      onLoad(scenario, text);
      onClose();
    } catch (err) {
      if (err instanceof ScenarioLoadError) setError(err.message);
      else setError(`Unexpected error: ${(err as Error).message}`);
    }
  }, [text, onLoad, onClose]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="custom-scenario-title"
      >
        <div className="modal-head">
          <h2 id="custom-scenario-title">Load custom scenario</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <p className="modal-lead">
          Paste a YAML scenario, or drop / pick a <code>.yaml</code> file. The same format works in
          the CLI (<code>a2a-testbed run</code>) and the browser. Execution-only fields like agent
          runtimes, card paths, and reports are ignored — the canvas just visualizes the message
          graph.
        </p>

        <div
          className="modal-drop"
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragEnter={onDragOver}
        >
          <textarea
            className="modal-textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            placeholder="Paste YAML here, or drop a .yaml file…"
            rows={18}
          />
          <div className="modal-drop-hint">
            Drop a <code>.yaml</code> file anywhere on this textarea to load it.
          </div>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".yaml,.yml,text/yaml"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
        />

        {error && (
          <div className="modal-error">
            <strong>Could not load scenario:</strong> {error}
          </div>
        )}

        {info && (
          <div className="modal-info">
            <strong>Heads up:</strong> {info}
          </div>
        )}

        <div className="modal-actions">
          <button className="btn" onClick={() => fileInputRef.current?.click()}>
            Pick .yaml file
          </button>
          <button
            className="btn"
            onClick={() => {
              setText(SAMPLE_YAML);
              setError(null);
            }}
          >
            Reset to sample
          </button>
          <span className="modal-spacer" />
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" onClick={onLoadClick}>
            Load scenario
          </button>
        </div>
      </div>
    </div>
  );
}
