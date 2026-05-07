import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Position,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { agentCards, scenario, type ScenarioStep, type AgentCard } from './scenario';
import { AgentNode } from './AgentNode';
import { Inspector, type InspectorTarget, type StepRunResult } from './Inspector';
import { ValidatePanel } from './ValidatePanel';
import { HomePage } from './HomePage';
import { CloudflareAnalytics } from './CloudflareAnalytics';
import { CustomScenarioPanel } from './CustomScenarioPanel';
import {
  adaptSteps,
  layoutAgents,
  parseScenarioYaml,
  type LoadedScenario,
} from './scenarioLoader';
import {
  BUILTIN_SCENARIOS,
  findBuiltin,
  type BuiltinScenarioDef,
} from './builtins';
import { ALL_CONTRACTS } from './conformance/contracts';
import {
  CHUNK_SIZE,
  runConformanceChunk,
  summarize,
} from './conformance/runner';
import type { ContractResult } from './conformance/types';
import './App.css';

export type Mode = 'home' | 'scenario' | 'validate';

const nodeTypes = { agent: AgentNode };

// localStorage key for persisting a custom-loaded scenario across
// reloads. Serializes the full ActiveScenario shape (agents +
// uploaded cards + steps + positions). Bundled scenarios are never
// persisted — fresh page = bundled welcome experience.
const SAVED_ACTIVE_KEY = 'a2a-testbed.playground.active_scenario_v1';

// ---------------------------------------------------------------------------
// Active scenario abstraction
//
// The canvas can render either the bundled three-party scenario or any
// CLI-format YAML the user pastes via the "Load custom" dialog. To avoid
// special-casing throughout the runtime, we normalize both into a single
// `ActiveScenario` shape.
// ---------------------------------------------------------------------------

interface ActiveAgent {
  id: string;
  label: string;
  role: string;
  card: AgentCard | null;
  /** Path-string preserved when `card:` was a CLI-style file path
   *  the browser couldn't follow. Surfaced in the inspector + the
   *  "?" badge tooltip so the user knows which file to upload. */
  cardHint?: string;
  /** YAML `runtime:` value, preserved verbatim. */
  runtime?: string;
  /** YAML `url:` value. Required for `runtime: external` to actually
   *  call out — when both are set, runScenario POSTs A2A JSON-RPC to
   *  this URL instead of running the animation-only path. */
  url?: string;
  position: { x: number; y: number };
}

interface ActiveScenario {
  name: string;
  description?: string;
  agents: ActiveAgent[];
  steps: ScenarioStep[];
  /** Whether this scenario originated from a user upload (vs. a
   *  built-in). Custom scenarios always render observers and skip
   *  the "Add Observer" toggle. */
  isCustom: boolean;
  /** Built-in id when this scenario was picked from the dropdown.
   *  Lets the dropdown stay in sync after page reload, etc.
   *  null = bundled three-party (the historical default). */
  builtinId: string | null;
  /** Whether the scenario will make REAL HTTP calls when run.
   *  'external' = at least one agent is `runtime: external` with
   *  a `url:` and the playground will POST A2A JSON-RPC there.
   *  'simulated' = animation-only. Drives the live banner above
   *  the canvas. */
  runtimeKind: 'simulated' | 'external';
  /** Distinct external agent URLs surfaced in the banner so the
   *  user can see exactly which deployments the run will hit.
   *  Empty when runtimeKind === 'simulated'. */
  externalUrls: string[];
  /** Map of cardId -> AgentCard for the inspector lookup. */
  agentCardLookup: Record<string, AgentCard>;
}

/** Compute runtimeKind + externalUrls from an agent list. */
function deriveRuntimeKind(agents: ActiveAgent[]): {
  runtimeKind: 'simulated' | 'external';
  externalUrls: string[];
} {
  const urls = Array.from(
    new Set(
      agents
        .filter((a) => a.runtime === 'external' && typeof a.url === 'string')
        .map((a) => a.url as string)
    )
  );
  return {
    runtimeKind: urls.length > 0 ? 'external' : 'simulated',
    externalUrls: urls,
  };
}

// Sentinel used in the dropdown for "the bundled three-party demo".
// It's not in BUILTIN_SCENARIOS because that array is reserved for
// data-driven scenarios bundled from `examples/`; the three-party
// flow is hardcoded in scenario.ts for educational simplicity.
const BUNDLED_DEFAULT_ID = '__bundled__';
// Sentinel for "user-uploaded custom YAML, not a built-in".
const CUSTOM_ID = '__custom__';

const BUNDLED_AGENT_META: Array<{
  id: string;
  label: string;
  role: string;
  position: { x: number; y: number };
}> = [
  { id: 'alice', label: 'Alice', role: 'principal',         position: { x:  60, y: 220 } },
  { id: 'bob',   label: 'Bob',   role: 'guardian',          position: { x: 380, y:  60 } },
  { id: 'carol', label: 'Carol', role: 'service_provider',  position: { x: 720, y: 220 } },
  { id: 'observer', label: 'Observer', role: 'integrity',   position: { x: 380, y: 420 } },
];

function buildBundledActive(): ActiveScenario {
  const agents: ActiveAgent[] = BUNDLED_AGENT_META.map((m) => ({
    id: m.id,
    label: m.label,
    role: m.role,
    card: agentCards[m.id] ?? null,
    position: m.position,
  }));
  return {
    name: scenario.name,
    description: scenario.description,
    agents,
    steps: scenario.steps,
    isCustom: false,
    builtinId: null,
    runtimeKind: 'simulated',
    externalUrls: [],
    agentCardLookup: agentCards,
  };
}

