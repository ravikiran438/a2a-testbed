// AgentCard structural & discovery contracts. These verify the
// shape and contents of the JSON returned at
// `/.well-known/agent-card.json` — they don't exercise any wire
// behavior beyond the GET. Each maps to the Python contract module
// of the same name; spec citations align so reports compare
// apples-to-apples across surfaces.

import { assert, fetchCard } from '../transport';
import type { Contract } from '../types';

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '0.0.0.0']);

function isLocal(url: string): boolean {
  try {
    return LOCAL_HOSTS.has(new URL(url).hostname);
  } catch {
    return false;
  }
}

function isAbsoluteUrl(value: unknown): value is string {
  if (typeof value !== 'string' || !value) return false;
  try {
    const u = new URL(value);
    return Boolean(u.protocol) && Boolean(u.host);
  } catch {
    return false;
  }
}

export const wellKnownCard: Contract = {
  id: 'transport.well_known_card',
  specSection: '§8.2',
  description: 'GET /.well-known/agent-card.json returns 200 + parseable card.',
  category: 'transport',
  async verify(agentUrl) {
    const { status, body } = await fetchCard(agentUrl);
    assert(
      status === 200,
      `well-known card endpoint returned ${status}, expected 200`,
    );
    assert(
      body && typeof body === 'object',
      'card body did not parse as a JSON object',
    );
    const card = body as Record<string, unknown>;
    assert(
      typeof card.name === 'string' && card.name,
      'card.name is missing or empty',
    );
  },
};

export const agentCardRequiredFields: Contract = {
  id: 'transport.agent_card_required_fields',
  specSection: '§4.4.1',
  description: 'AgentCard carries every REQUIRED field per A2A 1.0 §4.4.1 + §8.1.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    assert(body && typeof body === 'object', 'card is not an object');
    const card = body as Record<string, unknown>;

    for (const field of ['name', 'description', 'version']) {
      const v = card[field];
      assert(
        typeof v === 'string' && v,
        `${field} is REQUIRED but missing/empty`,
      );
    }
    const interfaces = card.supportedInterfaces;
    assert(
      Array.isArray(interfaces) && interfaces.length >= 1,
      'supportedInterfaces MUST have ≥1 entry',
    );
    const skills = card.skills;
    assert(
      Array.isArray(skills) && skills.length >= 1,
      'skills MUST have ≥1 entry',
    );
    const inputs = card.defaultInputModes;
    assert(
      Array.isArray(inputs) && inputs.length >= 1,
      'defaultInputModes MUST have ≥1 entry',
    );
    const outputs = card.defaultOutputModes;
    assert(
      Array.isArray(outputs) && outputs.length >= 1,
      'defaultOutputModes MUST have ≥1 entry',
    );
    assert(
      card.capabilities && typeof card.capabilities === 'object',
      'capabilities object is REQUIRED on the AgentCard',
    );
  },
};

export const agentCardSkillAttributes: Contract = {
  id: 'transport.agent_card_skill_attributes',
  specSection: '§4.4.1',
  description: 'Each skill carries id, name, description, tags.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const skills = (body as { skills?: unknown }).skills;
    assert(Array.isArray(skills), 'skills MUST be an array');
    skills.forEach((s, i) => {
      assert(s && typeof s === 'object', `skills[${i}] MUST be an object`);
      const sk = s as Record<string, unknown>;
      assert(
        typeof sk.id === 'string' && sk.id,
        `skills[${i}].id REQUIRED, non-empty string`,
      );
      assert(
        typeof sk.name === 'string' && sk.name,
        `skills[${i}].name REQUIRED, non-empty string`,
      );
      assert(
        typeof sk.description === 'string' && sk.description,
        `skills[${i}].description REQUIRED, non-empty string`,
      );
      assert(
        Array.isArray(sk.tags),
        `skills[${i}].tags REQUIRED, array (may be empty)`,
      );
    });
  },
};

export const agentCardSkillIdUnique: Contract = {
  id: 'transport.agent_card_skill_id_unique',
  specSection: '§4.4.1',
  description: 'AgentCard.skills[*].id values are unique within the card.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const skills = (body as { skills?: unknown }).skills;
    if (!Array.isArray(skills)) return;
    const seen = new Map<string, number>();
    for (const s of skills) {
      const id = (s as { id?: unknown })?.id;
      if (typeof id !== 'string' || !id) continue;
      seen.set(id, (seen.get(id) ?? 0) + 1);
    }
    const duplicates = [...seen.entries()]
      .filter(([, n]) => n > 1)
      .map(([id]) => id)
      .sort();
    assert(
      duplicates.length === 0,
      `duplicate skill ids on AgentCard: ${duplicates.join(', ')}`,
    );
  },
};

