#!/usr/bin/env node
// Copyright 2026 Ravi Kiran Kadaboina
// Licensed under the Apache License, Version 2.0.
//
// Node.js reference agent for the a2a-testbed subprocess runtime.
//
// Reads CLI args --agent-card, --scripts, --port; binds an HTTP server
// on 127.0.0.1; serves the AgentCard at the well-known URL and a
// minimal JSON-RPC message/send endpoint. Prints
// "A2A_TESTBED_READY: <url>" on stdout when listening.
//
// Stdlib only (node:http) to keep this template verifiable. Real
// agents would swap to @a2a-js/sdk for full A2A compliance.

import http from 'node:http';
import fs from 'node:fs';
import process from 'node:process';

function parseArgs(argv) {
  const out = { port: 0, host: '127.0.0.1' };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (k === '--agent-card') { out.cardPath = v; i++; }
    else if (k === '--scripts') { out.scriptsPath = v; i++; }
    else if (k === '--port') { out.port = parseInt(v, 10); i++; }
    else if (k === '--host') { out.host = v; i++; }
  }
  if (!out.cardPath || !out.scriptsPath) {
    console.error('usage: node index.js --agent-card <path> --scripts <path> [--port N]');
    process.exit(2);
  }
  return out;
}

function matchScript(text, scripts) {
  const lower = (text || '').toLowerCase();
  for (const [key, response] of Object.entries(scripts)) {
    if (lower.includes(key.toLowerCase())) return response;
  }
  return `received: ${text || '(empty)'}`;
}

function extractText(params) {
  const message = params && params.message;
  if (!message || !Array.isArray(message.parts)) return '';
  const chunks = [];
  for (const part of message.parts) {
    if (part && typeof part.text === 'string' && part.text) chunks.push(part.text);
  }
  return chunks.join(' ');
}

function jsonResponse(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

async function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')));
    req.on('error', reject);
  });
}

function main() {
  const args = parseArgs(process.argv);
  const card = JSON.parse(fs.readFileSync(args.cardPath, 'utf-8'));
  const scripts = JSON.parse(fs.readFileSync(args.scriptsPath, 'utf-8'));
  const agentId = card.name || 'agent';

  const server = http.createServer(async (req, res) => {
    if (req.method === 'GET' && req.url && req.url.endsWith('/.well-known/agent-card.json')) {
      jsonResponse(res, 200, card);
      return;
    }
    if (req.method !== 'POST') {
      res.writeHead(404); res.end(); return;
    }
    let payload;
    try {
      const raw = await readBody(req);
      payload = JSON.parse(raw || '{}');
    } catch {
      jsonResponse(res, 200, { jsonrpc: '2.0', id: null, error: { code: -32700, message: 'parse error' } });
      return;
    }
    const id = payload.id ?? null;
    if (payload.method !== 'message/send') {
      jsonResponse(res, 200, { jsonrpc: '2.0', id, error: { code: -32601, message: `unknown method ${payload.method}` } });
      return;
    }
    const text = extractText(payload.params);
    const response = matchScript(text, scripts);
    jsonResponse(res, 200, {
      jsonrpc: '2.0',
      id,
      result: {
        kind: 'message',
        messageId: `resp-${id}`,
        role: 'assistant',
        parts: [{ kind: 'text', text: `[${agentId}] ${response}` }],
      },
    });
  });

  server.listen(args.port, args.host, () => {
    const addr = server.address();
    console.log(`A2A_TESTBED_READY: http://${args.host}:${addr.port}`);
  });

  for (const sig of ['SIGTERM', 'SIGINT']) {
    process.on(sig, () => server.close(() => process.exit(0)));
  }
}

main();
