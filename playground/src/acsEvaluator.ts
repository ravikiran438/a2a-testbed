// Browser-side ACS evaluator — mirrors evaluator.py + canonical.py.
//
// Computes intervention-point verdicts from a wire exchange, with the
// same builtin rule engine, the same canonical-input shaping, and the
// same fail-closed semantics as the Python evaluator. Keep in lockstep:
// a behavior change in one must land in both (two-surfaces parity).
//
// Rego policies require an external backend the browser doesn't have, so
// they fail closed (deny) here — the safe default for a control layer.

export type Decision = 'allow' | 'warn' | 'deny' | 'escalate';

export interface Verdict {
  decision: Decision;
  intervention_point: string;
  policy_id?: string | null;
  reasons: string[];
  rule_name?: string | null;
  failed_closed: boolean;
}

/** A minimal wire exchange — the playground's synthetic equivalent of
 *  core.observer.WireExchange. */
export interface WireExchange {
  receiver_id: string;
  request_body: Record<string, unknown>;
  response_body: Record<string, unknown>;
}

const MISSING = Symbol('missing');

export function resolvePath(data: unknown, path: string): unknown {
  if (path === '' || path === '$' || path === '$.') return data;
  let cleaned = path.startsWith('$.') ? path.slice(2) : path;
  cleaned = cleaned.replace(/^[$.]+/, '');
  let cur: unknown = data;
  for (const seg of cleaned.split('.')) {
    if (seg === '') continue;
    if (Array.isArray(cur)) {
      const idx = Number(seg);
      if (!Number.isInteger(idx) || idx < 0 || idx >= cur.length) return MISSING;
      cur = cur[idx];
    } else if (cur !== null && typeof cur === 'object') {
      const obj = cur as Record<string, unknown>;
      if (!(seg in obj)) return MISSING;
      cur = obj[seg];
    } else {
      return MISSING;
    }
  }
  return cur;
}

interface ToolDecl {
  id: string;
  clearance?: string | null;
  security_labels?: string[];
}

export function snapshotFor(point: string, exchange: WireExchange): Record<string, unknown> {
  const req = exchange.request_body ?? {};
  const resp = exchange.response_body ?? {};
  const params =
    req && typeof req === 'object' ? ((req as Record<string, unknown>).params ?? {}) : {};

  const snap: Record<string, unknown> = {
    receiver: exchange.receiver_id,
    request: req,
    response: resp,
    extras: {},
  };

  if (point === 'input') {
    snap.input = { method: (req as Record<string, unknown>).method, params };
  } else if (point === 'output') {
    snap.output = (resp as Record<string, unknown>).result ?? resp;
  } else if (point === 'pre_tool_call' || point === 'post_tool_call') {
    const toolCall: Record<string, unknown> = {
      name: exchange.receiver_id,
      method: (req as Record<string, unknown>).method,
      args: params,
    };
    if (point === 'post_tool_call') {
      toolCall.result = (resp as Record<string, unknown>).result ?? resp;
    }
    snap.tool_call = toolCall;
  }
  return snap;
}

function toolMetadata(
  name: unknown,
  tools: Record<string, ToolDecl> | undefined,
): Record<string, unknown> | null {
  if (typeof name !== 'string' || !tools || !(name in tools)) return null;
  const decl = tools[name];
  return {
    name: decl.id,
    clearance: decl.clearance ?? null,
    security_labels: [...(decl.security_labels ?? [])],
  };
}

interface CanonicalInput {
  intervention_point: string;
  policy_target: { kind: string; path: string; value: unknown };
  snapshot: Record<string, unknown>;
  annotations: Record<string, unknown>;
  tool: Record<string, unknown> | null;
}

export function buildCanonicalInput(
  point: string,
  snapshot: Record<string, unknown>,
  opts: {
    policyTargetPath?: string;
    policyTargetKind?: string;
    toolNameFrom?: string | null;
    tools?: Record<string, ToolDecl>;
    annotations?: Record<string, unknown>;
  } = {},
): CanonicalInput {
  const path = opts.policyTargetPath ?? '$';
  const rawTarget = resolvePath(snapshot, path);
  const targetValue = rawTarget === MISSING ? null : rawTarget;

  let toolName: unknown = null;
  if (opts.toolNameFrom) {
    const resolved = resolvePath(snapshot, opts.toolNameFrom);
    if (resolved !== MISSING) toolName = resolved;
  }

  return {
    intervention_point: point,
    policy_target: { kind: opts.policyTargetKind ?? 'snapshot', path, value: targetValue },
    snapshot,
    annotations: { ...(opts.annotations ?? {}) },
    tool: toolMetadata(toolName, opts.tools),
  };
}

// --- builtin engine -------------------------------------------------

type Op = (a: unknown, b: unknown) => boolean;
const OPS: Record<string, Op> = {
  equals: (a, b) => a === b,
  not_equals: (a, b) => a !== b,
  in: (a, b) =>
    Array.isArray(b) || typeof b === 'string' ? (b as unknown[]).includes(a as never) : false,
  not_in: (a, b) =>
    Array.isArray(b) || typeof b === 'string' ? !(b as unknown[]).includes(a as never) : true,
  contains: (a, b) =>
    Array.isArray(a)
      ? a.includes(b as never)
      : typeof a === 'string'
        ? a.includes(String(b))
        : false,
  not_contains: (a, b) =>
    Array.isArray(a)
      ? !a.includes(b as never)
      : typeof a === 'string'
        ? !a.includes(String(b))
        : true,
  endswith: (a, b) => typeof a === 'string' && a.endsWith(String(b)),
  startswith: (a, b) => typeof a === 'string' && a.startsWith(String(b)),
  exists: (a) => a !== MISSING,
  absent: (a) => a === MISSING,
};

