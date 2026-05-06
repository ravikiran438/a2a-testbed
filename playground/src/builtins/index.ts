// Registry of built-in scenarios bundled with the playground.
//
// Each entry references YAML + AgentCard JSON files in
// `examples/` via Vite's `?raw` import suffix. The files are
// inlined into the production bundle, so the playground ships
// with these demos and stays in lockstep with whatever the CLI
// runs against the same files.
//
// Adding a new built-in:
//   1. Drop the YAML in `examples/scenarios/`.
//   2. Drop its AgentCards in `examples/agent-cards/<group>/`.
//   3. Import them with `?raw` here and append to BUILTIN_SCENARIOS.

import cloudflareMathYaml from '../../../examples/scenarios/cloudflare_math_demo.yaml?raw';
import cloudflareMathProberCard from '../../../examples/agent-cards/cloudflare-math/prober.json?raw';
import cloudflareMathMathCard from '../../../examples/agent-cards/cloudflare-math/math.json?raw';
import taskRunnerYaml from '../../../examples/scenarios/task_runner_demo.yaml?raw';
import taskRunnerProberCard from '../../../examples/agent-cards/task-runner/prober.json?raw';
import taskRunnerRunnerCard from '../../../examples/agent-cards/task-runner/runner.json?raw';

/** A built-in scenario the user can pick from the playground dropdown. */
export interface BuiltinScenarioDef {
  /** Stable identifier used as the dropdown's value. */
  id: string;
  /** Short label rendered in the dropdown. */
  label: string;
  /** One-line description shown under the dropdown / in the inspector. */
  description: string;
  /** Raw YAML body, identical to the file the CLI consumes. */
  yaml: string;
  /** Map of `<basename>.json -> raw JSON text`, resolves the YAML's
   *  `card: <path>` references the same way uploads do. */
  cards: Record<string, string>;
  /** Hint for the UI: 'external' means the YAML declares one or more
   *  agents with `runtime: external` + `url:` and the playground will
   *  make real HTTP calls; 'simulated' means animation-only. */
  runtimeKind: 'simulated' | 'external';
}

export const BUILTIN_SCENARIOS: BuiltinScenarioDef[] = [
  {
    id: 'cloudflare-math',
    label: 'Cloudflare math agent (live LLM)',
    description:
      'Sends arithmetic + word-math questions to a real A2A agent on ' +
      'Cloudflare Workers (Groq Llama 3.3, JSON mode). The playground ' +
      'makes real HTTP calls and verifies each response against the ' +
      "scenario's expect blocks.",
    yaml: cloudflareMathYaml,
    cards: {
      'prober.json': cloudflareMathProberCard,
      'math.json': cloudflareMathMathCard,
    },
    runtimeKind: 'external',
  },
  {
    id: 'task-runner',
    label: 'Task runner agent (live A2A lifecycle)',
    description:
      'A reference A2A 1.0 agent exercising the full task surface — ' +
      'Tasks via message/send, SSE streaming via message/stream, ' +
      'tasks/get/list/cancel, tasks/resubscribe, and push ' +
      'notifications. The playground runs a 58-contract conformance ' +
      'sweep against it on every Run.',
    yaml: taskRunnerYaml,
    cards: {
      'prober.json': taskRunnerProberCard,
      'runner.json': taskRunnerRunnerCard,
    },
    runtimeKind: 'external',
  },
];

/** Look up a built-in by id; returns undefined if no match. */
export function findBuiltin(id: string): BuiltinScenarioDef | undefined {
  return BUILTIN_SCENARIOS.find((s) => s.id === id);
}
