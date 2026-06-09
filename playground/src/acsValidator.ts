// Browser-side Agent Control Specification (ACS) manifest validator.
//
// Mirrors what `a2a-testbed acs validate` does in Python
// (src/a2a_testbed/acs/manifest.py): parse the manifest YAML, run the
// same structural + semantic checks, and emit the same finding kinds
// with the same verdicts. No backend — pure in-browser, the "online"
// half of the testbed's two-surfaces-one-source-of-truth discipline
// (the CLI is the "offline" half). Keep this in lockstep with the
// Python validator: a check added in one place must be added in both.

import yaml from 'js-yaml';

// The ACS spec revision this validator tracks. Mirrors
// `a2a_testbed.acs.types.ACS_SPEC_VERSION`.
export const ACS_SPEC_VERSION = '0.3.1-beta';

// The eight ACS intervention points. `observable_at_wire` marks the
// subset the testbed can evaluate from an A2A wire exchange alone;
// the two model-call points live inside an agent's process.
const ALL_POINTS = [
  'agent_startup',
  'input',
  'pre_model_call',
  'post_model_call',
  'pre_tool_call',
  'post_tool_call',
  'output',
  'agent_shutdown',
] as const;

const OBSERVABLE_AT_WIRE = new Set<string>([
  'agent_startup',
  'input',
  'pre_tool_call',
  'post_tool_call',
  'output',
  'agent_shutdown',
]);

const BUILTIN_OPS = new Set<string>([
  'equals',
  'not_equals',
  'in',
  'not_in',
  'contains',
  'not_contains',
  'endswith',
  'startswith',
  'exists',
  'absent',
]);

// Finding kinds — identical set + spelling to AcsFindingKind in Python.
export type AcsFindingKind =
  | 'ok'
  | 'error_parse'
  | 'error_schema'
  | 'error_policy_ref'
  | 'error_no_intervention'
  | 'warn_version_mismatch'
  | 'warn_tool_ref'
  | 'warn_rego_backend_required'
  | 'warn_non_observable_point';

export interface AcsFinding {
  kind: AcsFindingKind;
  detail: string;
  locus?: string;
  errors?: string[];
}

export interface AcsValidationResult {
  ok: boolean;
  parsed: boolean;
  findings: AcsFinding[];
}

export function isErrorFinding(kind: AcsFindingKind): boolean {
  return kind.startsWith('error_');
}

