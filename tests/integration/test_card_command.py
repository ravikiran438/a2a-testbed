# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""End-to-end test for the ``a2a-testbed card`` CLI command.

Spins up a tiny HTTP server hosting (1) an AgentCard declaring two
extensions and (2) the matching ExtensionManifests, then runs the
``card`` CLI flow programmatically and asserts every declared
extension is reported ``DECLARED_OK`` against its manifest.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from a2a_testbed.manifest import (
    ExtensionManifest,
    FindingKind,
    HttpManifestStore,
    InMemoryManifestStore,
    validate_agent_card,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_card(host: str, port: int) -> dict:
    """AgentCard JSON that declares the four core protocols."""
    base = f"http://{host}:{port}"
    return {
        "name": "manifest-validation-test-agent",
        "description": "Demo card for testbed manifest validator",
        "version": "1.0.0",
        "url": base,
        "supportedInterfaces": [
            {"url": f"{base}/", "protocolBinding": "JSONRPC"}
        ],
        "skills": [
            {
                "id": "demo",
                "name": "Demo skill",
                "description": "A demo skill",
                "tags": ["demo"],
            }
        ],
        "capabilities": {
            "streaming": False,
            "extensions": [
                {
                    "uri": f"{base}/test/agent-consent-protocol/v1",
                    "params": {
                        "version": "1.0.0",
                        "document_uri": f"{base}/policy.json",
                        "document_hash": "sha256:" + "a" * 64,
                        "effective_date": "2026-04-01T00:00:00Z",
                        "acceptance_required": False,
                        "natural_language_uri": f"{base}/terms",
                    },
                },
                {
                    "uri": f"{base}/test/phala-protocol/v1",
                    "params": {
                        "version": "1.0.0",
                        "outcome_endpoint": f"{base}/phala/outcomes",
                        "satisfaction_endpoint": f"{base}/phala/satisfactions",
                        "belief_update_endpoint": f"{base}/phala/belief_updates",
                        "weight_keys": ["k1"],
                        "learning_rate": 0.05,
                        "weight_bounds": {"min": -1.0, "max": 1.0},
                    },
                },
            ],
        },
    }


def _load_manifest(repo: str) -> ExtensionManifest:
    path = REPO_ROOT.parent / repo / "v1" / "manifest.json"
    return ExtensionManifest.model_validate_json(path.read_text(encoding="utf-8"))


class _Handler(BaseHTTPRequestHandler):
    """Serves the card at /.well-known/agent-card.json and manifests at
    /test/<protocol>/v1/manifest.json. Test fixture only — no auth, no
    error handling beyond what we need."""

    def log_message(self, *args, **kwargs):  # silence stderr noise
        return

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        path = self.path
        if path == "/.well-known/agent-card.json":
            host, port = self.server.server_address
            payload = json.dumps(_make_card(host, port)).encode("utf-8")
        elif path.startswith("/test/agent-consent-protocol/v1/manifest.json"):
            payload = self._rewrite_manifest_uri(
                _load_manifest("agent-consent-protocol"),
                expected_path="/test/agent-consent-protocol/v1",
            )
        elif path.startswith("/test/phala-protocol/v1/manifest.json"):
            payload = self._rewrite_manifest_uri(
                _load_manifest("phala-protocol"),
                expected_path="/test/phala-protocol/v1",
            )
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _rewrite_manifest_uri(
        self, manifest: ExtensionManifest, expected_path: str
    ) -> bytes:
        host, port = self.server.server_address
        copy = manifest.model_dump(by_alias=True, exclude_none=True)
        copy["extension"]["uri"] = f"http://{host}:{port}{expected_path}"
        return json.dumps(copy).encode("utf-8")


@pytest.fixture
def fake_agent_server():
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_card_command_validates_all_declared_extensions(fake_agent_server):
    base = fake_agent_server
    # Reuse the same logic the CLI runs; equivalent to invoking
    # ``a2a-testbed card <base>``.
    import httpx

    async def run() -> list:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/.well-known/agent-card.json")
        card = json.loads(resp.text)
        store = HttpManifestStore()
        return await validate_agent_card(card, store=store)

    findings = asyncio.run(run())
    assert len(findings) == 2, [f.extension_uri for f in findings]
    for f in findings:
        assert f.kind == FindingKind.DECLARED_OK, (f.extension_uri, f.detail, f.schema_errors)


def test_card_command_reports_unknown_uris(fake_agent_server):
    """An unknown URI in the card produces MANIFEST_NOT_FOUND, not crash."""
    import httpx

    base = fake_agent_server
    async def run() -> list:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/.well-known/agent-card.json")
        card = json.loads(resp.text)
        # Inject a bogus URI.
        card["capabilities"]["extensions"].append(
            {"uri": "https://example.org/unknown-extension/v1", "params": {"x": 1}}
        )
        store = HttpManifestStore()
        return await validate_agent_card(card, store=store)

    findings = asyncio.run(run())
    kinds = {f.kind for f in findings}
    assert FindingKind.DECLARED_OK in kinds
    assert FindingKind.MANIFEST_NOT_FOUND in kinds


def test_card_command_catches_broken_payload(fake_agent_server):
    """Mutating a declared payload to omit a required field surfaces it."""
    import httpx

    base = fake_agent_server
    async def run() -> list:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/.well-known/agent-card.json")
        card = json.loads(resp.text)
        # Drop a required field from the Phala declaration.
        for entry in card["capabilities"]["extensions"]:
            if entry["uri"].endswith("phala-protocol/v1"):
                del entry["params"]["belief_update_endpoint"]
        store = HttpManifestStore()
        return await validate_agent_card(card, store=store)

    findings = asyncio.run(run())
    invalid = [f for f in findings if f.kind == FindingKind.DECLARED_INVALID]
    assert len(invalid) == 1
    assert any("belief_update_endpoint" in err for err in invalid[0].schema_errors)


def test_in_memory_store_short_circuits_http(monkeypatch):
    """Pre-populated InMemoryManifestStore should be enough — no network.

    Independent of fake_agent_server: just exercises that the validator
    accepts a full in-memory cache and doesn't fall through.
    """
    uri = "https://example.org/runtime-only/v1"
    from a2a_testbed.manifest import generate_manifest

    manifest = generate_manifest(
        extension_uri=uri,
        name="Runtime-Only",
        version="1.0.0",
    )
    card = {
        "name": "x",
        "capabilities": {
            "extensions": [{"uri": uri, "params": {"any": "object"}}]
        },
    }

    async def run() -> list:
        return await validate_agent_card(
            card, store=InMemoryManifestStore({uri: manifest})
        )

    findings = asyncio.run(run())
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.DECLARED_OK
