#!/usr/bin/env python3
# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Python reference agent for the a2a-testbed subprocess runtime.

Reads CLI args ``--agent-card``, ``--scripts``, ``--port``; binds an HTTP
server on 127.0.0.1; serves the AgentCard at the well-known URL and a
minimal JSON-RPC ``message/send`` endpoint that matches the incoming
text against the scripts map.

Prints exactly one line ``A2A_TESTBED_READY: http://127.0.0.1:<port>`` on
stdout once it's listening so the orchestrator can discover the bound
port. Implementation deliberately uses stdlib only (http.server) to
keep this template a verifiable demonstration of the wire protocol;
production agents will swap this for the official a2a-sdk.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _match_script(text: str, scripts: dict[str, str]) -> str:
    text_lower = text.lower()
    for key, response in scripts.items():
        if key.lower() in text_lower:
            return response
    return f"received: {text or '(empty)'}"


def _extract_text(params: Any) -> str:
    if not isinstance(params, dict):
        return ""
    message = params.get("message")
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or []
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            t = part.get("text") or ""
            if t:
                chunks.append(t)
    return " ".join(chunks)


def make_handler(card: dict, scripts: dict[str, str], agent_id: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/.well-known/agent-card.json"):
                body = json.dumps(card).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._jsonrpc_error(None, -32700, "parse error")
                return
            method = payload.get("method")
            jsonrpc_id = payload.get("id")
            if method != "message/send":
                self._jsonrpc_error(jsonrpc_id, -32601, f"unknown method {method!r}")
                return
            text = _extract_text(payload.get("params"))
            response = _match_script(text, scripts)
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": jsonrpc_id,
                    "result": {
                        "kind": "message",
                        "messageId": f"resp-{jsonrpc_id}",
                        "role": "assistant",
                        "parts": [{"kind": "text", "text": f"[{agent_id}] {response}"}],
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _jsonrpc_error(self, jsonrpc_id, code: int, message: str) -> None:
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": jsonrpc_id,
                    "error": {"code": code, "message": message},
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # silence stdout
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-card", required=True, type=Path)
    parser.add_argument("--scripts", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    card = json.loads(args.agent_card.read_text())
    scripts = json.loads(args.scripts.read_text())
    agent_id = card.get("name", "agent")

    handler_cls = make_handler(card, scripts, agent_id)
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    bound_port = server.server_address[1]
    print(f"A2A_TESTBED_READY: http://{args.host}:{bound_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
