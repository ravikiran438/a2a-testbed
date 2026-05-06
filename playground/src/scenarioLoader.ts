// YAML scenario loader for the browser playground.
//
// Accepts the same scenario format the CLI uses (see
// `examples/scenarios/*.yaml`). Browser-side concerns:
//   - `agents[].card` is normally a path — we can't follow paths in
//     the browser, so a string `card` is preserved as a hint string
//     and the inspector falls back to displaying just id + role.
//     If the user inlines the AgentCard JSON under `card:` instead,
//     we use it directly.
//   - `agents[].runtime` + `agents[].url` are preserved. When an
//     agent declares `runtime: external` + a `url`, the playground
//     makes a REAL HTTP POST to that URL during scenario execution
//     instead of the animation-only path. Other runtime values are
//     passed through but only the external case affects execution.
//   - `mode`, `reports` are read but ignored — CLI-only concerns.
//   - `flow[].expect` is preserved verbatim. For external steps
//     it's enforced (response_status, response_contains). For
//     simulated steps it's shown in the inspector but not enforced.
//
// Same YAML works in both surfaces.

import yaml from 'js-yaml';
import type { AgentCard, ScenarioStep } from './scenario';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LoadedAgent {
  id: string;
  role?: string;
  /** Inline AgentCard if provided; null when only a path was given. */
  card: AgentCard | null;
  /** When card is null, retain the original string for display in the inspector. */
  cardHint?: string;
  /** YAML `runtime:` value, preserved verbatim. Only `external`
   *  affects execution in the browser today. */
  runtime?: string;
  /** YAML `url:` value when present. Required for `runtime: external`
   *  to actually call out — otherwise the agent falls back to the
   *  animation-only path. */
  url?: string;
}

export interface LoadedScenario {
  name: string;
  description?: string;
  agents: LoadedAgent[];
  steps: LoadedStep[];
  /** Number of CLI flow entries skipped because they aren't message
   *  exchanges (e.g. `kind: observe`, `kind: advance_time`, or any
   *  step missing `from` or `to`). The browser visualizes wire
   *  traffic only; clock advances and passive recorder ticks have
   *  no edge to draw. */
  skippedNonMessageSteps: number;
  /** Counts per recognized special-kind value so the modal can give
   *  a slightly more useful note than "N steps skipped". */
  skippedKinds: Record<string, number>;
  /** How many `card:` path references were resolved against the
   *  uploaded card JSONs vs. left as path-hints. */
  cardsResolved: number;
  cardsTotal: number;
}

export interface LoadedStep {
  from: string;
  to: string;
  action: string;
  message?: string;
  expect?: Record<string, unknown>;
  duration_ms: number;
}

export class ScenarioLoadError extends Error {}

// ---------------------------------------------------------------------------
// Parser + validator
// ---------------------------------------------------------------------------

/**
 * Parse YAML text into a LoadedScenario. Throws ScenarioLoadError with a
 * human-readable message on any structural problem.
 *
 * `cardLookup` is an optional map of {filename → AgentCard JSON} that
 * the parser uses to resolve `agent.card` path strings. When the YAML
 * has `card: ../agent-cards/three-party/alice.json`, the parser
 * extracts the basename (`alice.json`) and looks it up. Unresolved
 * paths are preserved as `cardHint` strings for the inspector.
 */
