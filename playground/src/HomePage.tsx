import type { Mode } from './App';

interface Props {
  onOpen: (mode: Mode) => void;
  /** Optional deep-link: open the Scenario tab and immediately
   *  swap to the named built-in scenario. Used by the "Live LLM
   *  agent validator" tool card so first-time visitors land on
   *  the live demo with one click instead of two. */
  onOpenBuiltin: (builtinId: string) => void;
  /** Open the Validator tab focused on a specific artifact
   *  (AgentCard vs ACS manifest). */
  onOpenValidate: (target: 'agentcard' | 'acs') => void;
}

interface ToolCard {
  id: 'scenario' | 'validate' | 'acs' | 'polyglot' | 'live-llm';
  title: string;
  body: string;
  cta: string;
  external?: string;
  badge?: string;
  /** Built-in id to swap to when the card is clicked. Only used
   *  when id === 'live-llm'. */
  builtinId?: string;
}

const TOOLS: ToolCard[] = [
  {
    id: 'scenario',
    title: 'Multi-agent scenario',
    body:
      'Render a network of A2A agents as a node graph; animate ' +
      'message edges as a scripted flow runs end-to-end. Toggle ' +
      '"Preview ACS" to overlay runtime governance — each handoff is ' +
      'evaluated and the edges color by verdict (allow / warn / deny); ' +
      'flip on "Enforce ACS" and a denied handoff halts the flow.',
    cta: 'Open scenario',
  },
  {
    id: 'validate',
    title: 'AgentCard validator',
    body:
      'Paste an AgentCard JSON. The validator fetches each declared ' +
      "extension's published manifest, runs JSON Schema validation in " +
      'the browser, and reports per-extension findings. No backend.',
    cta: 'Open validator',
  },
  {
    id: 'acs',
    title: 'ACS manifest validator',
    body:
      'Validate an Agent Control Specification (ACS) manifest in your ' +
      'browser — the portable YAML that places runtime controls at an ' +
      "agent's lifecycle checkpoints. Same structural + semantic checks " +
      'as the `a2a-testbed acs validate` CLI, with zero backend.',
    cta: 'Validate ACS manifest',
    badge: 'new',
  },
  {
    id: 'live-llm',
    title: 'Live LLM agent validator',
    body:
      'Drive a real LLM-backed A2A agent (deployed on Cloudflare ' +
      'Workers, Llama 3.3 in JSON mode) from your browser. The ' +
      'playground POSTs A2A JSON-RPC to the live worker and ' +
      "evaluates each step's expect block against the actual " +
      'response — same checks the CLI runs.',
    cta: 'Run live demo',
    builtinId: 'cloudflare-math',
    badge: 'live HTTP',
  },
  {
    id: 'polyglot',
    title: 'Polyglot agents (CLI)',
    body:
      'Run a scenario where each agent is a real subprocess in a ' +
      'different language: Python, Go, Node.js, Java. Each agent is ' +
      'a separate process talking real HTTP+JSON-RPC. CLI-only; the ' +
      'browser playground does not spawn subprocesses.',
    cta: 'Open repo',
    external: 'https://github.com/ravikiran438/a2a-testbed/tree/main/agents',
    badge: 'CLI',
  },
];

interface PainPoint {
  problem: string;
  solution: string;
}

const PAIN_POINTS: PainPoint[] = [
  {
    problem: 'Integration brittleness between agents',
    solution:
      'Scripted scenario runner exercises the wire format end-to-end and ' +
      'surfaces breakages early.',
  },
  {
    problem: 'Language compatibility barriers',
    solution:
      'Polyglot subprocess runtimes (Python, Go, Node.js, Java) ' +
      'cross-validated under one scenario.',
  },
  {
    problem: 'Opacity (how do agents actually collaborate?)',
    solution:
      'Observer agent pattern records every wire exchange; A2A 1.0 has ' +
      'no observer primitive — the testbed adds one.',
  },
  {
    problem: 'Extension validation gap',
    solution:
      'A2A 1.0 specifies extension URIs but not how to validate the ' +
      'payload. The testbed proposes a manifest convention: each URI ' +
      'serves a JSON Schema; a generic validator checks any payload.',
  },
  {
    problem: 'Runtime governance scattered across frameworks',
    solution:
      'Agent Control Specification (ACS) support: validate a portable ' +
      'control manifest, map its eight intervention points onto the A2A ' +
      'wire seam, and prove the control layer fails closed under injected ' +
      'faults. Validated both in the CLI and in-browser, same verdicts.',
  },
  {
    problem: 'Cross-harness wire conformance',
    solution:
      'Agents built in different runtimes (Claude Code, Codex, ' +
      'LangGraph, CrewAI, OpenHarness, custom) need to interoperate ' +
      'over A2A. The testbed validates that their published wire ' +
      'surface matches the spec, regardless of which harness produced ' +
      'them.',
  },
];