function loadSavedActive(): ActiveScenario | null {
  try {
    const raw = localStorage.getItem(SAVED_ACTIVE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ActiveScenario>;
    if (!parsed || !Array.isArray(parsed.agents) || !Array.isArray(parsed.steps)) {
      return null;
    }
    // Trust the persisted shape — it was written by the same code,
    // and any mismatch would be caught by the type-erased runtime
    // checks downstream (xyflow ignores malformed nodes).
    const restoredAgents = parsed.agents as ActiveAgent[];
    const derived = deriveRuntimeKind(restoredAgents);
    return {
      name: parsed.name ?? 'Custom scenario',
      description: parsed.description,
      agents: restoredAgents,
      steps: parsed.steps as ScenarioStep[],
      isCustom: parsed.isCustom ?? true,
      builtinId: parsed.builtinId ?? null,
      runtimeKind: parsed.runtimeKind ?? derived.runtimeKind,
      externalUrls: parsed.externalUrls ?? derived.externalUrls,
      agentCardLookup: parsed.agentCardLookup ?? {},
    };
  } catch {
    return null;
  }
}

function buildCustomActive(loaded: LoadedScenario): ActiveScenario {
  const positions = layoutAgents(loaded.agents.length);
  const agents: ActiveAgent[] = loaded.agents.map((a, i) => ({
    id: a.id,
    label: a.card?.name ?? a.id,
    role: a.role ?? 'agent',
    card: a.card,
    cardHint: a.cardHint,
    runtime: a.runtime,
    url: a.url,
    position: positions[i],
  }));
  const lookup: Record<string, AgentCard> = {};
  for (const a of agents) {
    if (a.card) lookup[a.id] = a.card;
  }
  const { runtimeKind, externalUrls } = deriveRuntimeKind(agents);
  return {
    name: loaded.name,
    description: loaded.description,
    agents,
    steps: adaptSteps(loaded),
    isCustom: true,
    builtinId: null,
    runtimeKind,
    externalUrls,
    agentCardLookup: lookup,
  };
}

/** Parse a built-in scenario (YAML + bundled cards) into an
 *  ActiveScenario. Same code path as a user upload, just with the
 *  cards pre-resolved from the registry instead of the upload picker. */
function buildBuiltinActive(def: BuiltinScenarioDef): ActiveScenario {
  const cardLookup: Record<string, AgentCard> = {};
  for (const [filename, jsonText] of Object.entries(def.cards)) {
    try {
      cardLookup[filename] = JSON.parse(jsonText) as AgentCard;
    } catch {
      // A malformed bundled card is a build-time mistake; skip it
      // and let the per-agent "?" badge surface the gap.
    }
  }
  const loaded = parseScenarioYaml(def.yaml, cardLookup);
  // Reuse the custom factory for layout + step adapt, then mark it
  // as a built-in (not "isCustom") so the UI doesn't offer "Discard
  // custom" / "Cards needed" prompts that don't apply.
  const built = buildCustomActive(loaded);
  return {
    ...built,
    isCustom: false,
    builtinId: def.id,
  };
}

// ---------------------------------------------------------------------------
// External execution: real HTTP POST against a deployed agent.
// ---------------------------------------------------------------------------

/** Result of executing one external step's HTTP call + expectations. */
interface ExternalStepOutcome {
  ok: boolean;
  status: number;
  /** First ~400 chars of the response body, for inspector display. */
  bodySnippet: string;
  /** One entry per expect-block check. */
  checks: StepRunResult['checks'];
  /** Error string when the fetch itself failed (network/CORS/etc). */
  error?: string;
}

/**
 * POST an A2A JSON-RPC `message/send` to the agent's URL and
 * evaluate `expect.response_status` + `expect.response_contains`
 * against the raw response body.
 *
 * Mirrors the CLI's checks (a2a_testbed/runtime/scenario.py): the
 * matchers are literal substrings against the raw HTTP body, so
 * a YAML like `response_contains: '\"answer\": 84'` works
 * identically here and in the CLI.
 */
async function executeExternalStep(
  agentUrl: string,
  step: ScenarioStep,
  jsonRpcId: number,
): Promise<ExternalStepOutcome> {
  // The user's authored `message:` string is preserved by adaptSteps
  // under message.content. Fall back to the action label if the
  // scenario didn't supply text (won't happen for the math demo).
  const userText =
    typeof (step.message as { content?: unknown } | undefined)?.content ===
    'string'
      ? ((step.message as { content: string }).content)
      : step.action;

  const endpoint = agentUrl.replace(/\/$/, '') + '/a2a/v1/';
  const requestBody = {
    jsonrpc: '2.0',
    id: jsonRpcId,
    method: 'message/send',
    params: {
      message: {
        parts: [{ kind: 'text', text: userText }],
      },
    },
  };

  let res: Response;
  try {
    res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(requestBody),
    });
  } catch (err) {
    return {
      ok: false,
      status: 0,
      bodySnippet: '',
      checks: [
        {
          name: 'network',
          ok: false,
          detail: `fetch failed: ${(err as Error).message}`,
        },
      ],
      error: (err as Error).message,
    };
  }

  const bodyText = await res.text();
  const expect = (step.expect ?? {}) as Record<string, unknown>;
  const checks: StepRunResult['checks'] = [];

  // response_status: '2xx' / '3xx' / '4xx' / '5xx' OR an exact code.
  const expectedStatus = expect.response_status;
  if (typeof expectedStatus === 'string') {
    const match = /^([1-5])xx$/i.exec(expectedStatus);
    let ok: boolean;
    if (match) {
      ok = Math.floor(res.status / 100) === Number(match[1]);
    } else {
      ok = String(res.status) === expectedStatus;
    }
    checks.push({
      name: 'response_status',
      ok,
      detail: `expected ${expectedStatus}, got ${res.status}`,
    });
  } else if (typeof expectedStatus === 'number') {
    const ok = res.status === expectedStatus;
    checks.push({
      name: 'response_status',
      ok,
      detail: `expected ${expectedStatus}, got ${res.status}`,
    });
  }

  // response_contains: literal substring against the raw body.
  const expectedContains = expect.response_contains;
  if (typeof expectedContains === 'string') {
    const ok = bodyText.includes(expectedContains);
    checks.push({
      name: 'response_contains',
      ok,
      detail: ok
        ? `body contains '${expectedContains}'`
        : `body did not contain '${expectedContains}'`,
    });
  }

  const allOk = checks.every((c) => c.ok);
  return {
    ok: allOk,
    status: res.status,
    bodySnippet: bodyText.slice(0, 400),
    checks,
  };
}

