// Hardcoded three-party guardian-mediated consent scenario.
//
// One agent per AgentCard; one entry per scenario step. The runtime
// in App.tsx walks the steps in order, animating the canvas edge
// between `from` and `to` as each step fires. Sample extension URIs
// reference real manifests so the scenario stays consistent with the
// playground's "Validate AgentCard" mode, but the prose stays
// protocol-agnostic — anyone reading the canvas should understand
// the flow without knowing which protocols those URIs back.

export interface AgentCard {
  name: string;
  description: string;
  url: string;
  version: string;
  capabilities: {
    streaming: boolean;
    extensions: Array<{
      uri: string;
      description: string;
      required?: boolean;
    }>;
  };
  skills: Array<{
    id: string;
    name: string;
    description: string;
    tags: string[];
  }>;
}

// Four sample extension URIs. The playground fetches and validates
// against the manifests at these URIs in "Validate AgentCard" mode;
// the canvas mode just renders them as opaque protocol identifiers.
const EXT_URIS = {
  consent: 'https://ravikiran438.github.io/agent-consent-protocol/v1',
  welfare: 'https://ravikiran438.github.io/phala-protocol/v1',
  integrity: 'https://ravikiran438.github.io/pratyahara-nerve/v1',
  accessibility: 'https://ravikiran438.github.io/sauvidya-pace/v1',
};

export const agentCards: Record<string, AgentCard> = {
  alice: {
    name: 'Alice (principal)',
    description:
      'Principal whose consent decisions delegate to a guardian.',
    url: 'https://example.com/alice',
    version: '1.0.0',
    capabilities: {
      streaming: false,
      extensions: [
        { uri: EXT_URIS.accessibility, description: 'Sample extension declaration.', required: true },
        { uri: EXT_URIS.consent, description: 'Sample extension declaration.', required: true },
      ],
    },
    skills: [
      {
        id: 'receive_request',
        name: 'Receive incoming requests',
        description: 'Accept service requests.',
        tags: ['principal'],
      },
    ],
  },
  bob: {
    name: 'Bob (guardian)',
    description:
      'Guardian agent holding delegated authority over the principal.',
    url: 'https://example.com/bob',
    version: '1.0.0',
    capabilities: {
      streaming: false,
      extensions: [
        { uri: EXT_URIS.consent, description: 'Sample extension declaration.', required: true },
      ],
    },
    skills: [
      {
        id: 'grant_consent',
        name: 'Grant or deny consent',
        description: 'Decide on requests on behalf of the principal.',
        tags: ['guardian'],
      },
    ],
  },
  carol: {
    name: 'Carol (service provider)',
    description: 'Service agent that initiates and fulfils requests.',
    url: 'https://example.com/carol',
    version: '1.0.0',
    capabilities: {
      streaming: false,
      extensions: [
        { uri: EXT_URIS.consent, description: 'Sample extension declaration.', required: true },
        { uri: EXT_URIS.welfare, description: 'Sample extension declaration.', required: false },
      ],
    },
    skills: [
      {
        id: 'request_service',
        name: 'Request service',
        description: 'Submit a service offer to a principal.',
        tags: ['service'],
      },
    ],
  },
  observer: {
    name: 'Observer (integrity)',
    description: 'Observer monitoring the conversation across the cohort.',
    url: 'https://example.com/observer',
    version: '1.0.0',
    capabilities: {
      streaming: true,
      extensions: [
        { uri: EXT_URIS.integrity, description: 'Sample extension declaration.', required: true },
      ],
    },
    skills: [
      {
        id: 'evaluate',
        name: 'Evaluate behavior',
        description: 'Compare observed behavior against the published baseline.',
        tags: ['observer'],
      },
    ],
  },
};

export interface ScenarioStep {
  from: string;
  to: string;
  action: string;
  // Neutral identifier the inspector renders; the canvas does not
  // dispatch on this value.
  extension_uri: string;
  outcome: 'ok' | 'fail';
  duration_ms: number;
  message: Record<string, unknown>;
  /** YAML-declared expectations from the original scenario file.
   *  Read-only in the browser; the CLI runner enforces these. Set
   *  when loading a custom scenario; the bundled hardcoded scenario
   *  doesn't carry expectations. */
  expect?: Record<string, unknown>;
  /** Real validation finding. Set on bundled scenario steps where
   *  we hand-author an outcome; omitted on custom-loaded scenarios
   *  because the browser doesn't actually validate anything. */
  validation?: {
    finding: 'declared_ok' | 'declared_invalid';
    detail: string;
  };
}

export interface Scenario {
  name: string;
  description: string;
  steps: ScenarioStep[];
}

export const scenario: Scenario = {
  name: 'Three-party guardian-mediated consent',
  description:
    'A service agent requests authorization from a principal whose ' +
    'consent decisions delegate to a guardian. An observer attests to ' +
    'integrity throughout.',
  steps: [
    {
      from: 'carol',
      to: 'alice',
      action: 'request_consent',
      extension_uri: EXT_URIS.consent,
      outcome: 'ok',
      duration_ms: 1100,
      message: {
        kind: 'a2a.task',
        task_id: 'task-001',
        from_agent: 'carol',
        to_agent: 'alice',
        skill: 'receive_request',
        payload: { service: 'service_request', options_count: 3 },
      },
      validation: {
        finding: 'declared_ok',
        detail:
          "Card's declared extension entry matches the schema published " +
          'at the extension URI.',
      },
    },
    {
      from: 'alice',
      to: 'bob',
      action: 'escalate_to_guardian',
      extension_uri: EXT_URIS.accessibility,
      outcome: 'ok',
      duration_ms: 950,
      message: {
        kind: 'capacity_check',
        principal_id: 'alice',
        recommendation: 'escalate',
        guardian_id: 'bob',
      },
      validation: {
        finding: 'declared_ok',
        detail:
          'Capacity check signals the principal cannot self-consent; ' +
          'request escalates to the guardian.',
      },
    },
    {
      from: 'bob',
      to: 'carol',
      action: 'grant_consent',
      extension_uri: EXT_URIS.consent,
      outcome: 'ok',
      duration_ms: 850,
      message: {
        kind: 'consent_record',
        record_id: 'cr-1042',
        principal_id: 'alice',
        consenting_agent: 'bob',
        decision: 'accepted',
        binding_authority: 'guardian',
      },
      validation: {
        finding: 'declared_ok',
        detail:
          'Consent record links to the principal and is signed by the ' +
          'guardian carrying delegated authority.',
      },
    },
    {
      from: 'observer',
      to: 'carol',
      action: 'attest_integrity',
      extension_uri: EXT_URIS.integrity,
      outcome: 'ok',
      duration_ms: 700,
      message: {
        kind: 'integrity_observation',
        observer_id: 'observer',
        target_agent: 'carol',
        behavioral_fingerprint: 'sha256:7f2c…',
        drift_detected: false,
      },
      validation: {
        finding: 'declared_ok',
        detail:
          'Observed behavior matches the published baseline; no drift ' +
          'flagged.',
      },
    },
  ],
};