interface RefCard {
  name: string;
  one_liner: string;
  href: string;
  role: string;
  badge?: string;
  /** Overrides the default link text (which assumes an A2A-spec issue). */
  link_label?: string;
}

const REFERENCES: RefCard[] = [
  {
    name: 'A2A Protocol',
    one_liner:
      'Open standard for agent-to-agent collaboration. Defines AgentCard, ' +
      'Task, Message, Artifact, Part. Authored by Google; governed by ' +
      'LF AI & Data Foundation.',
    href: 'https://a2a-protocol.org/',
    role: 'Inter-agent collaboration',
  },
  {
    name: 'Model Context Protocol (MCP)',
    one_liner:
      'Open standard for agent-to-tool integration. Authored by Anthropic. ' +
      'Complements A2A: A2A handles agent ↔ agent, MCP handles agent ↔ tool.',
    href: 'https://modelcontextprotocol.io/',
    role: 'Agent-to-tool integration',
  },
  {
    name: 'Extension manifest convention',
    one_liner:
      'A2A 1.0 specifies extension URIs but not how to validate the ' +
      'declared payload. We propose a small convention: each extension ' +
      'publishes a JSON Schema manifest at its URI, so any third-party ' +
      'validator can check declared payloads with zero protocol-specific ' +
      'code. Reference implementation is what powers this playground.',
    href: 'https://github.com/a2aproject/A2A/issues/1464',
    role: 'Schema discovery for capabilities.extensions[]',
    badge: 'experimental',
  },
  {
    name: 'Agent Control Specification (ACS)',
    one_liner:
      'Open, vendor-neutral standard for runtime governance of agents: ' +
      'deterministic controls at eight lifecycle checkpoints, expressed as ' +
      "a portable YAML manifest. Part of Microsoft's Agent Governance " +
      'Toolkit. The testbed maps ACS onto the A2A wire seam and validates ' +
      'manifests offline (CLI) and in-browser, with fail-closed checks.',
    href: 'https://github.com/microsoft/agent-governance-toolkit/blob/main/policy-engine/spec/SPECIFICATION.md',
    role: 'Runtime governance / safety controls',
    badge: 'experimental',
    link_label: 'See the ACS specification ↗',
  },
  {
    name: 'ASSERT',
    one_liner:
      "Microsoft's open-source, spec-driven agent evaluation framework: " +
      'turn natural-language behavior requirements into executable evals. ' +
      'a2a-testbed ships an ASSERT callable target that drives an A2A agent ' +
      'and feeds ACS verdicts to the judge as evidence.',
    href: 'https://github.com/microsoft/ASSERT',
    role: 'Spec-driven agent evaluation',
    badge: 'experimental',
    link_label: 'See the ASSERT repo ↗',
  },
  {
    name: 'Agent harnesses',
    one_liner:
      'The runtime layer that wraps a model into a usable agent — ' +
      'tools, memory, planning, sub-agent orchestration, sandboxes. ' +
      'Examples: Claude Code, Codex, LangGraph, CrewAI, OpenHarness. ' +
      'This testbed validates the wire layer above whatever harness ' +
      'you choose.',
    href: 'https://github.com/ai-boost/awesome-harness-engineering',
    role: 'The runtime layer below A2A',
  },
  {
    name: 'a2aproject/a2a-tck',
    one_liner:
      'Official Technology Compatibility Kit from the A2A project. ' +
      'Single-agent compliance validator targeting A2A v0.3.0 with ' +
      'multi-transport (JSON-RPC + gRPC + REST) equivalence testing. ' +
      'The right tool for "is my agent A2A 1.0 compliant?" — this ' +
      'testbed sits alongside it for multi-agent and extension testing.',
    href: 'https://github.com/a2aproject/a2a-tck',
    role: 'Single-agent compliance',
  },
  {
    name: 'a2aproject/a2a-inspector',
    one_liner:
      'Official interactive debugger UI. Connect to one A2A endpoint, ' +
      'browse its AgentCard, send messages from a chat panel, inspect ' +
      'raw JSON-RPC in a console. Useful as a human-in-the-loop ' +
      "companion to this testbed's scripted scenarios.",
    href: 'https://github.com/a2aproject/a2a-inspector',
    role: 'Interactive single-agent debugger',
  },
];

