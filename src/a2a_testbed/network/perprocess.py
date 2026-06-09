# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Per-process network: each agent gets its own port + lifecycle.

This is *realistic mode* — used when a scenario must validate
production-topology behavior:
  - cross-SDK conformance runs (Go agent + Python agent on the wire)
  - per-agent identity / TLS posture
  - latency or disconnect tests where a real socket matters

Compared to the multi-tenant sim mode:
  - boots slower (one socket per agent)
  - cards' URLs reflect each agent's actual bound port
  - subprocess runtimes are first-class citizens

For Python in-process agents in realistic mode we still need an HTTP
server, so we wrap each one in a ``SingleAgentServer`` that hosts that
agent under the active transport's endpoint paths. Subprocess and
external runtimes already manage their own URL.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from typing import Optional

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from a2a_testbed.core.types import AgentDecl
from a2a_testbed.runtimes import (
    AgentRuntime,
    ExternalRuntime,
    PythonInProcRuntime,
)
from a2a_testbed.transport import A2ATransport, Transport


logger = logging.getLogger(__name__)


def _free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class PerProcessNetwork:
    """Run each agent on its own URL using its declared runtime."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        log_level: str = "warning",
        transport: Optional[Transport] = None,
    ) -> None:
        self._host = host
        self._log_level = log_level
        self._transport: Transport = transport or A2ATransport()
        self._registered: list[tuple[AgentDecl, AgentRuntime]] = []
        self._inproc_servers: dict[str, "_SingleAgentServer"] = {}
        self._traffic_taps: list = []

    @property
    def transport(self) -> Transport:
        return self._transport

    def register(self, decl: AgentDecl, runtime: AgentRuntime) -> None:
        self._registered.append((decl, runtime))

    def attach_traffic_tap(self, tap) -> None:
        self._traffic_taps.append(tap)

    def urls(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for decl, runtime in self._registered:
            if isinstance(runtime, PythonInProcRuntime):
                server = self._inproc_servers[decl.id]
                out[decl.id] = server.url
            else:
                out[decl.id] = runtime.url
        return out

    async def start(self) -> None:
        try:
            from sse_starlette.sse import AppStatus

            AppStatus.should_exit = False
            AppStatus.disable_automatic_graceful_drain()
        except ImportError:
            pass

        # Start in-proc agents on their own single-agent servers
        for decl, runtime in self._registered:
            if isinstance(runtime, PythonInProcRuntime):
                server = _SingleAgentServer(
                    runtime=runtime,
                    transport=self._transport,
                    host=self._host,
                    log_level=self._log_level,
                    traffic_taps=self._traffic_taps,
                )
                await server.start()
                runtime.attach(server.url, runtime.agent_card)
                self._inproc_servers[decl.id] = server
            elif isinstance(runtime, ExternalRuntime):
                # Already running — nothing to start.
                pass
            else:
                # Subprocess: spawn the process; it prints its url on stdout.
                await runtime.start()

    async def stop(self) -> None:
        for server in self._inproc_servers.values():
            await server.stop()
        self._inproc_servers.clear()
        for decl, runtime in self._registered:
            if not isinstance(runtime, (PythonInProcRuntime, ExternalRuntime)):
                await runtime.stop()
        self._registered.clear()
        self._traffic_taps.clear()

    async def __aenter__(self) -> "PerProcessNetwork":
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()


class _SingleAgentServer:
    """Host one PythonInProcRuntime under the transport's endpoint paths."""

    def __init__(
        self,
        runtime: PythonInProcRuntime,
        transport: Transport,
        host: str,
        log_level: str,
        traffic_taps: list,
    ) -> None:
        self._runtime = runtime
        self._transport = transport
        self._host = host
        self._log_level = log_level
        self._traffic_taps = traffic_taps
        self._port = _free_port(host)
        self._server: Optional[uvicorn.Server] = None
        self._serve_task: Optional[asyncio.Task[None]] = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def start(self) -> None:
        card_path = self._transport.card_endpoint_path()
        rpc_path = self._transport.rpc_endpoint_path()

        async def card_handler(_request: Request) -> Response:
            payload = self._transport.serialize_card(self._runtime.agent_card)
            return JSONResponse(payload)

        async def rpc_handler(request: Request) -> Response:
            try:
                body = await request.json()
            except json.JSONDecodeError:
                return JSONResponse(
                    self._transport.build_error_response({}, -32700, "parse error"),
                    status_code=400,
                )
            method = body.get("method") if isinstance(body, dict) else None
            if method != "message/send":
                error_payload = self._transport.build_error_response(
                    body, -32601, f"method not implemented: {method!r}"
                )
                return JSONResponse(error_payload)
            params = body.get("params") if isinstance(body, dict) else None
            message = params.get("message") if isinstance(params, dict) else None
            valid = (
                isinstance(message, dict)
                and message.get("role")
                and message.get("messageId")
                and isinstance(message.get("parts"), list)
                and len(message["parts"]) > 0
            )
            if not valid:
                error_payload = self._transport.build_error_response(
                    body,
                    -32602,
                    "invalid params: message MUST have role, messageId, and ≥1 part (A2A 1.0 §3.1.1)",
                )
                return JSONResponse(error_payload)
            text = self._transport.extract_text_for_scripting(body)
            scripted = self._runtime.script_for(text)
            response_body = self._transport.build_response(body, self._runtime.agent_id, scripted)
            for tap in self._traffic_taps:
                try:
                    tap(self._runtime.agent_id, body, response_body)
                except Exception:
                    logger.exception("traffic tap raised; continuing")
            return JSONResponse(response_body)

        routes = [
            Route(card_path, card_handler, methods=["GET"]),
            Route(rpc_path, rpc_handler, methods=["POST"]),
        ]
        if rpc_path.endswith("/"):
            routes.append(Route(rpc_path[:-1], rpc_handler, methods=["POST"]))

        app = Starlette(routes=routes)
        config = uvicorn.Config(
            app=app, host=self._host, port=self._port, log_level=self._log_level
        )
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        for _ in range(100):
            if self._server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError(f"_SingleAgentServer for {self._runtime.agent_id} did not start")

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._serve_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._serve_task
            self._serve_task = None