export const agentCardCapabilitiesObject: Contract = {
  id: 'transport.agent_card_capabilities_object',
  specSection: '§4.4.1',
  description: 'AgentCard.capabilities is a well-formed object.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const caps = (body as { capabilities?: unknown }).capabilities;
    assert(
      caps && typeof caps === 'object' && !Array.isArray(caps),
      'capabilities MUST be a JSON object',
    );
    const c = caps as Record<string, unknown>;
    for (const f of ['streaming', 'pushNotifications', 'extendedAgentCard']) {
      if (f in c) {
        assert(
          typeof c[f] === 'boolean',
          `capabilities.${f} MUST be a boolean if present`,
        );
      }
    }
    if (c.extensions !== undefined) {
      assert(
        Array.isArray(c.extensions),
        'capabilities.extensions MUST be a JSON array if present',
      );
      (c.extensions as unknown[]).forEach((ext, i) => {
        assert(
          ext && typeof ext === 'object',
          `extensions[${i}] MUST be an object`,
        );
        const e = ext as Record<string, unknown>;
        assert(
          typeof e.uri === 'string' && e.uri,
          `extensions[${i}].uri REQUIRED`,
        );
      });
    }
  },
};

export const agentCardSupportedInterfaces: Contract = {
  id: 'transport.agent_card_supported_interfaces',
  specSection: '§8.3.1',
  description: 'supportedInterfaces[*] each have protocolBinding + url.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const interfaces = (body as { supportedInterfaces?: unknown })
      .supportedInterfaces;
    assert(
      Array.isArray(interfaces),
      'supportedInterfaces MUST be an array',
    );
    interfaces.forEach((entry, i) => {
      assert(
        entry && typeof entry === 'object',
        `supportedInterfaces[${i}] MUST be an object`,
      );
      const e = entry as Record<string, unknown>;
      assert(
        typeof e.protocolBinding === 'string' && e.protocolBinding,
        `supportedInterfaces[${i}].protocolBinding REQUIRED`,
      );
      assert(
        typeof e.url === 'string' && e.url,
        `supportedInterfaces[${i}].url REQUIRED`,
      );
    });
  },
};

export const agentCardPreferredInterface: Contract = {
  id: 'transport.agent_card_preferred_interface',
  specSection: '§8.3.1',
  description: 'supportedInterfaces[0] is well-formed (preferred interface).',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const interfaces = (body as { supportedInterfaces?: unknown })
      .supportedInterfaces;
    assert(
      Array.isArray(interfaces) && interfaces.length > 0,
      'supportedInterfaces MUST be a non-empty array',
    );
    const preferred = interfaces[0] as Record<string, unknown>;
    assert(
      typeof preferred.url === 'string' && preferred.url,
      'supportedInterfaces[0].url REQUIRED on preferred interface',
    );
    assert(
      typeof preferred.protocolBinding === 'string' && preferred.protocolBinding,
      'supportedInterfaces[0].protocolBinding REQUIRED on preferred interface',
    );
  },
};

export const agentCardUrlWellFormed: Contract = {
  id: 'transport.agent_card_url_well_formed',
  specSection: '§4.4.1',
  description: 'AgentCard URLs are absolute parseable URLs.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const card = body as Record<string, unknown>;
    const offenders: string[] = [];
    for (const f of ['url', 'documentationUrl', 'iconUrl']) {
      const v = card[f];
      if (v != null && !isAbsoluteUrl(v)) {
        offenders.push(`${f}=${JSON.stringify(v)} is not an absolute URL`);
      }
    }
    const provider = card.provider as Record<string, unknown> | undefined;
    if (provider?.url != null && !isAbsoluteUrl(provider.url)) {
      offenders.push(
        `provider.url=${JSON.stringify(provider.url)} is not absolute`,
      );
    }
    const interfaces = card.supportedInterfaces;
    if (Array.isArray(interfaces)) {
      interfaces.forEach((entry, i) => {
        const u = (entry as Record<string, unknown>)?.url;
        if (u != null && !isAbsoluteUrl(u)) {
          offenders.push(
            `supportedInterfaces[${i}].url=${JSON.stringify(u)} is not absolute`,
          );
        }
      });
    }
    assert(offenders.length === 0, offenders.join('; '));
  },
};