function makeNodesFor(
  active: ActiveScenario,
  includeObserver: boolean,
  onLoadCard: (cardId: string) => void
): Node[] {
  const visible = active.agents.filter(
    (a) => includeObserver || a.role !== 'observer'
  );
  return visible.map((a) => ({
    id: a.id,
    type: 'agent',
    position: a.position,
    data: {
      label: a.label,
      role: a.role,
      cardId: a.id,
      state: 'idle',
      hasCard: a.card !== null,
      cardHint: a.cardHint,
      onLoadCard,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  }));
}

function formatVirtualTimeDelta(seconds: number): string {
  if (seconds <= 0) return '0 seconds';
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'}`;
  if (seconds < 3600) {
    const m = Math.round(seconds / 60);
    return `${m} minute${m === 1 ? '' : 's'}`;
  }
  if (seconds < 86400) {
    const h = Math.round(seconds / 3600);
    return `${h} hour${h === 1 ? '' : 's'}`;
  }
  const d = Math.round(seconds / 86400);
  return `${d} day${d === 1 ? '' : 's'}`;
}

function makeEdgesFor(active: ActiveScenario, includeObserver: boolean): Edge[] {
  const messageEdges = active.steps
    .map((step, idx) => ({ step, idx }))
    // advance_time steps render as a banner overlay (handled in the
    // run loop), not as a from→to edge. Filter them out of the
    // edge list so the canvas doesn't try to draw a phantom curve.
    .filter(({ step }) => step.kind !== 'advance_time')
    .filter(({ step }) => includeObserver || !isObserverStep(step))
    .map(({ step, idx }) => ({
      id: `e${idx}-${step.from}-${step.to}`,
      source: step.from,
      target: step.to,
      sourceHandle: 'right',
      targetHandle: 'left',
      label: step.action,
      labelStyle: { fontSize: 11, fontWeight: 600, fill: '#475569' },
      labelBgStyle: { fill: '#f8fafc', fillOpacity: 0.95 },
      labelBgPadding: [4, 6] as [number, number],
      labelBgBorderRadius: 4,
      type: 'default',
      style: { stroke: '#cbd5e1', strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8' },
      data: { stepIndex: idx, stepStatus: 'pending' },
    }));

  // Tap edges: passive observer-role agents (no message edges in
  // the flow) get dashed taps to every participating agent.
  if (!includeObserver) return messageEdges;

  const observers = active.agents.filter((a) => a.role === 'observer');
  const passiveObservers = observers.filter(
    (o) => !active.steps.some((s) => s.from === o.id || s.to === o.id)
  );
  if (passiveObservers.length === 0) return messageEdges;

  const participants = new Set<string>();
  for (const s of active.steps) {
    participants.add(s.from);
    participants.add(s.to);
  }
  const positionById: Record<string, { x: number; y: number }> = {};
  for (const a of active.agents) positionById[a.id] = a.position;

  const tapEdges: Edge[] = [];
  for (const observer of passiveObservers) {
    const obsPos = positionById[observer.id];
    if (!obsPos) continue;
    for (const pid of participants) {
      if (pid === observer.id) continue;
      const pPos = positionById[pid];
      if (!pPos) continue;

      // Pick handles so the tap curve flows toward the observer
      // without overlapping with other taps. If the observer is
      // ABOVE the participant, source leaves from the participant's
      // top, enters the observer's bottom; if BELOW, the opposite.
      const observerIsAbove = obsPos.y < pPos.y;
      const sourceHandle = observerIsAbove ? 'top-out' : 'bottom-out';
      const targetHandle = observerIsAbove ? 'bottom-in' : 'top-in';

      tapEdges.push({
        id: `tap-${pid}-${observer.id}`,
        source: pid,
        target: observer.id,
        sourceHandle,
        targetHandle,
        type: 'default',
        label: 'tap',
        labelStyle: {
          fontSize: 9.5,
          fontWeight: 600,
          fill: '#65a30d',
          letterSpacing: 0.4,
          textTransform: 'uppercase' as const,
        },
        labelBgStyle: { fill: '#f7fee7', fillOpacity: 0.95 },
        labelBgPadding: [2, 5] as [number, number],
        labelBgBorderRadius: 3,
        // No arrowhead — taps are non-directional observations.
        style: {
          stroke: '#a3e635',
          strokeWidth: 1.5,
          strokeDasharray: '4 5',
          opacity: 0.6,
        },
        animated: false,
        data: { stepIndex: -1, stepStatus: 'pending', isTap: true },
      });
    }
  }

  return [...messageEdges, ...tapEdges];
}

type Phase = 'idle' | 'running' | 'done';
type EdgeStatus = 'pending' | 'firing' | 'ok' | 'fail';

const colorByStatus: Record<EdgeStatus, string> = {
  pending: '#cbd5e1',
  firing: '#f59e0b',
  ok: '#22c55e',
  fail: '#ef4444',
};

// Steps that involve the observer agent. When "Add observer" is off,
// these are filtered out and the observer node is hidden — so first-time
// users see the 3-agent base flow without extra cognitive load.
function isObserverStep(step: ScenarioStep): boolean {
  return step.from === 'observer' || step.to === 'observer';
}

export default function App() {
  const [mode, setMode] = useState<Mode>('home');
  const [includeObserver, setIncludeObserver] = useState(false);
  // Initialize from localStorage if a custom scenario was saved last
  // session, otherwise the bundled demo.
  const [activeScenario, setActiveScenario] = useState<ActiveScenario>(
    () => loadSavedActive() ?? buildBundledActive()
  );
  // Mirror activeScenario into a ref so stable callbacks (e.g.
  // onLoadCardForAgent) can read the latest value without depending
  // on it. Avoids rebuild-useEffect churn.
  const activeScenarioRef = useRef(activeScenario);
  useEffect(() => {
    activeScenarioRef.current = activeScenario;
  }, [activeScenario]);
  const [panelOpen, setPanelOpen] = useState(false);
  // Initial nodes/edges built from whichever scenario activeScenario
  // ended up holding (custom from localStorage, or bundled). The
  // rebuild useEffect immediately re-derives these on first render
  // anyway; this just avoids a flash of empty canvas.
  const [nodes, setNodes] = useState<Node[]>(() =>
    makeNodesFor(loadSavedActive() ?? buildBundledActive(), false, () => {})
  );
  const [edges, setEdges] = useState<Edge[]>(() =>
    makeEdgesFor(loadSavedActive() ?? buildBundledActive(), false)
  );

  // Whether observer-role agents/steps are visible.
  //
  // - In the BUNDLED scenario: opt-in via the "Add Observer" toggle,
  //   so first-time users see the simple 3-agent flow.
  // - In any CUSTOM scenario: ALWAYS visible. The user explicitly
  //   authored the observer in their YAML; hiding it would be
  //   condescending. The toggle is also hidden in custom mode.
  const showObserver = activeScenario.isCustom || includeObserver;
  const [phase, setPhase] = useState<Phase>('idle');
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [completed, setCompleted] = useState<Set<number>>(new Set());
  const [target, setTarget] = useState<InspectorTarget | null>(null);
  // Per-step results from real HTTP execution. Populated only for
  // steps whose target agent has `runtime: external` + `url:`.
  // Animation-only steps stay absent from this map and are colored
  // by `step.outcome` as before.
  const [stepResults, setStepResults] = useState<Map<number, StepRunResult>>(
    () => new Map()
  );
  // Browser-side A2A 1.0 conformance results, keyed by external
  // agent URL. Populated after `runScenario` finishes for any
  // scenario that includes a `runtime: external` agent. Same
  // contract suite the CLI's `conformance` command runs.
  const [conformanceResults, setConformanceResults] = useState<
    Map<string, ContractResult[]>
  >(() => new Map());
  const [conformanceRunning, setConformanceRunning] = useState(false);
  // Banner shown while an advance_time step is active. Carries the
  // virtual-clock delta in seconds so the UI can format it as
  // "+1 hour" / "+1 day" / etc. Cleared between steps.
  const [advanceTimeBanner, setAdvanceTimeBanner] = useState<{
    stepIndex: number;
    seconds: number;
  } | null>(null);
  // Per-URL index of the next contract to run. Drives the chunked
  // "Run next batch" flow — sweeping all 58 in one burst can trip
  // an external agent's per-IP rate limit, so the user paces it.
  const [conformanceProgress, setConformanceProgress] = useState<
    Map<string, number>
  >(() => new Map());
  // Accordion: panel starts expanded so users see the body's intent
  // copy ("Click Run scenario to drive…") without an extra click.
  // Toggling collapses to a one-line header so the sidebar reclaims
  // space when the user wants to focus on the canvas/inspector.
  const [conformanceExpanded, setConformanceExpanded] = useState(true);

  // Per-agent card loader. When an agent in a custom scenario has no
  // card yet (only a path-string hint), the AgentNode shows a "?"
  // badge / pill; clicking it triggers this. We open a transient
  // file picker, validate the picked file, and update the active
  // scenario so that one agent gets its card filled in (or replaced).
  //
  // Validation has two layers:
  //   (1) Hard: parses as JSON and looks like an AgentCard
  //       (must have a `name` field — A2A 1.0's only universally
  //       required AgentCard field).
  //   (2) Soft: filename matches the basename the YAML expected.
  //       If it doesn't, we confirm with the user before accepting —
  //       people legitimately rename files.
  //
  // We use a ref to look up agent metadata so this callback stays
  // stable (no activeScenario in deps), avoiding rebuild-useEffect
  // churn.
  const onLoadCardForAgent = useCallback((cardId: string) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;

      let parsed: AgentCard;
      try {
        const text = await file.text();
        parsed = JSON.parse(text) as AgentCard;
      } catch (err) {
        window.alert(
          `Could not load "${file.name}":\n${(err as Error).message}\n\n` +
            'The file must be valid JSON.'
        );
        return;
      }

      // (1) Hard content check.
      if (
        !parsed ||
        typeof parsed !== 'object' ||
        typeof (parsed as { name?: unknown }).name !== 'string'
      ) {
        window.alert(
          `"${file.name}" doesn't look like an A2A AgentCard.\n\n` +
            'Expected a JSON object with at least a "name" string field. ' +
            'Make sure you picked the right file.'
        );
        return;
      }

      // (2) Soft filename check — uses a ref so we can read the
      // current scenario without making this callback unstable.
      const agent = activeScenarioRef.current.agents.find((x) => x.id === cardId);
      const expectedName = agent?.cardHint?.split(/[\\/]/).pop();
      if (expectedName && file.name !== expectedName) {
        const ok = window.confirm(
          `Filename mismatch.\n\n` +
            `The scenario YAML expected:  ${expectedName}\n` +
            `You picked:  ${file.name}\n\n` +
            `If you renamed the file, click OK to use it anyway. ` +
            `Otherwise click Cancel and pick the matching file.`
        );
        if (!ok) return;
      }

      setActiveScenario((prev) => ({
        ...prev,
        agents: prev.agents.map((a) =>
          a.id === cardId ? { ...a, card: parsed, cardHint: a.cardHint } : a
        ),
        agentCardLookup: { ...prev.agentCardLookup, [cardId]: parsed },
      }));
    };
    input.click();
  }, []);

  // Document title reflects the active mode so browser tabs / history
  // entries are scannable instead of all reading "a2a-testbed".
  useEffect(() => {
    const suffix =
      mode === 'home'
        ? 'Home'
        : mode === 'scenario'
        ? 'Scenario'
        : 'Validator';
    document.title = `a2a-testbed | ${suffix}`;
  }, [mode]);

  // Re-build the canvas when observer visibility flips OR the active
  // scenario swaps (custom load / reset to default / per-agent card
  // upload). Rebuilding (not just filtering in place) keeps xyflow's
  // layout, fit-view, and edge state clean.
  useEffect(() => {
    setNodes(makeNodesFor(activeScenario, showObserver, onLoadCardForAgent));
    setEdges(makeEdgesFor(activeScenario, showObserver));
    setPhase('idle');
    setActiveStep(null);
    setCompleted(new Set());
    setTarget(null);
    setStepResults(new Map());
    setConformanceResults(new Map());
  }, [showObserver, activeScenario, onLoadCardForAgent]);

  // Persist the active scenario to localStorage whenever it changes
  // (only for custom scenarios; bundled is the default and doesn't
  // need persisting). This survives page reloads, browser restarts,
  // and tab switches — the user gets back exactly what they uploaded.
  useEffect(() => {
    try {
      if (activeScenario.isCustom) {
        localStorage.setItem(
          SAVED_ACTIVE_KEY,
          JSON.stringify({
            name: activeScenario.name,
            description: activeScenario.description,
            agents: activeScenario.agents,
            steps: activeScenario.steps,
            agentCardLookup: activeScenario.agentCardLookup,
          })
        );
      } else {
        localStorage.removeItem(SAVED_ACTIVE_KEY);
      }
    } catch {
      /* localStorage may be disabled (private mode, quota); ignore */
    }
  }, [activeScenario]);

  // Recompute edge styling whenever step status changes.
  useEffect(() => {
    setEdges((prev) =>
      prev.map((edge) => {
        const data = edge.data as { stepIndex: number; isTap?: boolean };

        // Tap edges (passive observer connections) animate when the
        // observed agent is firing — visualizes "the observer is
        // recording this step right now" without changing the
        // underlying message-edge animation.
        if (data.isTap) {
          const firingStep =
            activeStep !== null ? activeScenario.steps[activeStep] : null;
          const isFiringSource =
            !!firingStep &&
            (firingStep.from === edge.source ||
              firingStep.to === edge.source);
          return {
            ...edge,
            animated: isFiringSource,
            style: {
              stroke: isFiringSource ? '#65a30d' : '#a3e635',
              strokeWidth: isFiringSource ? 2.25 : 1.5,
              strokeDasharray: '4 5',
              opacity: isFiringSource ? 0.95 : 0.6,
            },
          };
        }

        const idx = data.stepIndex;
        const isActive = idx === activeStep;
        const isDone = completed.has(idx);
        // Real-run outcome takes precedence over the static
        // `step.outcome`. Both are 'ok'/'fail' but stepResults is
        // populated by the executeExternalStep evaluator while
        // step.outcome is hand-authored on bundled steps.
        const runOutcome = stepResults.get(idx);
        const status: EdgeStatus = isActive
          ? 'firing'
          : isDone
          ? runOutcome
            ? runOutcome.ok
              ? 'ok'
              : 'fail'
            : activeScenario.steps[idx]?.outcome === 'fail'
            ? 'fail'
            : 'ok'
          : 'pending';

        return {
          ...edge,
          animated: status === 'firing',
          style: {
            stroke: colorByStatus[status],
            strokeWidth: status === 'firing' ? 3 : 2,
            strokeDasharray: status === 'firing' ? '6 4' : undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: colorByStatus[status],
          },
          data: { stepIndex: idx, stepStatus: status },
        };
      })
    );
  }, [activeStep, completed, activeScenario, stepResults]);

  // Highlight nodes participating in the active step.
  useEffect(() => {
    setNodes((prev) =>
      prev.map((node) => {
        let state: 'idle' | 'sending' | 'receiving' | 'done' = 'idle';
        if (activeStep !== null) {
          const step = activeScenario.steps[activeStep];
          // advance_time steps don't have a from/to, so no node
          // gets a sending/receiving highlight; they read as a
          // pause across the canvas, not a wire exchange.
          if (step && step.kind !== 'advance_time') {
            if (node.id === step.from) state = 'sending';
            else if (node.id === step.to) state = 'receiving';
          }
        }
        if (state === 'idle' && completed.size > 0) state = 'done';
        return { ...node, data: { ...node.data, state } };
      })
    );
  }, [activeStep, completed.size, activeScenario]);

  const runScenario = useCallback(async () => {
    setPhase('running');
    setCompleted(new Set());
    setStepResults(new Map());
    setTarget(null);

    // Build a quick lookup so each step can find its target's
    // runtime/url without scanning the agent list every iteration.
    const agentById = new Map<string, ActiveAgent>();
    for (const a of activeScenario.agents) agentById.set(a.id, a);

    for (let i = 0; i < activeScenario.steps.length; i++) {
      const step = activeScenario.steps[i];
      // Skip observer steps when the toggle is off — they're not
      // visible on the canvas in that mode.
      if (!showObserver && isObserverStep(step)) continue;

      setActiveStep(i);

      // advance_time steps: surface a banner with the virtual-clock
      // delta, hold for duration_ms, then move on. No HTTP, no
      // edge animation. The banner clears after the step completes.
      if (step.kind === 'advance_time') {
        setAdvanceTimeBanner({
          stepIndex: i,
          seconds: step.advance_seconds ?? 0,
        });
        await new Promise((r) => setTimeout(r, step.duration_ms));
        setAdvanceTimeBanner(null);
        setCompleted((s) => {
          const next = new Set(s);
          next.add(i);
          return next;
        });
        continue;
      }

      const target = agentById.get(step.to);
      const isExternal =
        target?.runtime === 'external' && typeof target.url === 'string';

      if (isExternal && target?.url) {
        // Real HTTP path. Run the request + minimum-duration timer
        // in parallel so a fast worker still gets a visible animation
        // beat (rather than the edge flashing for one frame).
        const [outcome] = await Promise.all([
          executeExternalStep(target.url, step, i + 1),
          new Promise<void>((r) => setTimeout(r, Math.max(step.duration_ms, 350))),
        ]);
        setStepResults((prev) => {
          const next = new Map(prev);
          next.set(i, {
            executedExternal: true,
            ok: outcome.ok,
            status: outcome.status,
            bodySnippet: outcome.bodySnippet,
            checks: outcome.checks,
            error: outcome.error,
          });
          return next;
        });
      } else {
        // Animation-only path (unchanged).
        await new Promise((r) => setTimeout(r, step.duration_ms));
      }

      setCompleted((s) => {
        const next = new Set(s);
        next.add(i);
        return next;
      });
    }
    setActiveStep(null);
    setPhase('done');
    // Conformance is now user-triggered (chunked, one batch at a
    // time) instead of auto-running here — bursting all 58 contracts
    // back-to-back can trip an external agent's per-IP rate limit.
  }, [showObserver, activeScenario]);

  /**
   * Run the next chunk of conformance contracts against every
   * external agent in parallel. The runner clears caches when
   * `startIndex === 0`, so calling this from a fresh state
   * effectively starts a new sweep; calling it again continues
   * from where the previous chunk left off.
   */
  const runNextConformanceBatch = useCallback(async () => {
    const urls = activeScenario.externalUrls;
    if (urls.length === 0 || conformanceRunning) return;
    setConformanceRunning(true);
    setConformanceExpanded(true);
    try {
      const updates = await Promise.all(
        urls.map(async (url) => {
          const startIndex = conformanceProgress.get(url) ?? 0;
          const chunk = await runConformanceChunk(url, startIndex, CHUNK_SIZE);
          return { url, startIndex, chunk };
        }),
      );
      setConformanceResults((prev) => {
        const next = new Map(prev);
        for (const { url, startIndex, chunk } of updates) {
          const existing = startIndex === 0 ? [] : next.get(url) ?? [];
          next.set(url, [...existing, ...chunk]);
        }
        return next;
      });
      setConformanceProgress((prev) => {
        const next = new Map(prev);
        for (const { url, startIndex, chunk } of updates) {
          next.set(url, startIndex + chunk.length);
        }
        return next;
      });
    } finally {
      setConformanceRunning(false);
    }
  }, [activeScenario, conformanceProgress, conformanceRunning]);

  /** Reset the chunked sweep so the next click starts at contract 0. */
  const resetConformance = useCallback(() => {
    setConformanceResults(new Map());
    setConformanceProgress(new Map());
  }, []);

  const reset = useCallback(() => {
    setPhase('idle');
    setActiveStep(null);
    setCompleted(new Set());
    setTarget(null);
  }, []);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    const cardId = (node.data as { cardId: string }).cardId;
    setTarget({ kind: 'agent', id: node.id, cardId });
  }, []);

  const onEdgeClick = useCallback((_: unknown, edge: Edge) => {
    const data = edge.data as { stepIndex: number; isTap?: boolean };
    // Tap edges aren't real steps — clicking them shouldn't open
    // a step inspector. Ignore.
    if (data.isTap) return;
    setTarget({ kind: 'step', index: data.stepIndex });
  }, []);

  const stepLabels = useMemo(
    () =>
      activeScenario.steps
        .map((s, i) => ({ s, i }))
        .filter(({ s }) => showObserver || !isObserverStep(s))
        .map(({ s, i }, displayIdx) => {
          const text =
            s.kind === 'advance_time'
              ? `${displayIdx + 1}. virtual time +${formatVirtualTimeDelta(
                  s.advance_seconds ?? 0,
                )}`
              : `${displayIdx + 1}. ${s.from} → ${s.to}: ${s.action}`;
          return {
            index: i,
            text,
            status: completed.has(i)
              ? 'done'
              : i === activeStep
              ? 'firing'
              : 'pending',
          };
        }),
    [activeStep, completed, showObserver, activeScenario]
  );

  const inspectorAgent =
    target?.kind === 'agent'
      ? activeScenario.agentCardLookup[target.cardId]
      : undefined;
  const inspectorAgentMeta =
    target?.kind === 'agent'
      ? (() => {
          const a = activeScenario.agents.find((x) => x.id === target.cardId);
          return a
            ? {
                id: a.id,
                label: a.label,
                role: a.role,
                cardHint: a.cardHint,
              }
            : undefined;
        })()
      : undefined;
  const inspectorStep: ScenarioStep | undefined =
    target?.kind === 'step' ? activeScenario.steps[target.index] : undefined;

  const onLoadCustom = useCallback((loaded: LoadedScenario) => {
    setActiveScenario(buildCustomActive(loaded));
  }, []);

  const onResetToDefault = useCallback(() => {
    setActiveScenario(buildBundledActive());
  }, []);

  const onSelectBuiltin = useCallback((id: string) => {
    if (id === BUNDLED_DEFAULT_ID) {
      setActiveScenario(buildBundledActive());
      return;
    }
    const def = findBuiltin(id);
    if (def) setActiveScenario(buildBuiltinActive(def));
  }, []);

  // What value the dropdown shows. Custom-uploaded scenarios show
  // a sentinel that's not selectable (read-only "Custom upload"
  // option) so the user can see where they are without losing the
  // ability to switch back to a built-in.
  const dropdownValue: string = activeScenario.isCustom
    ? CUSTOM_ID
    : activeScenario.builtinId ?? BUNDLED_DEFAULT_ID;

  return (
    <div className="layout">
      <CloudflareAnalytics />
      <CustomScenarioPanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        onLoad={onLoadCustom}
      />
      <header className="topbar">
        <div className="topbar-inner">
        <button
          className="brand-button"
          onClick={() => setMode('home')}
          aria-label="a2a-testbed home"
        >
          <img
            className="brand-icon"
            src="/a2a-logo/a2a-testbed-icon.svg"
            alt=""
            width="40"
            height="40"
          />
          <span className="brand-wordmark">
            <span>a</span>
            <span className="brand-grad">2</span>
            <span>a</span>
            <span className="brand-sep">-</span>
            <span>testbed</span>
          </span>
        </button>
        <nav className="mode-toggle">
          <button
            className={`mode-btn ${mode === 'home' ? 'active' : ''}`}
            onClick={() => setMode('home')}
          >
            Home
          </button>
          <button
            className={`mode-btn ${mode === 'scenario' ? 'active' : ''}`}
            onClick={() => setMode('scenario')}
          >
            Scenario
          </button>
          <button
            className={`mode-btn ${mode === 'validate' ? 'active' : ''}`}
            onClick={() => setMode('validate')}
          >
            Validator
          </button>
        </nav>
        <nav className="ext-links">
          <a href="https://a2a-protocol.org/" target="_blank" rel="noreferrer">
            A2A Spec ↗
          </a>
          <a href="https://modelcontextprotocol.io/" target="_blank" rel="noreferrer">
            MCP ↗
          </a>
          <a
            href="https://github.com/ravikiran438/a2a-testbed"
            target="_blank"
            rel="noreferrer"
          >
            GitHub ↗
          </a>
        </nav>
        {mode === 'scenario' && (
          <div className="actions">
            <select
              className="scenario-picker"
              value={dropdownValue}
              onChange={(e) => onSelectBuiltin(e.target.value)}
              disabled={phase === 'running'}
              title="Pick a built-in scenario, or load your own YAML."
            >
              <option value={BUNDLED_DEFAULT_ID}>
                Three-party guardian consent (visualization)
              </option>
              {BUILTIN_SCENARIOS.map((def) => (
                <option key={def.id} value={def.id}>
                  {def.label}
                  {def.runtimeKind === 'external' ? ' — live HTTP' : ''}
                </option>
              ))}
              {/* The "Custom upload" entry is shown only when one is
                  active; selecting it is a no-op (the user uploads
                  via "Load YAML"). It exists to reflect state, not
                  to be re-selected. */}
              {activeScenario.isCustom && (
                <option value={CUSTOM_ID} disabled>
                  Custom upload (active)
                </option>
              )}
            </select>
            <button
              className="btn"
              onClick={() => setPanelOpen(true)}
              disabled={phase === 'running'}
              title="Paste or upload a CLI-format YAML scenario."
            >
              Load YAML
            </button>
            {activeScenario.isCustom && (
              <button
                className="btn"
                onClick={onResetToDefault}
                disabled={phase === 'running'}
                title="Discard the loaded custom scenario and uploaded cards; return to the bundled three-party demo."
              >
                Discard custom
              </button>
            )}
            {/* Observer toggle is bundled-scenario-only. Custom
                scenarios always render observers — the user
                explicitly authored them in YAML. */}
            {!activeScenario.isCustom && (
              <label
                className={`observer-toggle ${includeObserver ? 'on' : ''}`}
                title="Adds a passive observer agent that taps every wire exchange. Useful for audit trails, drift detection, and cross-agent invariants."
              >
                <input
                  type="checkbox"
                  checked={includeObserver}
                  onChange={(e) => setIncludeObserver(e.target.checked)}
                  disabled={phase === 'running'}
                />
                <span>Add Observer</span>
              </label>
            )}
            {/* "Clear" is shown only after a run completes — there's
                no run state to clear in idle, and Run-while-running
                is already disabled. */}
            {phase === 'done' && (
              <button
                className="btn"
                onClick={reset}
                title="Clear the post-run state (completed-step coloring, inspector selection) without re-running."
              >
                Clear
              </button>
            )}
            <button
              className={
                phase === 'running' ? 'btn primary running' : 'btn primary'
              }
              disabled={phase === 'running'}
              onClick={runScenario}
              title={
                phase === 'done'
                  ? 'Re-run the scenario from the start. Clears the previous run state automatically.'
                  : 'Run the scenario from the start.'
              }
            >
              {phase === 'running'
                ? 'Running…'
                : phase === 'done'
                ? 'Run again'
                : 'Run scenario'}
            </button>
          </div>
        )}
        </div>
      </header>

      <main className={mode === 'home' ? 'home-shell' : 'canvas-shell'}>
        {mode === 'home' ? (
          <HomePage
            onOpen={setMode}
            onOpenBuiltin={(id) => {
              onSelectBuiltin(id);
              setMode('scenario');
            }}
          />
        ) : mode === 'scenario' ? (
          <>
            <div className="canvas">
              {/* Live-scenario banner: shown when at least one agent
                  declares `runtime: external` + a `url:`. Tells the
                  user the run will make REAL HTTP calls to that
                  deployment and that expectations are enforced. */}
              {activeScenario.runtimeKind === 'external' && (
                <div className="live-scenario-banner">
                  <span className="live-dot" aria-hidden />
                  <div className="live-text">
                    <strong>Live HTTP scenario.</strong> Clicking{' '}
                    <em>Run</em> will POST A2A JSON-RPC to{' '}
                    {activeScenario.externalUrls.map((url, i) => (
                      <span key={url}>
                        {i > 0 && ', '}
                        <code>{url}</code>
                      </span>
                    ))}
                    . Each step's <code>expect.response_status</code> and{' '}
                    <code>expect.response_contains</code> are evaluated
                    against the live response body — same checks the
                    CLI runs.
                  </div>
                </div>
              )}
              {/* Cards-needed banner: shown only when a custom scenario
                  is active and one or more visible agents lack a card.
                  Each chip is a one-click upload for that specific
                  agent — the filename is the YAML's expected basename,
                  so the user knows exactly which JSON to pick. */}
              {(() => {
                const missing = activeScenario.agents.filter(
                  (a) =>
                    !a.card &&
                    a.cardHint &&
                    (showObserver || a.role !== 'observer')
                );
                if (missing.length === 0) return null;
                return (
                  <div className="cards-needed-banner">
                    <span className="banner-label">
                      Cards needed ({missing.length}):
                    </span>
                    <div className="banner-pills">
                      {missing.map((a) => {
                        const filename =
                          a.cardHint?.split(/[\\/]/).pop() ?? a.id;
                        return (
                          <button
                            key={a.id}
                            className="card-pill"
                            onClick={() => onLoadCardForAgent(a.id)}
                            title={`Pick the JSON file for agent '${a.id}' (${a.cardHint})`}
                          >
                            <span className="card-pill-name">{filename}</span>
                            <span className="card-pill-action">↑ pick</span>
                          </button>
                        );
                      })}
                    </div>
                    <button
                      className="banner-dismiss"
                      onClick={onResetToDefault}
                      title="Discard the custom scenario and return to the bundled demo."
                    >
                      ✕
                    </button>
                  </div>
                );
              })()}
              {advanceTimeBanner && (
                <div
                  className="advance-time-banner"
                  role="status"
                  aria-live="polite"
                >
                  <span className="advance-time-icon" aria-hidden="true">
                    ⏱
                  </span>
                  <span className="advance-time-text">
                    Virtual time advanced by{' '}
                    <strong>
                      {formatVirtualTimeDelta(advanceTimeBanner.seconds)}
                    </strong>
                  </span>
                </div>
              )}
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodeClick={onNodeClick}
                onEdgeClick={onEdgeClick}
                fitView
                /* Cap the auto-zoom so a small scenario doesn't get
                   blown up to oversized nodes when fitView fills the
                   viewport. Padding gives breathing room around the
                   bounding box. */
                fitViewOptions={{ padding: 0.18, minZoom: 0.4, maxZoom: 1.05 }}
                minZoom={0.3}
                maxZoom={1.8}
                proOptions={{ hideAttribution: true }}
              >
                <Background gap={16} color="#e2e8f0" />
                <Controls position="bottom-left" />
              </ReactFlow>
            </div>

            <aside className="sidebar">
              <section className="panel">
                <h3>Steps</h3>
                <ol className="steps">
                  {stepLabels.map((s) => (
                    <li
                      key={s.index}
                      className={`step ${s.status}`}
                      onClick={() =>
                        setTarget({ kind: 'step', index: s.index })
                      }
                    >
                      <span className="step-bullet" />
                      <span className="step-text">{s.text}</span>
                    </li>
                  ))}
                </ol>
              </section>

              <section className="panel inspector">
                <h3>Inspector</h3>
                <Inspector
                  target={target}
                  agentCard={inspectorAgent}
                  agentMeta={inspectorAgentMeta}
                  step={inspectorStep}
                  stepResult={
                    target?.kind === 'step'
                      ? stepResults.get(target.index)
                      : undefined
                  }
                  onLoadCardForAgent={onLoadCardForAgent}
                />
              </section>

              {(activeScenario.runtimeKind === 'external' ||
                conformanceResults.size > 0) && (
                <section
                  className={
                    conformanceExpanded
                      ? 'panel conformance'
                      : 'panel conformance is-collapsed'
                  }
                >
                  <button
                    type="button"
                    className="conformance-toggle"
                    onClick={() => setConformanceExpanded((v) => !v)}
                    aria-expanded={conformanceExpanded}
                    aria-controls="conformance-body"
                  >
                    <span
                      className="conformance-chevron"
                      aria-hidden="true"
                    >
                      ▾
                    </span>
                    <span className="conformance-title">
                      A2A 1.0 conformance
                    </span>
                    {/* Header summary visible whether expanded or not.
                        Lets users see the verdict without expanding. */}
                    {conformanceResults.size > 0 && !conformanceRunning && (
                      <span className="conformance-summary">
                        {(() => {
                          let total = 0;
                          let passed = 0;
                          let failed = 0;
                          for (const results of conformanceResults.values()) {
                            const sum = summarize(results);
                            total += sum.total;
                            passed += sum.passed;
                            failed += sum.failed;
                          }
                          const ok = failed === 0;
                          return (
                            <span
                              className={
                                ok
                                  ? 'conformance-verdict ok'
                                  : 'conformance-verdict fail'
                              }
                            >
                              {ok ? '✓' : '✗'} {passed}/{total}
                            </span>
                          );
                        })()}
                      </span>
                    )}
                    {conformanceRunning && (
                      <span className="conformance-summary running">
                        running…
                      </span>
                    )}
                  </button>

                  <div
                    id="conformance-body"
                    className="conformance-body"
                    hidden={!conformanceExpanded}
                  >
                  {conformanceRunning && (
                    <div className="conformance-running">
                      Running batch of {CHUNK_SIZE} contracts…
                    </div>
                  )}
                  {!conformanceRunning &&
                    conformanceResults.size === 0 &&
                    activeScenario.externalUrls.length > 0 && (
                      <div className="conformance-pending">
                        <p>
                          Spec-derived contract sweep — same {ALL_CONTRACTS.length}{' '}
                          contracts the CLI's{' '}
                          <code>a2a-testbed conformance</code> command
                          runs; identical verdict. Paced in batches of{' '}
                          {CHUNK_SIZE} so a sweep stays inside the
                          target agent's rate-limit window.
                        </p>
                        <button
                          type="button"
                          className="conformance-run-btn"
                          onClick={runNextConformanceBatch}
                        >
                          Run conformance ({CHUNK_SIZE} of {ALL_CONTRACTS.length})
                        </button>
                      </div>
                    )}
                  {!conformanceRunning &&
                    conformanceResults.size === 0 &&
                    activeScenario.externalUrls.length === 0 && (
                      <div className="conformance-pending">
                        Conformance only runs against agents declared
                        with <code>runtime: external</code>.
                      </div>
                    )}
                  {[...conformanceResults.entries()].map(([url, results]) => {
                    const sum = summarize(results);
                    return (
                      <div key={url} className="conformance-block">
                        <div className="conformance-head">
                          <span
                            className={
                              sum.failed === 0
                                ? 'conformance-verdict ok'
                                : 'conformance-verdict fail'
                            }
                          >
                            {sum.failed === 0 ? '✓' : '✗'}{' '}
                            {sum.passed}/{sum.total} passed
                            {sum.softPasses > 0 &&
                              ` · ${sum.softPasses} soft`}
                          </span>
                          <code className="conformance-url">{url}</code>
                        </div>
                        <ul className="conformance-list">
                          {results.map((r) => (
                            <li
                              key={r.contractId}
                              className={
                                !r.passed
                                  ? 'conformance-row fail'
                                  : r.softPass
                                  ? 'conformance-row soft'
                                  : 'conformance-row ok'
                              }
                            >
                              <span className="conformance-mark">
                                {!r.passed ? '✗' : r.softPass ? '~' : '✓'}
                              </span>
                              <span className="conformance-section">
                                {r.specSection ?? '—'}
                              </span>
                              <span className="conformance-name">
                                {r.contractId.replace(/^transport\./, '')}
                              </span>
                              {r.detail && (
                                <span className="conformance-detail">
                                  {r.detail}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                  {conformanceResults.size > 0 && (() => {
                    // All URLs share the contract list, so any URL's
                    // progress reflects sweep position. Pick the
                    // smallest so the button reflects the trailing
                    // agent in a multi-agent scenario.
                    let minDone = ALL_CONTRACTS.length;
                    for (const url of activeScenario.externalUrls) {
                      const done = conformanceProgress.get(url) ?? 0;
                      if (done < minDone) minDone = done;
                    }
                    const remaining = ALL_CONTRACTS.length - minDone;
                    const nextBatch = Math.min(CHUNK_SIZE, remaining);
                    return (
                      <div className="conformance-footer">
                        {remaining > 0 ? (
                          <button
                            type="button"
                            className="conformance-run-btn"
                            onClick={runNextConformanceBatch}
                            disabled={conformanceRunning}
                          >
                            Run next {nextBatch} ({minDone}/
                            {ALL_CONTRACTS.length} done)
                          </button>
                        ) : (
                          <span className="conformance-done">
                            All {ALL_CONTRACTS.length} contracts run.
                          </span>
                        )}
                        <button
                          type="button"
                          className="conformance-reset-btn"
                          onClick={resetConformance}
                          disabled={conformanceRunning}
                        >
                          Reset
                        </button>
                      </div>
                    );
                  })()}
                  </div>
                </section>
              )}
            </aside>
          </>
        ) : (
          <div className="validate-shell">
            <ValidatePanel />
          </div>
        )}
      </main>

      <footer className="footer">
        <div className="footer-inner">
          <div className="footer-left">
            © {new Date().getFullYear()} a2a-testbed · Apache 2.0 ·{' '}
            <a
              href="https://a2a-testbed.com"
              target="_blank"
              rel="noreferrer"
            >
              a2a-testbed.com
            </a>{' '}
            ·{' '}
            <a
              href="https://github.com/ravikiran438/a2a-testbed"
              target="_blank"
              rel="noreferrer"
            >
              github
            </a>
          </div>
          <div className="footer-mid">
            {mode === 'scenario' ? (
              <>
                {activeScenario.steps.length}-step scenario ·{' '}
                {activeScenario.name} · click a node or edge to inspect
              </>
            ) : mode === 'validate' ? (
              <>Browser-side JSON Schema validation · no backend</>
            ) : (
              <>Experimental tooling for the A2A protocol</>
            )}
          </div>
          <div className="footer-right">
            <a href="https://a2a-protocol.org/" target="_blank" rel="noreferrer">
              A2A Spec
            </a>
            {' · '}
            <a href="https://modelcontextprotocol.io/" target="_blank" rel="noreferrer">
              MCP
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