interface BuiltinRule {
  name: string;
  field: string;
  op: string;
  value?: unknown;
  decision?: Decision;
  description?: string;
}

interface PolicyDecl {
  type?: 'builtin' | 'rego';
  rules?: BuiltinRule[];
  default_decision?: Decision;
}

interface InterventionDecl {
  policy: string;
  policy_target?: string;
  policy_target_kind?: string;
  tool_name_from?: string | null;
  evidence?: string[];
}

export interface AcsManifestObj {
  agent_control_specification_version?: string;
  policies?: Record<string, PolicyDecl>;
  intervention_points?: Record<string, InterventionDecl>;
  tools?: Record<string, ToolDecl>;
}

function evalRule(rule: BuiltinRule, canonical: CanonicalInput): boolean {
  const op = OPS[rule.op];
  if (!op) throw new Error(`unknown builtin op: ${rule.op}`);
  const actual = resolvePath(canonical as unknown as Record<string, unknown>, rule.field);
  if (rule.op === 'exists' || rule.op === 'absent') return op(actual, null);
  if (actual === MISSING) return false;
  return op(actual, rule.value);
}

function builtinBackend(policy: PolicyDecl, canonical: CanonicalInput): Verdict {
  for (const rule of policy.rules ?? []) {
    if (evalRule(rule, canonical)) {
      return {
        decision: rule.decision ?? 'deny',
        intervention_point: canonical.intervention_point,
        reasons: [rule.description || `matched rule '${rule.name}'`],
        rule_name: rule.name,
        failed_closed: false,
      };
    }
  }
  return {
    decision: policy.default_decision ?? 'allow',
    intervention_point: canonical.intervention_point,
    reasons: ['no rule matched; applied default decision'],
    failed_closed: false,
  };
}

export type EvidenceProvider = (canonical: CanonicalInput) => Record<string, unknown>;

export class AcsEvaluator {
  private failClosed: boolean;
  private evidence = new Map<string, EvidenceProvider>();

  constructor(opts: { failClosed?: boolean } = {}) {
    this.failClosed = opts.failClosed ?? true;
  }

  registerEvidence(id: string, provider: EvidenceProvider): void {
    this.evidence.set(id, provider);
  }

  private denyClosed(point: string, reason: string): Verdict {
    return {
      decision: 'deny',
      intervention_point: point,
      reasons: [`fail-closed: ${reason}`],
      failed_closed: true,
    };
  }

  evaluate(manifest: AcsManifestObj, point: string, snapshot: Record<string, unknown>): Verdict {
    const decl = manifest.intervention_points?.[point];
    if (!decl) {
      return {
        decision: 'allow',
        intervention_point: point,
        reasons: ['no intervention point configured'],
        failed_closed: false,
      };
    }
    const policy = manifest.policies?.[decl.policy];
    if (!policy) {
      return this.denyClosed(point, `policy id '${decl.policy}' not found in manifest`);
    }

    const canonical = buildCanonicalInput(point, snapshot, {
      policyTargetPath: decl.policy_target,
      policyTargetKind: decl.policy_target_kind,
      toolNameFrom: decl.tool_name_from,
      tools: manifest.tools,
    });

    // Evidence — any failure denies.
    const annotations: Record<string, unknown> = {};
    for (const evId of decl.evidence ?? []) {
      const provider = this.evidence.get(evId);
      if (!provider) {
        if (this.failClosed) return this.denyClosed(point, `evidence provider '${evId}' missing`);
        continue;
      }
      try {
        Object.assign(annotations, provider(canonical));
      } catch (err) {
        if (this.failClosed)
          return this.denyClosed(point, `evidence '${evId}' raised: ${(err as Error).message}`);
      }
    }
    canonical.annotations = annotations;

    // Policy dispatch — rego needs a backend we don't have in-browser.
    if (policy.type === 'rego') {
      return this.denyClosed(point, "no backend registered for policy type 'rego'");
    }
    try {
      const verdict = builtinBackend(policy, canonical);
      verdict.policy_id = decl.policy;
      return verdict;
    } catch (err) {
      if (this.failClosed)
        return this.denyClosed(point, `policy backend raised: ${(err as Error).message}`);
      throw err;
    }
  }
}

/** Build the synthetic A2A request payload a playground step would send,
 *  matching the Python transport's encode_request shape so snapshots
 *  resolve identically. */
export function stepRequestPayload(message: string): Record<string, unknown> {
  return {
    jsonrpc: '2.0',
    method: 'message/send',
    params: {
      message: {
        role: 'user',
        parts: [{ kind: 'text', text: message }],
      },
      configuration: { blocking: true },
    },
  };
}

/** Which intervention points the testbed evaluates per step. */
export const PER_STEP_POINTS = ['input', 'pre_tool_call', 'post_tool_call', 'output'];

/** Request-side points, evaluated before dispatch (enforce can block here). */
export const PRE_POINTS = ['input', 'pre_tool_call'];

/** Response-side points, evaluated after dispatch against the real response. */
export const POST_POINTS = ['post_tool_call', 'output'];