export const agentCardHttpsUrls: Contract = {
  id: 'transport.agent_card_https_urls',
  specSection: '§7.1',
  description: 'Non-loopback supportedInterfaces URLs use HTTPS/WSS.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const interfaces = (body as { supportedInterfaces?: unknown })
      .supportedInterfaces;
    if (!Array.isArray(interfaces)) return;
    const offenders: string[] = [];
    interfaces.forEach((entry, i) => {
      const e = entry as Record<string, unknown>;
      const url = e.url;
      const binding = (e.protocolBinding as string | undefined) ?? '?';
      if (typeof url !== 'string' || !url) return;
      if (isLocal(url)) return;
      // gRPC declares TLS via its own scheme.
      if (binding.toUpperCase() === 'GRPC') return;
      let scheme = '';
      try {
        scheme = new URL(url).protocol.replace(':', '').toLowerCase();
      } catch {
        scheme = '';
      }
      if (scheme !== 'https' && scheme !== 'wss') {
        offenders.push(
          `supportedInterfaces[${i}] (${binding}) url ${url} uses ${scheme || '?'}`,
        );
      }
    });
    assert(
      offenders.length === 0,
      `production MUST use https/wss: ${offenders.join('; ')}`,
    );
  },
};

export const agentCardSecuritySchemes: Contract = {
  id: 'transport.agent_card_security_schemes',
  specSection: '§7.3',
  description: 'Declared securitySchemes use recognized OpenAPI types.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const schemes = (body as { securitySchemes?: unknown }).securitySchemes;
    if (schemes == null) return;
    assert(
      typeof schemes === 'object' && !Array.isArray(schemes),
      'securitySchemes MUST be an object keyed by scheme name',
    );
    const recognized = new Set([
      'apiKey', 'http', 'oauth2', 'openIdConnect', 'mutualTLS',
    ]);
    for (const [name, spec] of Object.entries(
      schemes as Record<string, unknown>,
    )) {
      assert(
        spec && typeof spec === 'object',
        `securitySchemes[${JSON.stringify(name)}] MUST be an object`,
      );
      const kind = (spec as { type?: unknown }).type;
      assert(
        typeof kind === 'string' && recognized.has(kind),
        `securitySchemes[${JSON.stringify(name)}].type ${JSON.stringify(kind)} is not a recognized OpenAPI scheme`,
      );
    }
  },
};

export const providerWellFormed: Contract = {
  id: 'transport.provider_well_formed',
  specSection: '§4.4.1',
  description:
    'AgentCard.provider object (when present) carries organization + valid URL.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const provider = (body as { provider?: unknown }).provider;
    if (provider == null) return;
    assert(
      typeof provider === 'object' && !Array.isArray(provider),
      'provider MUST be a JSON object when present',
    );
    const p = provider as Record<string, unknown>;
    assert(
      typeof p.organization === 'string' && p.organization,
      'provider.organization is REQUIRED when provider is present',
    );
    if (p.url != null) {
      assert(
        typeof p.url === 'string' && p.url && isAbsoluteUrl(p.url),
        `provider.url ${JSON.stringify(p.url)} MUST be an absolute URL`,
      );
    }
  },
};

export const defaultModesDistinct: Contract = {
  id: 'transport.default_modes_distinct',
  specSection: '§4.4.1',
  description:
    'defaultInputModes / defaultOutputModes contain no duplicate values.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const card = body as Record<string, unknown>;
    const offenders: string[] = [];
    for (const field of ['defaultInputModes', 'defaultOutputModes']) {
      const modes = card[field];
      if (!Array.isArray(modes)) continue;
      const seen = new Map<string, number>();
      for (const m of modes) {
        if (typeof m !== 'string') continue;
        seen.set(m, (seen.get(m) ?? 0) + 1);
      }
      const dups = [...seen.entries()]
        .filter(([, n]) => n > 1)
        .map(([m]) => m)
        .sort();
      if (dups.length > 0) {
        offenders.push(`${field} has duplicates: ${dups.join(', ')}`);
      }
    }
    assert(offenders.length === 0, offenders.join('; '));
  },
};