export function HomePage({ onOpen, onOpenBuiltin, onOpenValidate }: Props) {
  return (
    <div className="home">
      <section className="hero">
        <div className="hero-tag">
          A2A multi-agent testbed
          <span className="hero-domain"> · a2a-testbed.com</span>
        </div>
        <h1>Test A2A agent networks before you ship them</h1>
        <p className="hero-lead">
          A polyglot, JSON-driven multi-agent simulator with a scenario runner, observer pattern,
          virtual time control, fault injection, and an in-browser AgentCard <em>and</em> Agent
          Control Specification (ACS) validator. Exercises multi-agent A2A interactions end-to-end
          across runtimes — declarative scenarios, real wire traffic.
        </p>
        <p className="hero-lead">
          Then layer <strong>ACS runtime governance</strong> on those flows: deterministic allow /
          warn / deny / escalate verdicts at each lifecycle checkpoint, fail-closed enforcement that
          blocks a handoff before it's sent, validated in both the CLI and the browser.
        </p>
        <p className="hero-sublead">
          <strong>Harness-agnostic.</strong> Whatever runtime your agent lives inside — Claude Code,
          Codex, LangGraph, CrewAI, OpenHarness, or your own — the testbed validates that what it
          publishes on the wire conforms to A2A.
        </p>
        <div className="hero-actions">
          <button className="btn primary" onClick={() => onOpen('scenario')}>
            Run sample scenario →
          </button>
          <button className="btn" onClick={() => onOpenValidate('agentcard')}>
            Validate an AgentCard
          </button>
          <button className="btn" onClick={() => onOpenValidate('acs')}>
            Validate an ACS manifest
          </button>
        </div>
      </section>

      <section className="tools">
        <h2>Tools</h2>
        <div className="tool-grid">
          {TOOLS.map((t) => (
            <div className="tool-card" key={t.id}>
              <div className="tool-head">
                <h3>{t.title}</h3>
                {t.badge && <span className="tool-badge">{t.badge}</span>}
              </div>
              <p>{t.body}</p>
              {t.external ? (
                <a className="btn small" href={t.external} target="_blank" rel="noreferrer">
                  {t.cta} ↗
                </a>
              ) : t.id === 'live-llm' && t.builtinId ? (
                <button className="btn small" onClick={() => onOpenBuiltin(t.builtinId!)}>
                  {t.cta}
                </button>
              ) : t.id === 'acs' ? (
                <button className="btn small" onClick={() => onOpenValidate('acs')}>
                  {t.cta}
                </button>
              ) : t.id === 'validate' ? (
                <button className="btn small" onClick={() => onOpenValidate('agentcard')}>
                  {t.cta}
                </button>
              ) : (
                <button className="btn small" onClick={() => onOpen(t.id as Mode)}>
                  {t.cta}
                </button>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="why">
        <h2>What this tool focuses on</h2>
        <p className="why-lead">
          Multi-agent collaboration testing, cross-runtime conformance, and validation of declared
          extensions are the focus areas of this testbed. The pain points below are what it sets out
          to address.
        </p>
        <table className="pain-table">
          <thead>
            <tr>
              <th>Problem</th>
              <th>How this tool addresses it</th>
            </tr>
          </thead>
          <tbody>
            {PAIN_POINTS.map((p) => (
              <tr key={p.problem}>
                <td className="pain-problem">{p.problem}</td>
                <td className="pain-solution">{p.solution}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="observer-pattern">
        <div className="section-head-row">
          <h2>The Observer Pattern</h2>
          <span className="experimental-badge">testbed-only role</span>
        </div>
        <p className="why-lead">
          A2A 1.0 defines bilateral exchanges only — sender and receiver, nothing else. Real
          multi-agent deployments often need a passive third party that watches the conversation
          without sitting on the message path. The testbed adds this as an optional scenario role
          you can attach to any flow.
        </p>

        <div className="obs-grid">
          <div className="obs-card">
            <div className="obs-tag">Use case</div>
            <h3>Audit-trail completeness</h3>
            <p>
              An audit observer can verify that every consent step produced an adherence event, that
              every escalation reached its destination, that no required acknowledgement was
              dropped. The originating agent can&apos;t verify this on its own — it only sees its
              own traffic.
            </p>
          </div>
          <div className="obs-card">
            <div className="obs-tag">Use case</div>
            <h3>Behavioral drift detection</h3>
            <p>
              An integrity observer watches an agent&apos;s outputs across many steps and compares
              them to a baseline fingerprint. If outputs drift far enough, the observer flags it.
              The monitored agent doesn&apos;t need to cooperate; the observer listens passively.
            </p>
          </div>
          <div className="obs-card">
            <div className="obs-tag">Use case</div>
            <h3>Cross-agent invariants</h3>
            <p>
              &quot;Every message Alice sends to Bob must be acknowledged within N ticks.&quot;
              That&apos;s an invariant on the traffic graph, not on either endpoint. An observer is
              the natural place to enforce it.
            </p>
          </div>
        </div>

        <div className="obs-howto">
          <h3>How to try it</h3>
          <ol className="how-list">
            <li>
              Open <em>Scenario</em> mode. By default the canvas shows three agents (Alice, Bob,
              Carol) — the simplest path through the flow.
            </li>
            <li>
              Toggle <strong>Add Observer</strong> in the header. A fourth agent appears on the
              canvas, and a fourth step is added to the script:{' '}
              <em>observer → carol: attest_integrity</em>.
            </li>
            <li>
              Click <em>Run scenario</em>. Notice the observer never sits between Alice/Bob/Carol;
              it taps the conversation and emits its own attestation. Click the observer&apos;s edge
              after the run to see what it recorded.
            </li>
          </ol>
        </div>

        <p className="obs-honest">
          The observer role exists in the testbed; it isn&apos;t in A2A 1.0. In production
          you&apos;d implement it via a service-mesh sidecar, a webhook from each agent, or an
          external proxy — none of which the spec mandates. This playground gives you the simplest
          version (in-process traffic tap) so you can see the pattern at work before deciding which
          production form fits your stack.
        </p>

        <div className="obs-inspiration">
          <h3>Inspired by</h3>
          <p>
            The shape of this pattern — a passive third-party agent that taps wire exchanges and
            compares observed behavior to a published baseline — draws directly on prior work in two
            companion specifications:
          </p>
          <ul>
            <li>
              <strong>
                <a href="https://doi.org/10.5281/zenodo.19628589" target="_blank" rel="noreferrer">
                  Pratyahara / NERVE
                </a>
              </strong>{' '}
              — a multi-agent behavioral integrity model where <em>microglial observer</em> agents
              continuously compare an agent&apos;s output distribution to its baseline fingerprint
              and flag <em>drift</em> when the distribution diverges far enough.
            </li>
            <li>
              <strong>
                <a href="https://doi.org/10.5281/zenodo.19659633" target="_blank" rel="noreferrer">
                  Yathartha
                </a>
              </strong>{' '}
              — a refinement that distinguishes <em>drift</em> (change from a known baseline) from{' '}
              <em>jaggedness</em> (no baseline ever existed). Without that distinction, observers
              raise false drift flags on tasks the agent was never measured on.
            </li>
          </ul>
          <p>
            The testbed&apos;s observer is the generic shape only — it doesn&apos;t commit to either
            the fingerprint algorithm or the capability-surface model. You attach the semantic
            validator your protocol needs; the testbed gives you the wire-level traffic tap to plug
            it into.
          </p>
        </div>

        <p className="obs-deep-dive-cta">
          A longer write-up — including how A2A 1.0 currently leaves multi-agent observation to
          deployment, the assembly costs of the spec&apos;s recommended path, and a comparison table
          of spec-aligned alternatives — lives on the docs site.{' '}
          <a
            href="https://ravikiran438.github.io/agent-protocol-stack/observer-pattern/"
            target="_blank"
            rel="noreferrer"
          >
            Read the full deep-dive ↗
          </a>
        </p>
      </section>

      <section className="reference">
        <h2>The protocols this tool sits next to</h2>
        <div className="ref-grid">
          {REFERENCES.map((r) => (
            <a className="ref-card" key={r.name} href={r.href} target="_blank" rel="noreferrer">
              <div className="ref-role-row">
                <div className="ref-role">{r.role}</div>
                {r.badge && (
                  <span
                    className="experimental-badge"
                    title="Not yet adopted by the A2A spec; this is a proposal."
                  >
                    {r.badge}
                  </span>
                )}
              </div>
              <h3>{r.name}</h3>
              <p>{r.one_liner}</p>
              <span className="ref-link">
                {r.link_label
                  ? r.link_label
                  : r.badge === 'experimental'
                    ? 'See the related A2A issue ↗'
                    : 'Learn more ↗'}
              </span>
            </a>
          ))}
        </div>
      </section>

      <section className="how">
        <h2>How to use</h2>
        <ol className="how-list">
          <li>
            <strong>Run the bundled three-party scenario.</strong> Click <em>Open scenario</em>{' '}
            above. Hit <em>Run scenario</em>. Watch four agents (Alice, Bob, Carol, Observer)
            exchange messages with animated edges. Click any node or edge to inspect the AgentCard
            or message payload.
          </li>
          <li>
            <strong>Validate an AgentCard against live manifests.</strong> Click{' '}
            <em>Open validator</em>. The textarea pre-loads a sample card declaring four extensions.
            Click <em>Validate against live manifests</em>. The validator fetches each extension's
            JSON Schema from its URI and reports per-extension findings. Edit the JSON and
            re-validate to see error reporting.
          </li>
          <li>
            <strong>Run polyglot scenarios via the CLI.</strong> Browser cannot spawn subprocesses;
            cross-language scenarios use the Python CLI:
            <pre className="how-code">
              {`$ a2a-testbed run examples/scenarios/polyglot_smoke.yaml`}
            </pre>
            Each agent in the YAML can pick <code>runtime: python_inproc</code>,{' '}
            <code>python_subproc</code>, <code>go</code>, <code>nodejs</code>, <code>java</code>, or{' '}
            <code>external</code>. Templates for each language live under{' '}
            <code>agents/&lt;language&gt;-template/</code>.
          </li>
        </ol>
      </section>

      <section className="generate-manifest">
        <div className="section-head-row">
          <h2>Generate a manifest for your own extension</h2>
          <span className="experimental-badge">experimental</span>
        </div>
        <p className="why-lead">
          If you author an A2A extension and want third-party validators to check declared payloads
          automatically, publish a manifest at the extension URI. The testbed CLI generates one from
          a Pydantic model:
        </p>
        <pre className="how-code">
          {`$ pip install a2a-testbed

$ a2a-testbed manifest generate \\
    --extension-uri https://your-org.github.io/your-protocol/v1 \\
    --name "Your Protocol" \\
    --version 1.0.0 \\
    --ref-class your_protocol.types:YourServiceRef \\
    --output ./v1/manifest.json

$ a2a-testbed manifest validate ./v1/manifest.json
$ a2a-testbed manifest spec ./v1/manifest.json --output ./v1/SPEC.md`}
        </pre>
        <p>
          A full step-by-step (Pydantic model authoring, hosting on GitHub Pages, envelope shape,
          optional wire-artefact and invariant metadata) lives in the docs site:
        </p>
        <p>
          <a
            className="btn small"
            href="https://ravikiran438.github.io/agent-protocol-stack/manifest-convention/"
            target="_blank"
            rel="noreferrer"
          >
            Read the full guide ↗
          </a>
        </p>
      </section>

      <section className="generate-manifest">
        <div className="section-head-row">
          <h2>Author an ACS governance manifest</h2>
          <span className="experimental-badge">experimental</span>
        </div>
        <p className="why-lead">
          An Agent Control Specification (ACS) manifest places runtime controls at an agent's
          lifecycle checkpoints. Unlike an extension manifest, there's no <em>generate</em> — a
          manifest is authored governance intent, not a projection of a model. The CLI scaffolds a
          starter, validates it, and renders a plain-English audit summary:
        </p>
        <pre className="how-code">
          {`$ pip install a2a-testbed

# scaffold a starter manifest to edit
$ a2a-testbed acs init --name my-agent -o ./my-agent.acs.yaml

# validate it (structural + semantic checks; --strict for CI)
$ a2a-testbed acs validate ./my-agent.acs.yaml

# render a human-readable governance summary for review/audit
$ a2a-testbed acs spec ./my-agent.acs.yaml -o ./ACS-SUMMARY.md

# apply it to a scenario; --acs-enforce blocks denied handoffs
$ a2a-testbed run --acs ./my-agent.acs.yaml my_scenario.yaml`}
        </pre>
        <p>
          You can also validate a manifest in the browser — switch the Validator tab to{' '}
          <strong>ACS manifest</strong>. Full mapping, intervention points, evidence providers,
          Rego, and fail-closed enforcement are documented in the repo:
        </p>
        <p>
          <a
            className="btn small"
            href="https://github.com/ravikiran438/a2a-testbed/blob/main/docs/ACS.md"
            target="_blank"
            rel="noreferrer"
          >
            Read the ACS guide ↗
          </a>
        </p>
      </section>

      <section className="status">
        <h2>Status</h2>
        <p>
          Alpha. The CLI surface, scenario format, and manifest envelope may change while the
          convention is being explored. Everything in this UI runs entirely in the browser; no data
          leaves your machine except for HTTPS fetches of published manifests.
        </p>
      </section>
    </div>
  );
}
