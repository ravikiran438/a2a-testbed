# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Reference A2A agents built on the official a2a-sdk, for conformance tests.

The conformance contracts are only as good as the oracle they are
validated against. These agents are built from the a2a-sdk's own server
stack (``DefaultRequestHandler`` + ``create_jsonrpc_routes``), so their
wire behaviour is by construction what the spec's reference SDK does:

- ``"1.0"``: a pure A2A 1.0 agent (1.0 card, 1.0 methods only).
- ``"0.3"``: a legacy agent — a 0.3-layout card, served through the
  SDK's ``enable_v0_3_compat`` adapter so 0.3 clients (no
  ``A2A-Version`` header, ``message/send`` …) get 0.3 payloads.
- ``"dual"``: one endpoint serving both, advertised the way the SDK
  does it (1.0 card + 0.3 interface, 0.3 fields merged into the card).

Both run an "echo over time" executor that mirrors the hosted
reference task runner: the text may carry ``count: N`` and the agent
emits N artifacts 50ms apart before completing, so contracts can act on
a task while it is still running.

A tiny push-notification receiver (:func:`build_push_receiver`) mirrors
``push.a2a-testbed.com`` so ``push_fires_on_completion`` can run offline.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import socket
from collections.abc import AsyncIterator
from typing import Any

import httpx
import uvicorn
from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
    TaskUpdater,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a_testbed.transport.dialect import card_to_v03_json

CARD_PATH = "/.well-known/agent-card.json"
RPC_PATH = "/a2a/v1/"


class EchoOverTimeExecutor(AgentExecutor):
    """Creates a Task and emits ``count: N`` artifacts 50ms apart."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        m = re.search(r"(?:count\s*:\s*)?(\d+)", text)
        count = max(1, min(int(m.group(1)), 20)) if m else 3
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        for i in range(1, count + 1):
            await asyncio.sleep(0.05)
            await updater.add_artifact([Part(text=f"unit {i}/{count}: {text}")], name=f"echo-{i}")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


def _card(base_url: str, protocol_version: str) -> AgentCard:
    return AgentCard(
        name=f"SDK oracle ({protocol_version})",
        description="a2a-sdk reference agent used to validate the conformance contracts",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=base_url.rstrip("/") + RPC_PATH,
                protocol_binding="JSONRPC",
                protocol_version=protocol_version,
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="echo_over_time",
                name="Echo over time",
                description="Echo the input over N artifact updates.",
                tags=["echo"],
            )
        ],
    )


def build_sdk_agent(base_url: str, protocol_version: str) -> Starlette:
    """A Starlette app serving an a2a-sdk agent in the given protocol version.

    ``"dual"`` is the SDK's own dual-version setup: a 1.0 card that also
    lists a 0.3 interface (the SDK merges the 0.3 top-level fields into
    the served card) with ``enable_v0_3_compat`` on the same endpoint.
    """
    if protocol_version == "dual":
        card = _card(base_url, "1.0")
        card.supported_interfaces.append(
            AgentInterface(
                url=base_url.rstrip("/") + RPC_PATH,
                protocol_binding="JSONRPC",
                protocol_version="0.3",
            )
        )
        push_store = InMemoryPushNotificationConfigStore()
        handler = DefaultRequestHandler(
            agent_executor=EchoOverTimeExecutor(),
            task_store=InMemoryTaskStore(),
            agent_card=card,
            push_config_store=push_store,
            push_sender=BasePushNotificationSender(httpx.AsyncClient(timeout=5.0), push_store),
        )
        routes = create_jsonrpc_routes(handler, RPC_PATH, enable_v0_3_compat=True)
        routes.extend(create_agent_card_routes(card, card_url=CARD_PATH))
        return Starlette(routes=routes)
    card = _card(base_url, protocol_version)
    push_store = InMemoryPushNotificationConfigStore()
    handler = DefaultRequestHandler(
        agent_executor=EchoOverTimeExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
        push_config_store=push_store,
        push_sender=BasePushNotificationSender(httpx.AsyncClient(timeout=5.0), push_store),
    )
    legacy = protocol_version.startswith("0.")
    routes = create_jsonrpc_routes(handler, RPC_PATH, enable_v0_3_compat=legacy)
    if legacy:
        card_json = card_to_v03_json(card)

        async def legacy_card(_request: Request) -> JSONResponse:
            return JSONResponse(card_json)

        routes.append(Route(CARD_PATH, legacy_card, methods=["GET"]))
    else:
        routes.extend(create_agent_card_routes(card, card_url=CARD_PATH))
    return Starlette(routes=routes)


def build_push_receiver() -> Starlette:
    """Capture webhooks per token, like push.a2a-testbed.com."""
    received: dict[str, list[dict[str, Any]]] = {}

    async def webhook(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        body = (await request.body()).decode("utf-8", "replace")
        received.setdefault(token, []).append({"body": body, "headers": dict(request.headers)})
        return JSONResponse({"ok": True})

    async def read(request: Request) -> JSONResponse:
        return JSONResponse({"hooks": received.get(request.path_params["token"], [])})

    return Starlette(
        routes=[
            Route("/webhook/{token}", webhook, methods=["POST"]),
            Route("/received/{token}", read, methods=["GET"]),
        ]
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def serve(app_factory, port: int | None = None) -> AsyncIterator[str]:
    """Run ``app_factory(base_url)`` under uvicorn; yield the base URL."""
    port = port or free_port()
    base_url = f"http://127.0.0.1:{port}"
    app = app_factory(base_url)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.025)
    try:
        yield base_url
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await task
