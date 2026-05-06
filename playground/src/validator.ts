// Browser-side AgentCard validator.
//
// Mirrors what `a2a-testbed validate` does in Python: for each entry
// in `capabilities.extensions[]`, fetch `<uri>/manifest.json`, parse
// the contained JSON Schema, and validate the entry's `params`
// payload. No backend required — works against any manifest hosted at
// a CORS-friendly URL (GitHub Pages serves the headers we need).

import Ajv, { type ErrorObject } from 'ajv';
import addFormats from 'ajv-formats';

export type FindingKind =
  | 'declared_ok'
  | 'declared_invalid'
  | 'manifest_unreachable'
  | 'manifest_malformed'
  | 'no_payload';

export interface Finding {
  uri: string;
  kind: FindingKind;
  detail: string;
  errors?: ErrorObject[];
  manifestName?: string;
  manifestVersion?: string;
}

interface AgentCardLike {
  capabilities?: {
    extensions?: Array<{
      uri: string;
      params?: unknown;
      payload?: unknown;
      [key: string]: unknown;
    }>;
  };
}

// Minimal ExtensionManifest envelope shape we read from the wire.
// Mirrors a2a_testbed.manifest.types.ExtensionManifest; only the
// fields we actually use are typed here.
interface ManifestEnvelope {
  manifest_version: string;
  extension: {
    uri: string;
    name: string;
    version: string;
  };
  agent_card_payload_schema?: Record<string, unknown>;
}

const ajv = new Ajv({
  strict: false, // protocol manifests use vendor keywords; don't fail on them
  allErrors: true,
  coerceTypes: false,
});
addFormats(ajv);

// Cache fetched manifests so re-validating the same card doesn't
// re-fetch the same URL.
const manifestCache = new Map<string, ManifestEnvelope>();

function manifestUrlForUri(uri: string): string {
  return uri.endsWith('/') ? `${uri}manifest.json` : `${uri}/manifest.json`;
}

async function loadManifest(uri: string): Promise<ManifestEnvelope> {
  const cached = manifestCache.get(uri);
  if (cached) return cached;

  const url = manifestUrlForUri(uri);
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText} for ${url}`);
  }
  const json = (await res.json()) as ManifestEnvelope;
  if (!json.extension || !json.extension.uri) {
    throw new Error('manifest missing required `extension.uri` field');
  }
  manifestCache.set(uri, json);
  return json;
}

function extractParams(entry: { params?: unknown; payload?: unknown }): unknown {
  if (entry.params !== undefined) return entry.params;
  if (entry.payload !== undefined) return entry.payload;
  // Tolerate the convention where params live as siblings of `uri`.
  const reserved = new Set(['uri', 'description', 'required']);
  const extras: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entry)) {
    if (!reserved.has(k)) extras[k] = v;
  }
  return Object.keys(extras).length ? extras : undefined;
}

export async function validateAgentCard(
  card: AgentCardLike
): Promise<Finding[]> {
  const extensions = card.capabilities?.extensions ?? [];
  if (extensions.length === 0) {
    return [];
  }

  const findings: Finding[] = [];

  for (const entry of extensions) {
    const uri = entry.uri;
    if (!uri) {
      findings.push({
        uri: '(missing)',
        kind: 'manifest_malformed',
        detail: 'extension entry has no uri field',
      });
      continue;
    }

    let manifest: ManifestEnvelope;
    try {
      manifest = await loadManifest(uri);
    } catch (err) {
      findings.push({
        uri,
        kind: 'manifest_unreachable',
        detail: `could not fetch manifest: ${(err as Error).message}`,
      });
      continue;
    }

    const params = extractParams(entry);
    if (params === undefined) {
      findings.push({
        uri,
        kind: 'no_payload',
        detail: 'extension entry has no params payload to validate',
        manifestName: manifest.extension.name,
        manifestVersion: manifest.extension.version,
      });
      continue;
    }

    const schema = manifest.agent_card_payload_schema;
    if (!schema) {
      findings.push({
        uri,
        kind: 'declared_ok',
        detail:
          'manifest declares no payload schema; entry treated as opaque',
        manifestName: manifest.extension.name,
        manifestVersion: manifest.extension.version,
      });
      continue;
    }

    const validate = ajv.compile(schema);
    const ok = validate(params);
    if (ok) {
      findings.push({
        uri,
        kind: 'declared_ok',
        detail: `payload conforms to ${manifest.extension.name} v${manifest.extension.version}`,
        manifestName: manifest.extension.name,
        manifestVersion: manifest.extension.version,
      });
    } else {
      findings.push({
        uri,
        kind: 'declared_invalid',
        detail: 'payload failed JSON Schema validation',
        errors: validate.errors ?? [],
        manifestName: manifest.extension.name,
        manifestVersion: manifest.extension.version,
      });
    }
  }

  return findings;
}