export function isWarnFinding(kind: AcsFindingKind): boolean {
  return kind.startsWith('warn_');
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isStr(v: unknown): v is string {
  return typeof v === 'string';
}

function done(parsed: boolean, findings: AcsFinding[]): AcsValidationResult {
  const ok = parsed && !findings.some((f) => isErrorFinding(f.kind));
  return { ok, parsed, findings };
}

/**
 * Validate an ACS manifest string (YAML or JSON). Never throws — every
 * problem becomes a finding, exactly like the Python validator, so the
 * UI can render them all at once.
 */
export function validateAcsManifest(source: string): AcsValidationResult {
  // --- parse ----------------------------------------------------
  let raw: unknown;
  try {
    raw = yaml.load(source);
  } catch (err) {
    return done(false, [{ kind: 'error_parse', detail: (err as Error).message }]);
  }
  if (!isObject(raw)) {
    return done(false, [
      { kind: 'error_parse', detail: 'ACS manifest must be a mapping at the top level' },
    ]);
  }

  // --- structural -----------------------------------------------
  // Collect every shape problem into a single error_schema finding,
  // matching how pydantic aggregates ValidationError in Python.
  const schemaErrors: string[] = [];

  const version = raw.agent_control_specification_version;
  if (version !== undefined && !isStr(version)) {
    schemaErrors.push('agent_control_specification_version: must be a string');
  }

  const policies = raw.policies;
  if (policies !== undefined && !isObject(policies)) {
    schemaErrors.push('policies: must be a mapping');
  } else if (isObject(policies)) {
    for (const [pid, p] of Object.entries(policies)) {
      if (!isObject(p)) {
        schemaErrors.push(`policies/${pid}: must be a mapping`);
        continue;
      }
      const ptype = p.type;
      if (ptype !== undefined && ptype !== 'builtin' && ptype !== 'rego') {
        schemaErrors.push(`policies/${pid}/type: must be 'builtin' or 'rego'`);
      }
      const rules = p.rules;
      if (rules !== undefined && !Array.isArray(rules)) {
        schemaErrors.push(`policies/${pid}/rules: must be a list`);
      } else if (Array.isArray(rules)) {
        rules.forEach((r, i) => {
          if (!isObject(r)) {
            schemaErrors.push(`policies/${pid}/rules/${i}: must be a mapping`);
            return;
          }
          for (const req of ['name', 'field', 'op']) {
            if (!isStr(r[req])) {
              schemaErrors.push(`policies/${pid}/rules/${i}/${req}: required string field`);
            }
          }
          if (isStr(r.op) && !BUILTIN_OPS.has(r.op as string)) {
            schemaErrors.push(`policies/${pid}/rules/${i}/op: unknown op '${r.op}'`);
          }
        });
      }
    }
  }

  const tools = raw.tools;
  if (tools !== undefined && !isObject(tools)) {
    schemaErrors.push('tools: must be a mapping');
  } else if (isObject(tools)) {
    for (const [tid, t] of Object.entries(tools)) {
      if (!isObject(t)) {
        schemaErrors.push(`tools/${tid}: must be a mapping`);
      } else if (!isStr(t.id)) {
        schemaErrors.push(`tools/${tid}/id: required string field`);
      }
    }
  }

  const points = raw.intervention_points;
  if (points !== undefined && !isObject(points)) {
    schemaErrors.push('intervention_points: must be a mapping');
  } else if (isObject(points)) {
    for (const [name, decl] of Object.entries(points)) {
      if (!ALL_POINTS.includes(name as (typeof ALL_POINTS)[number])) {
        schemaErrors.push(`intervention_points/${name}: not a valid ACS intervention point`);
        continue;
      }
      if (!isObject(decl)) {
        schemaErrors.push(`intervention_points/${name}: must be a mapping`);
        continue;
      }
      if (!isStr(decl.policy) || (decl.policy as string).length === 0) {
        schemaErrors.push(`intervention_points/${name}/policy: required non-empty string`);
      }
    }
  }

  if (schemaErrors.length > 0) {
    return done(false, [
      {
        kind: 'error_schema',
        detail: 'manifest failed schema validation',
        errors: schemaErrors,
      },
    ]);
  }

  // At this point the manifest is structurally valid. Treat missing
  // optional containers as empty, mirroring the pydantic defaults.
  const policyMap = isObject(policies) ? policies : {};
  const toolMap = isObject(tools) ? tools : {};
  const pointMap = isObject(points) ? points : {};

  // --- semantic -------------------------------------------------
  const findings: AcsFinding[] = [];

  const declaredVersion = isStr(version) ? version : ACS_SPEC_VERSION;
  if (declaredVersion !== ACS_SPEC_VERSION) {
    findings.push({
      kind: 'warn_version_mismatch',
      detail: `manifest declares ACS '${declaredVersion}'; testbed pins '${ACS_SPEC_VERSION}'`,
    });
  }

  if (Object.keys(pointMap).length === 0) {
    findings.push({
      kind: 'error_no_intervention',
      detail: 'manifest declares no intervention points; nothing to enforce',
    });
  }

  for (const [name, declUnknown] of Object.entries(pointMap)) {
    const decl = declUnknown as Record<string, unknown>;
    const locus = name;
    const policyId = decl.policy as string;

    if (!(policyId in policyMap)) {
      findings.push({
        kind: 'error_policy_ref',
        locus,
        detail: `references undeclared policy '${policyId}'`,
      });
    } else {
      const policy = policyMap[policyId] as Record<string, unknown>;
      if (policy.type === 'rego') {
        findings.push({
          kind: 'warn_rego_backend_required',
          locus,
          detail:
            `policy '${policyId}' is type 'rego'; needs an external OPA / ACS ` +
            'SDK backend registered on the evaluator, else it fails closed',
        });
      }
    }

    if (!OBSERVABLE_AT_WIRE.has(name)) {
      findings.push({
        kind: 'warn_non_observable_point',
        locus,
        detail:
          "model-call points aren't observable at the A2A wire seam; the " +
          'agent must emit this snapshot itself',
      });
    }

    if (isStr(decl.tool_name_from) && Object.keys(toolMap).length === 0) {
      findings.push({
        kind: 'warn_tool_ref',
        locus,
        detail:
          'declares tool_name_from but the manifest has no tools; tool ' +
          'metadata will be absent from the canonical input',
      });
    }
  }

  if (findings.length === 0) {
    findings.push({
      kind: 'ok',
      detail:
        `manifest valid: ${Object.keys(pointMap).length} intervention point(s), ` +
        `${Object.keys(policyMap).length} policy(ies)`,
    });
  }

  return done(true, findings);
}
