/**
 * A2A push-notification receiver. Captures incoming webhooks from
 * cloudflare-task-runner (or any A2A agent firing push) and exposes
 * a read-back endpoint so conformance tests can verify delivery.
 *
 * The token in the URL is opaque — the receiver doesn't validate
 * it. Test code generates a fresh token per probe so concurrent
 * tests don't see each other's webhooks.
 *
 * Storage is KV so reads are consistent across isolates. Captures
 * auto-expire after one hour to keep the namespace bounded.
 */

interface Env {
  RECEIVED: KVNamespace;
  RECEIVER_RATE_LIMITER: {
    limit: (opts: { key: string }) => Promise<{ success: boolean }>;
  };
}

// Cap on a single webhook body — agents POSTing massive payloads
// would otherwise let an attacker inflate KV storage cheaply. Real
// A2A Tasks fit comfortably under 64KB.
const MAX_WEBHOOK_BYTES = 64 * 1024;

interface CapturedHook {
  receivedAt: string;
  authorization: string | null;
  body: string;
}

const CORS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, authorization",
  "access-control-max-age": "86400",
};

const TTL_SECONDS = 60 * 60;

async function appendHook(
  env: Env,
  token: string,
  hook: CapturedHook,
): Promise<void> {
  const raw = await env.RECEIVED.get(token);
  const list: CapturedHook[] = raw ? (JSON.parse(raw) as CapturedHook[]) : [];
  list.push(hook);
  await env.RECEIVED.put(token, JSON.stringify(list), {
    expirationTtl: TTL_SECONDS,
  });
}

async function readHooks(env: Env, token: string): Promise<CapturedHook[]> {
  const raw = await env.RECEIVED.get(token);
  return raw ? (JSON.parse(raw) as CapturedHook[]) : [];
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    const webhookMatch = /^\/webhook\/([A-Za-z0-9_-]+)\/?$/.exec(url.pathname);
    if (req.method === "POST" && webhookMatch) {
      const ip = req.headers.get("cf-connecting-ip") ?? "unknown";
      const { success } = await env.RECEIVER_RATE_LIMITER.limit({ key: ip });
      if (!success) {
        return new Response("rate limit exceeded", {
          status: 429,
          headers: { ...CORS, "retry-after": "60" },
        });
      }
      const token = webhookMatch[1] as string;
      const body = await req.text();
      if (body.length > MAX_WEBHOOK_BYTES) {
        return new Response("payload too large", {
          status: 413,
          headers: CORS,
        });
      }
      await appendHook(env, token, {
        receivedAt: new Date().toISOString(),
        authorization: req.headers.get("authorization"),
        body,
      });
      return Response.json({ ok: true }, { headers: CORS });
    }

    const readMatch = /^\/received\/([A-Za-z0-9_-]+)\/?$/.exec(url.pathname);
    if (req.method === "GET" && readMatch) {
      const token = readMatch[1] as string;
      const hooks = await readHooks(env, token);
      return Response.json({ token, hooks }, { headers: CORS });
    }

    if (req.method === "GET" && url.pathname === "/") {
      return Response.json(
        {
          name: "a2a-push-receiver",
          description:
            "Captures push notifications. POST /webhook/<token> to record; " +
            "GET /received/<token> to read.",
        },
        { headers: CORS },
      );
    }

    return new Response("Not Found", { status: 404, headers: CORS });
  },
} satisfies ExportedHandler<Env>;
