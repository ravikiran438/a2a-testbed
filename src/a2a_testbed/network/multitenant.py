# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Multi-tenant network: one HTTP server, N in-process agents on path prefixes.

URL layout (paths driven by the active Transport, not hardcoded):

    http://127.0.0.1:<port>/agents/<agent_id>/<transport.card_endpoint_path()>
    http://127.0.0.1:<port>/agents/<agent_id>/<transport.rpc_endpoint_path()>

Sim mode hosts every agent in one Starlette process behind path
prefixes. Boot is near-instant, port allocation is deterministic,
and cross-agent state (observer hub, faults, virtual time) is shared
trivially through in-process references.

The network is wire-format-agnostic: every path / serialization /
parsing decision delegates to the active ``Transport``. Adding a
non-A2A inter-agent protocol means implementing one ``Transport``
subclass; the network and orchestrator stay unchanged.
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

from a2a_testbed.runtimes.python_inproc import PythonInProcRuntime
from a2a_testbed.transport import A2ATransport, Transport


logger = logging.getLogger(__name__)


def _free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class MultiTenantNetwork:
    """Hosts multiple in-process agents on one Starlette+uvicorn server."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        log_level: str = "warning",
        transport: Optional[Transport] = None,
    ) -> None:
        self._host = host
        self._log_level = log_level
        self._port = _free_port(host)
        self._transport: Transport = transport or A2ATransport()
        self._runtimes: dict[str, PythonInProcRuntime] = {}
        self._server: Optional[uvicorn.Server] = None
        self._serve_task: Optional[asyncio.Task[None]] = None
        self._traffic_taps: list[callable] = []

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def transport(self) -> Transport:
        return self._transport

    def url_of(self, agent_id: str) -> str:
        if agent_id not in self._runtimes:
            raise KeyError(f"unknown agent id: {agent_id!r}")
        return f"{self.base_url}/agents/{agent_id}"

    def runtime(self, agent_id: str) -> PythonInProcRuntime:
        if agent_id not in self._runtimes:
            raise KeyError(f"unknown agent id: {agent_id!r}")
        return self._runtimes[agent_id]

    def register(self, runtime: PythonInProcRuntime) -> None:
        if runtime.agent_id in self._runtimes:
            raise ValueError(f"duplicate agent id: {runtime.agent_id!r}")
        self._runtimes[runtime.agent_id] = runtime

    def attach_traffic_tap(self, tap) -> None:
        """Register a callback that receives every request/response pair.

        Signature: ``tap(agent_id: str, request_body: dict,
        response_body: dict) -> None``. Used by observer agents to
        accumulate the audit trail without sitting in the message path.
        """
        self._traffic_taps.append(tap)

    async def start(self) -> None:
        try:
            from sse_starlette.sse import AppStatus
            AppStatus.should_exit = False
            AppStatus.disable_automatic_graceful_drain()
        except ImportError:
            pass

        # Build URL-aware AgentCards now that we know our base port.
        rpc_path = self._transport.rpc_endpoint_path()
        for runtime in self._runtimes.values():
            base_url = self.url_of(runtime.agent_id)
            live_card = self._fix_card_url(
                runtime.agent_card, base_url + rpc_path
            )
            runtime.attach(base_url, live_card)
            await runtime.start()

        app = Starlette(routes=self._build_routes())
        config = uvicorn.Config(
            app=app,
            host=self._host,
            port=self._port,
            log_level=self._log_level,
        )
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        await self._wait_until_ready()
        logger.info(
            "MultiTenantNetwork[%s] up at %s with %d agents",
            self._transport.name,
            self.base_url,
            len(self._runtimes),
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._serve_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._serve_task
            self._serve_task = None
        for runtime in self._runtimes.values():
            await runtime.stop()
        self._runtimes.clear()
        self._traffic_taps.clear()

    async def __aenter__(self) -> "MultiTenantNetwork":
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _build_routes(self) -> list[Route]:
        card_path = self._transport.card_endpoint_path()
        rpc_path = self._transport.rpc_endpoint_path()
        # Trim leading slash from transport-supplied paths; we mount
        # under "/agents/<id>" already.
        if card_path.startswith("/"):
            card_path = card_path[1:]
        if rpc_path.startswith("/"):
            rpc_path = rpc_path[1:]

        routes: list[Route] = [
            Route("/health", self._health, methods=["GET"]),
        ]
        for agent_id in self._runtimes:
            routes.append(
                Route(
                    f"/agents/{agent_id}/{card_path}",
                    self._make_card_handler(agent_id),
                    methods=["GET"],
                )
            )
            routes.append(
                Route(
                    f"/agents/{agent_id}/{rpc_path}",
                    self._make_rpc_handler(agent_id),
                    methods=["POST"],
                )
            )
            # Tolerate trailing-slash variant if the transport's path ends in /
            if rpc_path.endswith("/"):
                routes.append(
                    Route(
                        f"/agents/{agent_id}/{rpc_path[:-1]}",
                        self._make_rpc_handler(agent_id),
                        methods=["POST"],
                    )
                )
        return routes

    async def _health(self, _request: Request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "transport": self._transport.name,
                "agents": sorted(self._runtimes),
            }
        )

    def _make_card_handler(self, agent_id: str):
        async def handler(_request: Request) -> Response:
            runtime = self._runtimes[agent_id]
            payload = self._transport.serialize_card(runtime.agent_card)
            return JSONResponse(payload)
        return handler

    def _make_rpc_handler(self, agent_id: str):
        runtime = self._runtimes[agent_id]

        async def handler(request: Request) -> Response:
            try:
                body = await request.json()
            except json.JSONDecodeError:
                error_payload = self._transport.build_error_response(
                    {}, -32700, "parse error"
                )
                return JSONResponse(error_payload, status_code=400)

            method = body.get("method") if isinstance(body, dict) else None

            # Only message/send is currently implemented; other A2A
            # methods (streaming, push notifications, extended cards)
            # are not exercised by sim-mode networks. Unknown methods
            # MUST return -32601 per JSON-RPC 2.0 §5.1.
            if method != "message/send":
                error_payload = self._transport.build_error_response(
                    body, -32601, f"method not implemented: {method!r}"
                )
                for tap in self._traffic_taps:
                    try:
                        tap(agent_id, body, error_payload)
                    except Exception:
                        logger.exception("traffic tap raised; continuing")
                return JSONResponse(error_payload)

            # Spec §3.1.1: message MUST have role, messageId, and ≥1 part.
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
                for tap in self._traffic_taps:
                    try:
                        tap(agent_id, body, error_payload)
                    except Exception:
                        logger.exception("traffic tap raised; continuing")
                return JSONResponse(error_payload)

            text = self._transport.extract_text_for_scripting(body)
            scripted = runtime.script_for(text)
            response_payload = self._transport.build_response(
                body, agent_id, scripted
            )

            for tap in self._traffic_taps:
                try:
                    tap(agent_id, body, response_payload)
                except Exception:
                    logger.exception("traffic tap raised; continuing")

            return JSONResponse(response_payload)

        return handler

    @staticmethod
    def _fix_card_url(card_payload, full_rpc_url: str):
        """Set the agent card's bound URL to the actual rpc endpoint.

        Done generically: we serialize through the transport, mutate
        the supportedInterfaces[0].url field if present, and parse
        back. The transport-specific bits are isolated to the load /
        serialize calls.
        """
        from a2a.types import AgentCard
        from google.protobuf.json_format import MessageToJson, Parse
        clone = Parse(MessageToJson(card_payload), AgentCard())
        if clone.supported_interfaces:
            clone.supported_interfaces[0].url = full_rpc_url
        return clone

    async def _wait_until_ready(self) -> None:
        for _ in range(100):
            if self._server is not None and self._server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("MultiTenantNetwork failed to start within 5s")