export const extensionsUriAbsolute: Contract = {
  id: 'transport.extensions_uri_absolute',
  specSection: '§4.4.4',
  description:
    'capabilities.extensions[*].uri values are absolute HTTP(S) URLs.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const exts =
      (body as { capabilities?: { extensions?: unknown } })?.capabilities
        ?.extensions ?? [];
    if (!Array.isArray(exts)) return;
    const offenders: string[] = [];
    exts.forEach((ext, i) => {
      const uri = (ext as Record<string, unknown>)?.uri;
      if (typeof uri !== 'string' || !uri) return;
      let scheme = '';
      let host = '';
      try {
        const u = new URL(uri);
        scheme = u.protocol.replace(':', '').toLowerCase();
        host = u.host;
      } catch {
        /* leave empty */
      }
      if ((scheme !== 'http' && scheme !== 'https') || !host) {
        offenders.push(
          `extensions[${i}].uri ${JSON.stringify(uri)} is not an absolute http(s) URL`,
        );
      }
    });
    assert(offenders.length === 0, offenders.join('; '));
  },
};

export const extensionsUriUnique: Contract = {
  id: 'transport.extensions_uri_unique',
  specSection: '§4.4.4',
  description:
    'capabilities.extensions[*].uri values are unique within the card.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const exts =
      (body as { capabilities?: { extensions?: unknown } })?.capabilities
        ?.extensions ?? [];
    if (!Array.isArray(exts)) return;
    const seen = new Map<string, number>();
    for (const ext of exts) {
      const uri = (ext as Record<string, unknown>)?.uri;
      if (typeof uri !== 'string' || !uri) continue;
      seen.set(uri, (seen.get(uri) ?? 0) + 1);
    }
    const dups = [...seen.entries()]
      .filter(([, n]) => n > 1)
      .map(([u]) => u)
      .sort();
    assert(
      dups.length === 0,
      `duplicate extension URIs on AgentCard: ${dups.join(', ')}`,
    );
  },
};

const BASE64URL = /^[A-Za-z0-9_-]+=*$/;

export const signaturesWellFormed: Contract = {
  id: 'transport.signatures_well_formed',
  specSection: '§4.4',
  description:
    'AgentCard.signatures (when present) are well-formed JWS entries.',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const sigs = (body as { signatures?: unknown }).signatures;
    if (sigs == null) return;
    assert(
      Array.isArray(sigs),
      `signatures MUST be an array when present`,
    );
    const offenders: string[] = [];
    sigs.forEach((sig, i) => {
      if (!sig || typeof sig !== 'object') {
        offenders.push(`signatures[${i}] is not an object`);
        return;
      }
      const s = sig as Record<string, unknown>;
      const protectedField = s.protected;
      const signature = s.signature;
      if (
        typeof protectedField !== 'string' ||
        !BASE64URL.test(protectedField)
      ) {
        offenders.push(
          `signatures[${i}].protected MUST be a base64url string`,
        );
      }
      if (typeof signature !== 'string' || !BASE64URL.test(signature)) {
        offenders.push(
          `signatures[${i}].signature MUST be a base64url string`,
        );
      }
      if (s.header != null && (typeof s.header !== 'object' || Array.isArray(s.header))) {
        offenders.push(
          `signatures[${i}].header MUST be an object when present`,
        );
      }
    });
    assert(offenders.length === 0, offenders.join('; '));
  },
};

export const agentCardProtocolVersionFormat: Contract = {
  id: 'transport.agent_card_protocol_version_format',
  specSection: '§3.6',
  description:
    'supportedInterfaces[*].protocolVersion is Major.Minor (no patch).',
  category: 'transport',
  async verify(agentUrl) {
    const { body } = await fetchCard(agentUrl);
    const interfaces = (body as { supportedInterfaces?: unknown })
      .supportedInterfaces;
    if (!Array.isArray(interfaces)) return;
    const offenders: string[] = [];
    interfaces.forEach((entry, i) => {
      const v = (entry as Record<string, unknown>)?.protocolVersion;
      if (v == null) return;
      if (typeof v !== 'string') {
        offenders.push(
          `supportedInterfaces[${i}].protocolVersion must be a string`,
        );
        return;
      }
      if (!/^\d+\.\d+$/.test(v)) {
        offenders.push(
          `supportedInterfaces[${i}].protocolVersion ${JSON.stringify(v)} MUST match Major.Minor`,
        );
      }
    });
    assert(offenders.length === 0, offenders.join('; '));
  },
};