export function parseScenarioYaml(
  text: string,
  cardLookup: Record<string, AgentCard> = {}
): LoadedScenario {
  let raw: unknown;
  try {
    raw = yaml.load(text);
  } catch (err) {
    throw new ScenarioLoadError(`YAML parse error: ${(err as Error).message}`);
  }
  if (!raw || typeof raw !== 'object') {
    throw new ScenarioLoadError('Scenario YAML must be a single mapping/object.');
  }

  const root = raw as Record<string, unknown>;
  const name = typeof root.name === 'string' ? root.name : 'Unnamed scenario';
  const description = typeof root.description === 'string' ? root.description : undefined;

  const agentsRaw = root.agents;
  if (!Array.isArray(agentsRaw) || agentsRaw.length === 0) {
    throw new ScenarioLoadError(
      'Scenario must declare at least one agent under `agents:`.'
    );
  }

  const agents: LoadedAgent[] = agentsRaw.map((entry, idx) => {
    if (!entry || typeof entry !== 'object') {
      throw new ScenarioLoadError(`agents[${idx}] is not an object.`);
    }
    const a = entry as Record<string, unknown>;
    const id = a.id;
    if (typeof id !== 'string' || !id) {
      throw new ScenarioLoadError(`agents[${idx}].id must be a non-empty string.`);
    }
    const role = typeof a.role === 'string' ? a.role : undefined;

    let card: AgentCard | null = null;
    let cardHint: string | undefined;
    if (typeof a.card === 'string') {
      // CLI-style path reference. Try to resolve via the cardLookup
      // (uploaded card JSON files keyed by basename); fall back to
      // exposing the path string as a hint when unresolved.
      cardHint = a.card;
      const basename = a.card.split(/[\\/]/).pop() ?? a.card;
      const resolved = cardLookup[basename];
      if (resolved) {
        card = resolved;
        cardHint = undefined; // successfully resolved → no hint needed
      }
    } else if (a.card && typeof a.card === 'object') {
      card = a.card as AgentCard;
    }

    const runtime = typeof a.runtime === 'string' ? a.runtime : undefined;
    const url = typeof a.url === 'string' ? a.url : undefined;

    return { id, role, card, cardHint, runtime, url };
  });

  const seenIds = new Set<string>();
  for (const a of agents) {
    if (seenIds.has(a.id)) {
      throw new ScenarioLoadError(`Duplicate agent id: '${a.id}'.`);
    }
    seenIds.add(a.id);
  }

  const flowRaw = root.flow;
  if (!Array.isArray(flowRaw)) {
    throw new ScenarioLoadError('Scenario must declare a `flow:` list.');
  }

  const steps: LoadedStep[] = [];
  let skippedNonMessageSteps = 0;
  const skippedKinds: Record<string, number> = {};

  flowRaw.forEach((entry, idx) => {
    if (!entry || typeof entry !== 'object') {
      throw new ScenarioLoadError(`flow[${idx}] is not an object.`);
    }
    const s = entry as Record<string, unknown>;
    const from = s.from;
    const to = s.to;
    const action = s.action;

    // Non-message step. CLI YAMLs use a `kind:` field for things
    // that aren't agent-to-agent messages — e.g. `kind: observe`
    // (passive recorder tick) or `kind: advance_time` (virtual
    // clock advance). Steps missing `from` or `to` are also
    // non-messages by definition. The browser visualizes wire
    // traffic only, so we count and skip these and report a
    // tally to the user.
    const declaredKind = typeof s.kind === 'string' ? s.kind : null;
    const isNonMessageStep = declaredKind !== null || !to || !from;
    if (isNonMessageStep) {
      skippedNonMessageSteps += 1;
      const tag =
        declaredKind ??
        (!from && !to
          ? 'orphan'
          : !from
          ? 'missing from'
          : 'missing to');
      skippedKinds[tag] = (skippedKinds[tag] ?? 0) + 1;
      return;
    }

    if (typeof from !== 'string' || !from) {
      throw new ScenarioLoadError(`flow[${idx}].from must be a non-empty string.`);
    }
    if (typeof to !== 'string' || !to) {
      throw new ScenarioLoadError(`flow[${idx}].to must be a non-empty string.`);
    }
    if (typeof action !== 'string' || !action) {
      throw new ScenarioLoadError(`flow[${idx}].action must be a non-empty string.`);
    }
    if (!seenIds.has(from)) {
      throw new ScenarioLoadError(
        `flow[${idx}].from references unknown agent '${from}'.`
      );
    }
    if (!seenIds.has(to)) {
      throw new ScenarioLoadError(
        `flow[${idx}].to references unknown agent '${to}'.`
      );
    }

    const message = typeof s.message === 'string' ? s.message : undefined;
    const expect =
      s.expect && typeof s.expect === 'object'
        ? (s.expect as Record<string, unknown>)
        : undefined;

    // duration_ms not in CLI YAML; default to 900ms per step so the
    // animation has a consistent rhythm.
    const duration_ms =
      typeof s.duration_ms === 'number' && s.duration_ms > 0
        ? s.duration_ms
        : 900;

    steps.push({ from, to, action, message, expect, duration_ms });
  });

  // Count how many agents wanted a card (had a `card:` field) and how
  // many ended up with one resolved.
  const cardsTotal = agents.filter(
    (a) => a.card !== null || a.cardHint !== undefined
  ).length;
  const cardsResolved = agents.filter((a) => a.card !== null).length;

  return {
    name,
    description,
    agents,
    steps,
    skippedNonMessageSteps,
    skippedKinds,
    cardsResolved,
    cardsTotal,
  };
}

// ---------------------------------------------------------------------------
// Auto-layout: arrange N agents on a canvas
// ---------------------------------------------------------------------------

export interface NodePosition {
  x: number;
  y: number;
}

/**
 * Position N agents on the canvas. Hand-tuned for small N (1–4),
 * radial for 5+. Produces stable positions: same input → same output.
 */
export function layoutAgents(count: number): NodePosition[] {
  const cx = 400;
  const cy = 240;

  if (count === 0) return [];
  if (count === 1) return [{ x: cx, y: cy }];
  if (count === 2) {
    return [
      { x: cx - 280, y: cy },
      { x: cx + 280, y: cy },
    ];
  }
  if (count === 3) {
    return [
      { x: cx - 280, y: cy + 80 },
      { x: cx + 280, y: cy + 80 },
      { x: cx, y: cy - 180 },
    ];
  }
  if (count === 4) {
    return [
      { x: cx - 320, y: cy - 120 },
      { x: cx + 320, y: cy - 120 },
      { x: cx + 320, y: cy + 180 },
      { x: cx - 320, y: cy + 180 },
    ];
  }
  // Radial layout for 5+.
  const r = Math.min(280, 80 + count * 24);
  return Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * 2 * Math.PI - Math.PI / 2; // start at top
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    };
  });
}

// ---------------------------------------------------------------------------
// Adapter: LoadedScenario → ScenarioStep[] used by App.tsx animation
// ---------------------------------------------------------------------------

/**
 * Convert a LoadedScenario's steps into the ScenarioStep shape the
 * canvas runtime consumes.
 *
 * The browser doesn't actually run agents, so we deliberately leave
 * `validation` UNSET — there's no real finding. Instead the
 * YAML-declared `expect` block is preserved as a separate field on
 * the step; the inspector renders it as the user's authored
 * expectations alongside a "not enforced in browser" note.
 */
export function adaptSteps(loaded: LoadedScenario): ScenarioStep[] {
  return loaded.steps.map((s) => ({
    from: s.from,
    to: s.to,
    action: s.action,
    extension_uri: '',
    outcome: 'ok' as const,
    duration_ms: s.duration_ms,
    message: {
      kind: 'a2a.message',
      from_agent: s.from,
      to_agent: s.to,
      action: s.action,
      ...(s.message ? { content: s.message } : {}),
    },
    expect: s.expect,
    // validation: intentionally omitted for custom scenarios.
  }));
}
